"""Compare retrieval methods on our own labels (embedding model choice, M4/M5).

Methods
* char3   character-trigram TF-IDF (lexical, no model; the baseline's kind)
* e5      intfloat/multilingual-e5-large ("query: " / "passage: " prefixes)
* hybrid  Reciprocal Rank Fusion of char3 and e5 (brief step 12; k = 60)

Task A, impact retrieval (M5 change test set, real + synthetic events): for each
change item, rank every existing body block of the store at that time by its
similarity to the change (old + new text). Recall@k = share of the
(change, block) pairs the person marked needs_review that are in the top k.
Reported per passage kind (states / cites / depends) and per language.
BIAS: the labels were pooled from lexical methods and layer 1, never from an
embedding model, so blocks only an embedding finds were never judged and count
as misses here. Task A therefore favours char3; it is a lower bound for e5.

Task B, version matching (no labels needed): for every block the diff found
edited in the real uploads, rank all blocks of the new versions by similarity to
the old block; hit@1 and MRR of the true new block, per language. This checks
how well a method recognises the same passage after an edit, in Thai and English.

Vectors are cached in data/cache/ (not in git) by content hash and model.
Writes counts only to eval/results/embedding_comparison.md.

Run:  uv run --group embed python eval/compare_embeddings.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from make_change_test_set import EVENTS, LABELS, ROOT, Char3Index, store_after_events

from kg.config import load_config
from kg.diff import MatchStatus, diff_event
from kg.layer0_structure import Normalizer, parse_corpus

MODEL = "intfloat/multilingual-e5-large"
CACHE = ROOT / "data" / "cache"
KS = (5, 10, 20)
RRF_K = 60
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


class E5:
    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        t = time.time()
        self.model = SentenceTransformer(MODEL, device="cpu")
        self.load_seconds = time.time() - t
        self.encode_seconds = 0.0
        self.encoded = 0
        CACHE.mkdir(parents=True, exist_ok=True)
        self.path = CACHE / f"{MODEL.replace('/', '__')}.json"
        self.cache = json.loads(self.path.read_text()) if self.path.exists() else {}

    def embed(self, texts: list[str], kind: str) -> np.ndarray:
        prefixed = [f"{kind}: {t}" for t in texts]
        keys = [hashlib.sha256(p.encode()).hexdigest() for p in prefixed]
        todo = [(k, p) for k, p in zip(keys, prefixed) if k not in self.cache]
        if todo:
            t = time.time()
            vecs = self.model.encode([p for _, p in todo], batch_size=16,
                                     normalize_embeddings=True, show_progress_bar=True)
            self.encode_seconds += time.time() - t
            self.encoded += len(todo)
            for (k, _), v in zip(todo, vecs):
                self.cache[k] = [round(float(x), 6) for x in v]
            self.path.write_text(json.dumps(self.cache))
        return np.array([self.cache[k] for k in keys])


def rrf(*rankings: list[str]) -> list[str]:
    score: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for r, key in enumerate(ranking, start=1):
            score[key] += 1.0 / (RRF_K + r)
    return sorted(score, key=lambda k: (-score[k], k))


def rankings(query: str, cands: dict[str, str], e5: E5) -> dict[str, list[str]]:
    keys = sorted(cands)
    char3 = Char3Index({k: cands[k] for k in keys}).top(query, len(keys), exclude=set())
    char3 += [k for k in keys if k not in set(char3)]  # zero-score blocks last
    q = e5.embed([query], "query")[0]
    p = e5.embed([cands[k] for k in keys], "passage")
    order = np.argsort(-(p @ q), kind="stable")
    e5_rank = [keys[i] for i in order]
    return {"char3": char3, "e5": e5_rank, "hybrid": rrf(char3, e5_rank)}


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


SETS = [("real", "m5"), ("synthetic", "m5s")]


def change_contexts(cfg):
    """For every change item of the M5 change test set (real and synthetic): the
    existing body blocks it was judged against (block_uid -> text) and the
    language of the changed document. Same candidate sets as the pooled sheets."""
    norm = Normalizer(cfg.layer0)
    for set_name, prefix in SETS:
        key = json.loads((LABELS / f"{prefix}_key.json").read_text(encoding="utf-8"))
        changes = read(LABELS / f"{prefix}_changes.csv")
        if set_name == "real":
            stores, store = {}, {d.document.doc_key: d for d in parse_corpus(
                ROOT / "data" / "initial_corpus", cfg.layer0, T0)}
            for ev in EVENTS:
                uploaded = parse_corpus(ROOT / "data" / "uploads" / ev, cfg.layer0, T0)
                changed = {m.old.block.block_uid for d in diff_event(store, uploaded, cfg.diff, norm)
                           for m in d.matches if m.old and m.status != MatchStatus.UNCHANGED}
                stores[ev] = ({pb.block.block_uid: pb.block.text for d in store.values()
                               for pb in d.blocks if pb.block.role.value == "body"
                               and pb.block.block_uid not in changed}, dict(store))
                for d in uploaded:
                    store[d.document.doc_key] = d
        else:
            base = store_after_events(cfg)
        for ch in changes:
            cid = ch["change_id"]
            if set_name == "real":
                cands, st = stores[ch["event"]]
            else:
                old_uid = key["changes"][cid]["old_block_uid"]
                st = base
                cands = {pb.block.block_uid: pb.block.text for d in base.values()
                         for pb in d.blocks if pb.block.role.value == "body"
                         and pb.block.block_uid != old_uid}
            yield {"set": set_name, "prefix": prefix, "change_id": cid, "change": ch,
                   "cands": cands, "store": st,
                   "lang": st[ch["document"]].document.language.value}


def positives_of(prefix: str) -> dict[str, list[tuple[str, str]]]:
    key = json.loads((LABELS / f"{prefix}_key.json").read_text(encoding="utf-8"))
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in read(LABELS / f"{prefix}_candidates.csv"):
        if r["needs_review"].strip().lower() != "yes":
            continue
        for cid in [x.strip() for x in r["change_ids"].split(";") if x.strip()]:
            out[cid].append((key["candidates"][r["row_id"]]["block_uid"],
                             r["kind"].strip().lower()))
    return out


def task_a(cfg, e5: E5) -> dict:
    """(change, positive block) pairs found in the top k, per method / kind / language."""
    hits: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    positives = {prefix: positives_of(prefix) for _, prefix in SETS}
    for ctx in change_contexts(cfg):
        pos = positives[ctx["prefix"]].get(ctx["change_id"])
        if not pos:
            continue
        ch = ctx["change"]
        ranks = rankings(ch["old_text"] + "\n" + ch["new_text"], ctx["cands"], e5)
        for method, ranking in ranks.items():
            where = {u: i for i, u in enumerate(ranking, start=1)}
            for uid, kind in pos:
                r = where.get(uid, 10**9)
                for group in (("all",), (ctx["set"],), ("kind", kind), ("lang", ctx["lang"])):
                    c = hits[(method, group)]
                    c["pairs"] += 1
                    for k in KS:
                        c[f"@{k}"] += r <= k
    return hits


def task_b(cfg, e5: E5) -> dict:
    norm = Normalizer(cfg.layer0)
    out: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    store = {d.document.doc_key: d for d in parse_corpus(ROOT / "data" / "initial_corpus",
                                                         cfg.layer0, T0)}
    for ev in EVENTS:
        uploaded = parse_corpus(ROOT / "data" / "uploads" / ev, cfg.layer0, T0)
        new_blocks = {pb.block.block_uid: pb.block.text for d in uploaded for pb in d.blocks
                      if pb.block.role.value == "body"}
        for d in diff_event(store, uploaded, cfg.diff, norm):
            for m in d.matches:
                if m.status != MatchStatus.EDITED or m.old.block.role.value != "body":
                    continue
                lang = d.new.document.language.value
                ranks = rankings(m.old.block.text, new_blocks, e5)
                for method, ranking in ranks.items():
                    r = ranking.index(m.new.block.block_uid) + 1
                    c = out[(method, lang)]
                    c["pairs"] += 1
                    c["hit1"] += r == 1
                    c["rr"] += 1.0 / r
        for d in uploaded:
            store[d.document.doc_key] = d
    return out


def main() -> None:
    cfg = load_config(ROOT / "config.yaml")
    e5 = E5()
    a = task_a(cfg, e5)
    b = task_b(cfg, e5)
    out = ["# Embedding comparison (multilingual-e5-large vs char-trigram TF-IDF)", "",
           f"Model load {e5.load_seconds:.0f} s; encoded {e5.encoded} new texts in "
           f"{e5.encode_seconds:.0f} s on CPU (cached texts not counted).", "",
           "## Task A: impact retrieval on the M5 change test set (needs_review)", "",
           "Labels were pooled without any embedding method: blocks only e5 finds were "
           "never judged, so this table favours char3 (a lower bound for e5).", "",
           "| group | pairs | " + " | ".join(f"{m} @{k}" for m in ("char3", "e5", "hybrid")
                                            for k in KS) + " |",
           "|---|---|" + "---|" * (3 * len(KS))]
    groups = sorted({g for _, g in a}, key=lambda g: (len(g), g))
    for g in groups:
        pairs = a[("char3", g)]["pairs"]
        cells = [f"{a[(m, g)][f'@{k}'] / pairs:.2f}" for m in ("char3", "e5", "hybrid") for k in KS]
        out.append(f"| {' '.join(g)} | {pairs} | " + " | ".join(cells) + " |")
    out += ["", "## Task B: finding the same passage after an edit (real uploads)", "",
            "| language | pairs | char3 hit@1 | char3 MRR | e5 hit@1 | e5 MRR | hybrid hit@1 | hybrid MRR |",
            "|---|---|---|---|---|---|---|---|"]
    for lang in sorted({l for _, l in b}):
        n = b[("char3", lang)]["pairs"]
        cells = []
        for m in ("char3", "e5", "hybrid"):
            c = b[(m, lang)]
            cells += [f"{c['hit1'] / n:.2f}", f"{c['rr'] / n:.2f}"]
        out.append(f"| {lang} | {int(n)} | " + " | ".join(cells) + " |")
    text = "\n".join(out)
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / "embedding_comparison.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
