"""M4 step 4: registry only (A) vs registry + local LLM fallback (B), offline.

The LLM (config `llm`, via src/kg/llm.py) runs only on body blocks where the
registry finds at most `layer2.llm_fallback_max_entities` non-hub entities, and
on change texts under the same rule. Kept terms must occur in the block; they
link to a registry entity by alias or become LLM-sourced entities. Hubs are
recomputed over registry and LLM mentions together. Nothing is written to Neo4j.

Reported per language:
1. review pairs (states / depends; historical apart) linked by a shared non-hub
   entity, and judged negatives that become linked;
2. body blocks of the initial corpus still without any entity;
3. JSON valid on the first attempt, terms dropped as not in the block;
4. stability: the initial-corpus blocks sent to the LLM are run a second time
   with the cache off; Jaccard overlap of the two entity sets per block;
5. cost: seconds per block, tokens in / out, peak GPU memory (nvidia-smi);
6. mention precision / recall: only a person's sheet counts.

Label source: --labels ai | human (merged M5 labels, eval/m5_labels.py).
Registry: automatic (manual entries with source documents only).
Writes eval/results/m4_llm_fallback_<source>.md; per-block LLM output (document
text) to data/labels/m4_llm_fallback_detail.json (not in git).

Run:  uv run --group embed python eval/m4_llm_fallback.py [--no-stability]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from collections import Counter, defaultdict
from statistics import mean, median

from compare_embeddings import change_contexts
from label_sources import DESCRIPTION, answered, read_rows, sheet
from m4_registry_coverage import T0, negatives_by_event
from m5_labels import by_change, positives
from make_change_test_set import LABELS, ROOT

from kg.config import load_config
from kg.layer0_structure import parse_corpus
from kg.layer2_entities import (
    EntityMatcher,
    LLMFallback,
    build_registry,
    load_manual,
)
from kg.llm import LLMClient


class GpuPeak:
    """Samples nvidia-smi memory.used every second while running."""

    def __init__(self) -> None:
        self.peak, self.base, self._stop = 0, None, threading.Event()

    def _read(self) -> int | None:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                                  "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout
            return int(out.strip().splitlines()[0])
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return None

    def __enter__(self):
        self.base = self._read()

        def loop():
            while not self._stop.is_set():
                v = self._read()
                if v is not None:
                    self.peak = max(self.peak, v)
                time.sleep(1)
        self._t = threading.Thread(target=loop, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join()


class Variant:
    """Entity sets per text for one store: registry (A) or registry + LLM (B)."""

    def __init__(self, docs, documents, cut, fallback_factory=None):
        self.reg = build_registry(docs, documents)
        self.matcher = EntityMatcher(self.reg)
        self.fb = fallback_factory(self.reg) if fallback_factory else None
        self.cut = cut
        self.lang = {}
        texts = {}
        for d in docs:
            for pb in d.blocks:
                if pb.block.role.value == "body":
                    texts[pb.block.block_uid] = (pb.block.text, d.document.language.value)
        # registry entities first; hubs from registry shares (as layer 2 does)
        raw = {u: {e for e, _ in self.matcher.find(t, l)} for u, (t, l) in texts.items()}
        hubs0 = self._hubs(raw, texts)
        self.ents = {}
        for u, (t, l) in texts.items():
            e = set(raw[u])
            if self.fb:
                e |= self.fb.entities_for(t, l, raw[u] - hubs0)
            self.ents[u] = e
        self.hubs = self._hubs(self.ents, texts)  # recomputed over registry + LLM
        self.hubs0 = hubs0
        self.texts = texts

    def _hubs(self, ents, texts):
        if self.cut is None:
            return set()
        per_lang = Counter(l for _, l in texts.values())
        count = Counter(e for es in ents.values() for e in es)
        lang_of = {}
        for u, es in ents.items():
            for e in es:
                lang_of[e] = texts[u][1]
        return {e for e, n in count.items() if n / per_lang[lang_of[e]] > self.cut}

    def of_text(self, text: str, lang: str) -> set[str]:
        e = {x for x, _ in self.matcher.find(text, lang)}
        if self.fb:
            e |= self.fb.entities_for(text, lang, e - self.hubs0)
        return e


def jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="ai", choices=["ai", "human"])
    ap.add_argument("--no-stability", action="store_true")
    args = ap.parse_args()
    source = args.labels
    cfg = load_config(ROOT / "config.yaml")
    cut = cfg.layer2.hub_block_share
    thr = cfg.layer2.llm_fallback_max_entities
    documents = load_manual(ROOT / cfg.layer2.manual_file, sources=["documents"])
    client = LLMClient(cfg.llm, root=ROOT)
    # warm-up: loading the model into the GPU can take minutes on the first call;
    # it is not part of the per-block cost, so it is left out of the log
    client.extract_mentions("warm-up", use_cache=False)
    client.log.clear()
    fallbacks: list[LLMFallback] = []

    def make_fb(reg):
        fb = LLMFallback(reg, client, thr)
        fallbacks.append(fb)
        return fb

    merged = by_change(positives(source), include_historical=True)
    negatives = negatives_by_event(source)
    contexts = list(change_contexts(cfg))
    docs0 = parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, T0)

    t0 = time.time()
    with GpuPeak() as gpu:
        variants = {"A": {}, "B": {}}
        base = {"A": Variant(docs0, documents, cut), "B": Variant(docs0, documents, cut, make_fb)}
        results = {}
        for name in ("A", "B"):
            pairs, negs = [], []
            for ctx in contexts:
                sid = id(ctx["store"])
                if sid not in variants[name]:
                    variants[name][sid] = Variant(list(ctx["store"].values()), documents, cut,
                                                  make_fb if name == "B" else None)
                v = variants[name][sid]
                ch, lang = ctx["change"], ctx["lang"]
                a = v.of_text(ch["old_text"], lang) | v.of_text(ch["new_text"], lang)
                for p in merged.get(ctx["change_id"], []):
                    if p.kind in ("states", "depends") and p.block_uid in v.ents:
                        b = v.ents[p.block_uid]
                        group = "historical" if p.historical else p.kind
                        pairs.append((group, lang, bool((a & b) - v.hubs)))
                for uid in negatives.get(ch["event"], []):
                    if uid in v.ents:
                        negs.append((lang, bool((a & v.ents[uid]) - v.hubs)))
            results[name] = (pairs, negs)
        run_seconds = time.time() - t0
        n_first = len(client.log)
        # stability: the initial-corpus blocks the LLM saw, again without the cache
        stab = []
        if not args.no_stability:
            fb2 = LLMFallback(base["B"].reg, client, thr)
            m = base["B"].matcher
            for u, (t, l) in base["B"].texts.items():
                reg_e = {e for e, _ in m.find(t, l)} - base["B"].hubs0
                if fb2.needs_llm(len(reg_e)):
                    first = base["B"].ents[u] - {e for e, _ in m.find(t, l)}
                    second = fb2.entities_for(t, l, reg_e, use_cache=False)
                    stab.append((l, jaccard(first, second)))

    # first-pass cost and quality: one row per unique call in the cache (repeats of
    # the same text across stores are cache hits and not counted twice)
    rows = client.db.execute(
        "SELECT seconds, tokens_in, tokens_out, valid_first, thinking_chars FROM calls "
        "WHERE prompt=? AND model=?", (client.prompt_key, cfg.llm.model)).fetchall()
    stab_calls = client.log[n_first:]
    st = Counter()
    for fb in fallbacks:
        for k, val in vars(fb.stats).items():
            st[k] += val

    out = ["# M4 step 4: registry only (A) vs registry + local LLM fallback (B)", "",
           f"Model `{cfg.llm.model}` via {cfg.llm.runtime}, prompt `{client.prompt_key}`, "
           f"num_ctx {cfg.llm.num_ctx}, temperature {cfg.llm.temperature}, think "
           f"{cfg.llm.think}. Fallback on blocks with at most {thr} non-hub registry "
           f"entities. Hubs above {cut}, recomputed with LLM mentions. Offline: nothing "
           "written to Neo4j.", "",
           f"**Label source: {source}** ({DESCRIPTION[source]}). Most pairs come from "
           "synthetic edits written by the same AI reviewer that labelled them.", "",
           "## 1. Review pairs linked by a shared non-hub entity", "",
           "| variant | group | th | en | all |", "|---|---|---|---|---|"]
    for name in ("A", "B"):
        pairs, negs = results[name]
        for g in ("states", "depends", "states + depends", "historical"):
            members = ("states", "depends") if g == "states + depends" else (g,)
            cell = []
            for lang in ("th", "en", None):
                ps = [x for x in pairs if x[0] in members and (lang is None or x[1] == lang)]
                cell.append(f"{sum(x[2] for x in ps)}/{len(ps)}")
            out.append(f"| {name} | {g} | " + " | ".join(cell) + " |")
        cell = []
        for lang in ("th", "en", None):
            ns = [x for x in negs if lang is None or x[0] == lang]
            k = sum(x[1] for x in ns)
            cell.append(f"{k}/{len(ns)} ({k / len(ns):.0%})" if ns else "-")
        out.append(f"| {name} | negatives | " + " | ".join(cell) + " |")

    out += ["", "## 2. Initial corpus: body blocks still without any entity", "",
            "| variant | th | en |", "|---|---|---|"]
    for name in ("A", "B"):
        v = base[name]
        c = Counter(v.texts[u][1] for u, e in v.ents.items() if not (e - v.hubs))
        tot = Counter(l for _, l in v.texts.values())
        out.append(f"| {name} | {c['th']}/{tot['th']} | {c['en']}/{tot['en']} |")
    new_ents = {e for fb in fallbacks for e in fb.new_entities}
    out.append(f"\nHubs in B (initial corpus): "
               f"{len(base['B'].hubs)}; LLM-sourced entities over all stores: {len(new_ents)}.")

    out += ["", "## 3. Output quality", "",
            f"- LLM calls on blocks / change texts (with repeats across stores, cached "
            f"after the first): {st['blocks_called']}; failures after retries: "
            f"{st['failures']}.",
            f"- Unique texts sent to the model (first pass, from the cache): {len(rows)}; "
            f"JSON valid on the first attempt: {sum(r[3] for r in rows)}/{len(rows)}; replies "
            f"with thinking text: {sum(r[4] > 0 for r in rows)}. Stability calls: "
            f"{len(stab_calls)}, valid on the first attempt "
            f"{sum(c.valid_first for c in stab_calls)}, with thinking text "
            f"{sum(c.thinking_chars > 0 for c in stab_calls)}.",
            f"- Terms (counted over all {st['blocks_called']} calls, repeats included) "
            f"returned {st['returned']}: dropped as not in the block "
            f"{st['dropped']} ({st['dropped'] / max(st['returned'], 1):.0%}), type Other "
            f"{st['other']}, linked to a registry entity {st['linked_existing']}, new "
            f"LLM-sourced {st['new_terms']}."]
    out += ["", "## 4. Stability (second run, cache off)", ""]
    if stab:
        for lang in ("th", "en"):
            js = [j for l, j in stab if l == lang]
            if js:
                out.append(f"- {lang}: {len(js)} blocks, Jaccard of LLM entity sets mean "
                           f"{mean(js):.2f}, median {median(js):.2f}.")
    else:
        out.append("- not run (--no-stability).")
    secs = [r[0] for r in rows]
    out += ["", "## 5. Cost", "",
            f"- Seconds per unique call (first pass, as recorded when the call was made): "
            f"mean {mean(secs):.1f}, median {median(secs):.1f}; {len(rows)} calls, "
            f"{sum(secs) / 60:.0f} min in total." if secs else "- No calls recorded.",
            f"- Tokens per call: in {mean(r[1] for r in rows):.0f}, out "
            f"{mean(r[2] for r in rows):.0f}." if rows else "",
            f"- Stability rerun: {len(stab_calls)} calls, mean "
            f"{mean(c.seconds for c in stab_calls):.1f} s." if stab_calls else "",
            f"- This run's wall time for the first pass: {run_seconds:.0f} s (small when "
            "the answers come from the cache).",
            f"- GPU memory, whole card (display included, model already loaded by the "
            f"warm-up): {gpu.base} MiB at start, peak {gpu.peak} MiB of 6144. Before the model "
            "was loaded the card used about 1,340 MiB; `ollama ps` showed the model at "
            "3.1 GB, 100% GPU, context 2048."]
    hs = sheet("m4_mentions_sample", "human")
    n_h = answered(read_rows(hs), ["mentions"]) if hs.exists() else 0
    out += ["", "## 6. Mention precision / recall", "",
            "Not reported: the person's sheet `m4_mentions_sample_human.csv` has "
            f"{n_h} answered rows. No AI copy is made." if not n_h else
            "The person's sheet has answers: scoring is not implemented yet in this run."]
    out += ["", "Not checked: whether each kept LLM term is a correct entity (needs the "
            "person's MENTIONS sheet); Gemma 4 E4B (dropped: does not fit 6 GB)."]
    text = "\n".join(o for o in out if o != "")
    text = "\n".join(out)
    (ROOT / "eval" / "results" / f"m4_llm_fallback_{source}.md").write_text(text, encoding="utf-8")
    detail = {e.entity_id: {"name": e.name, "type": e.entity_type, "language": e.language}
              for fb in fallbacks for e in fb.new_entities.values()}
    (LABELS / "m4_llm_fallback_detail.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")
    client.close()
    print(text)


if __name__ == "__main__":
    main()
