"""M5 step 3: the LLM check (workflow step 13), measured offline.

For each labelled change item, the graph-first ranking of step 1 gives the top
`impact.check_top_n` candidates; the local model (config `llm`, prompt
`check_prompt_file`) answers needs_update / not_affected / unsure with a reason
and evidence quoted from the candidate. Nothing is written to Neo4j.

Each checked candidate is one of: a labelled positive (needs_review yes, main),
historical positive, judged negative (needs_review no) or unjudged (never
labelled). Reported, against the labels named by --labels:
* verdicts per class;
* recall after the check: positives kept (needs_update or unsure) over all
  positives of these changes, next to recall@N before the check;
* the same for needs_revision pairs, and needs_update alone;
* kept list size per change, and the share of kept candidates that are
  labelled positive among the judged ones;
* evidence quoted from the candidate: found in it or not;
* JSON validity, seconds and tokens per call.

Run:  uv run --group embed python eval/m5_check_experiment.py
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from statistics import mean, median

from compare_embeddings import E5, change_contexts, rankings
from label_sources import DESCRIPTION
from m4_registry_coverage import negatives_by_event
from m5_labels import by_change, positives
from make_change_test_set import LABELS, ROOT

from kg.config import load_config
from kg.impact import ChangeItem, GraphView, evidence_in, graph_first, graph_signals
from kg.layer2_entities import load_manual
from kg.llm import LLMClient

KEEP = ("needs_update", "unsure")


def found_in(evidence: str, text: str) -> bool:
    return evidence_in(evidence, text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="ai", choices=["ai", "human"])
    source = ap.parse_args().labels
    cfg = load_config(ROOT / "config.yaml")
    n_top = cfg.impact.check_top_n
    documents = load_manual(ROOT / cfg.layer2.manual_file, sources=["documents"])
    client = LLMClient.for_check(cfg.llm, root=ROOT)
    client.check_impact("warm-up", "warm-up", "warm-up", "warm-up", use_cache=False)
    client.log.clear()
    e5 = E5()
    merged = by_change(positives(source), include_historical=True)
    negatives = {ev: set(u) for ev, u in negatives_by_event(source).items()}
    views: dict[int, GraphView] = {}
    rows, per_change = [], []
    t0 = time.time()
    for ctx in change_contexts(cfg):
        pos = merged.get(ctx["change_id"])
        if not pos:
            continue
        sid = id(ctx["store"])
        if sid not in views:
            views[sid] = GraphView(list(ctx["store"].values()), cfg.layer1,
                                   cfg.layer2.hub_block_share, documents)
        ch = ctx["change"]
        item = ChangeItem(ctx["change_id"], ch["document"], ch["section"], ch["old_text"],
                          ch["new_text"], ctx["lang"])
        cands = ctx["cands"]
        hybrid = rankings(ch["old_text"] + "\n" + ch["new_text"], cands, e5)["hybrid"]
        order = graph_first(graph_signals(views[sid], item, set(cands)), hybrid)[:n_top]
        label = {p.block_uid: p for p in pos}
        kept = 0
        for u in order:
            p = label.get(u)
            cls = ("historical" if p and p.historical else "positive" if p
                   else "negative" if u in negatives.get(ch["event"], set()) else "unjudged")
            res = client.check_impact(ch["old_text"], ch["new_text"], cands[u],
                                      f"{ch['document']} > {ch['section']}")
            v = res.data
            verdict = v.verdict if v else "failed"
            kept += verdict in KEEP
            rows.append({"change": ctx["change_id"], "uid": u, "class": cls,
                         "revision": p.needs_revision if p else "", "kind": p.kind if p else "",
                         "verdict": verdict, "evidence_found":
                         bool(v and v.evidence and found_in(v.evidence, cands[u])),
                         "evidence_empty": bool(v and not v.evidence.strip()),
                         "reason": v.reason if v else ""})
        main_pos = [p for p in pos if not p.historical and p.block_uid in cands]
        per_change.append({"change": ctx["change_id"], "kept": kept,
                           "positives": len(main_pos),
                           "in_top": sum(p.block_uid in order for p in main_pos)})
    wall = time.time() - t0

    by_cls = defaultdict(Counter)
    for r in rows:
        by_cls[r["class"]][r["verdict"]] += 1
    n_pos = sum(c["positives"] for c in per_change)
    in_top = sum(c["in_top"] for c in per_change)
    kept_pos = sum(r["verdict"] in KEEP for r in rows if r["class"] == "positive")
    upd_pos = sum(r["verdict"] == "needs_update" for r in rows if r["class"] == "positive")
    rev_rows = [r for r in rows if r["class"] == "positive" and r["revision"] in ("yes", "unsure")]
    n_rev = sum(1 for c in merged.values() for p in c
                if not p.historical and p.needs_revision in ("yes", "unsure"))
    kept_judged = [r for r in rows if r["verdict"] in KEEP and r["class"] in ("positive", "negative")]
    calls = [c for c in client.log if not c.cached]
    kept_rows = [r for r in rows if r["verdict"] in KEEP]

    out = ["# M5 step 3: LLM check of the top candidates (offline)", "",
           f"Model `{cfg.llm.model}` (local, Ollama), prompt `{client.prompt_key}`, num_ctx "
           f"{cfg.llm.check_num_ctx}, temperature {cfg.llm.temperature}, think {cfg.llm.think}. "
           f"Top {n_top} candidates per change from the graph-first ranking (step 1). Nothing "
           "written to Neo4j.", "",
           f"**Label source: {source}** ({DESCRIPTION[source]}). Most pairs come from "
           "synthetic edits written by the same AI reviewer. 'unjudged' candidates were never "
           "labelled, so their verdicts cannot be scored.", "",
           "## Verdicts by label class", "",
           "| class | checked | needs_update | unsure | not_affected | failed |",
           "|---|---|---|---|---|---|"]
    for cls in ("positive", "negative", "historical", "unjudged"):
        c = by_cls[cls]
        out.append(f"| {cls} | {sum(c.values())} | {c['needs_update']} | {c['unsure']} "
                   f"| {c['not_affected']} | {c['failed']} |")
    out += ["", "## Effect on the list", "",
            f"- Main needs_review pairs of these {len(per_change)} changes: {n_pos}; in the top "
            f"{n_top} before the check: {in_top} ({in_top / n_pos:.2f}); kept by the check "
            f"(needs_update or unsure): {kept_pos} ({kept_pos / n_pos:.2f}); marked "
            f"needs_update: {upd_pos} ({upd_pos / n_pos:.2f}).",
            f"- needs_revision (yes / unsure) pairs: {n_rev}; checked {len(rev_rows)}, kept "
            f"{sum(r['verdict'] in KEEP for r in rev_rows)}, needs_update "
            f"{sum(r['verdict'] == 'needs_update' for r in rev_rows)}.",
            f"- Kept per change: mean {mean(c['kept'] for c in per_change):.1f}, median "
            f"{median(c['kept'] for c in per_change):g} of {n_top}.",
            f"- Among kept candidates that were judged: "
            f"{sum(r['class'] == 'positive' for r in kept_judged)}/{len(kept_judged)} are "
            "labelled positive (judged negatives kept: "
            f"{sum(r['class'] == 'negative' for r in kept_judged)}).",
            f"- Evidence of kept candidates: found in the candidate "
            f"{sum(r['evidence_found'] for r in kept_rows)}/{len(kept_rows)}, empty "
            f"{sum(r['evidence_empty'] for r in kept_rows)}.",
            "", "## Cost", "",
            f"- {len(rows)} checks, {len(calls)} uncached calls in {wall / 60:.0f} min; JSON valid "
            f"on the first attempt {sum(c.valid_first for c in calls)}/{len(calls)}; failures "
            f"{by_cls_total(by_cls, 'failed')}; thinking text in "
            f"{sum(c.thinking_chars > 0 for c in calls)} replies.",
            f"- Per call: {mean(c.seconds for c in calls):.1f} s, tokens in "
            f"{mean(c.tokens_in for c in calls):.0f}, out {mean(c.tokens_out for c in calls):.0f}."
            if calls else "- All checks came from the cache.",
            f"- Tokens per change (in + out): "
            f"{sum(c.tokens_in + c.tokens_out for c in calls) / max(len(per_change), 1):.0f}."
            if calls else "",
            "", "Not checked: verdicts on unjudged candidates; any human label; the check on "
            "the 116 changes of events 1-3 in the graph."]
    text = "\n".join(out)
    (ROOT / "eval" / "results" / f"m5_check_{source}.md").write_text(text, encoding="utf-8")
    (LABELS / f"m5_check_detail_{source}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    client.close()
    print(text)


def by_cls_total(by_cls, verdict: str) -> int:
    return sum(c[verdict] for c in by_cls.values())


if __name__ == "__main__":
    main()
