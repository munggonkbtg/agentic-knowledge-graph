"""Add multilingual-e5-large's top results to the M5 change test set pool.

The first pool (char3, cite, graph, random) had no embedding method, so blocks
only an embedding finds were never judged, and the comparison favoured the
lexical method (20 of 41 positives came from char3's own top 3). Standard
pooling fixes this: take the top K of the missing method for every change item,
and have a person judge the blocks not judged before, blind.

Both methods are pooled to the same depth K: e5's top K, and char3 extended from
its first depth of 3 to K, so neither is judged deeper than the other.

For each change (real C01-C40 and synthetic XS01-XS15): e5's top K over the same
candidate blocks the first sheets used; blocks already in m5_candidates.csv /
m5s_candidates.csv for that event are skipped; the rest is shuffled per event.

Files written to data/labels/ (not in git):
* m5e_candidates.csv  same columns as m5_candidates.csv; fill needs_revision,
                      needs_review, kind, change_ids (C-ids or XS-ids of that event)
* m5e_key.json        which block each row is, the K used, the e5 rank per change

Run:  uv run --group embed python eval/make_e5_pool.py --dry-run   (sizes for K = 3, 5, 10)
      uv run --group embed python eval/make_e5_pool.py --k 5
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from datetime import datetime, timezone

from compare_embeddings import E5, LABELS, ROOT, change_contexts, read
from make_change_test_set import Char3Index

from kg.config import load_config

SEED = 20261129
COLUMNS = ["row_id", "event", "file", "lines", "section", "block_text",
           "needs_revision", "needs_review", "kind", "change_ids", "note"]


def judged_by_event() -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for prefix in ("m5", "m5s"):
        key = json.loads((LABELS / f"{prefix}_key.json").read_text(encoding="utf-8"))
        for r in read(LABELS / f"{prefix}_candidates.csv"):
            out[r["event"]].add(key["candidates"][r["row_id"]]["block_uid"])
    return out


def e5_top(ctx: dict, e5: E5, k: int) -> list[str]:
    import numpy as np

    ch = ctx["change"]
    keys = sorted(ctx["cands"])
    q = e5.embed([ch["old_text"] + "\n" + ch["new_text"]], "query")[0]
    p = e5.embed([ctx["cands"][u] for u in keys], "passage")
    order = np.argsort(-(p @ q), kind="stable")[:k]
    return [keys[i] for i in order]


def char3_top(ctx: dict, k: int) -> list[str]:
    ch = ctx["change"]
    return Char3Index(ctx["cands"]).top(ch["old_text"] + "\n" + ch["new_text"], k, exclude=set())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sheet, key_path = LABELS / "m5e_candidates.csv", LABELS / "m5e_key.json"
    if not args.dry_run:
        for p in (sheet, key_path):
            if p.exists():
                raise SystemExit(f"{p} exists (it may hold labels); not overwriting")
    cfg = load_config(ROOT / "config.yaml")
    e5 = E5()
    judged = judged_by_event()
    contexts = list(change_contexts(cfg))
    ranked = {c["change_id"]: e5_top(c, e5, 10) for c in contexts}
    # char3 was pooled only to depth 3 the first time; extend it to the same depth
    # as e5, so neither method is judged deeper than the other.
    lexical = {c["change_id"]: char3_top(c, 10) for c in contexts}

    if args.dry_run:
        for k in (3, 5, 10):
            new = defaultdict(set)
            for c in contexts:
                ev = c["change"]["event"]
                top = set(ranked[c["change_id"]][:k]) | set(lexical[c["change_id"]][:k])
                new[ev] |= {u for u in top if u not in judged[ev]}
            print(f"K={k:2d}: {sum(len(v) for v in new.values())} new blocks to judge")
        return

    rng = random.Random(SEED)
    new: dict[str, dict[str, dict]] = defaultdict(dict)  # event -> uid -> info
    for c in contexts:
        ev = c["change"]["event"]
        for method, ranking in (("e5", ranked), ("char3", lexical)):
            for rank, u in enumerate(ranking[c["change_id"]][: args.k], start=1):
                if u in judged[ev]:
                    continue
                info = new[ev].setdefault(u, {"store": c["store"], "ranks": {}})
                info["ranks"].setdefault(method, {})[c["change_id"]] = rank
    rows, key = [], {"seed": SEED, "k": args.k, "model": "intfloat/multilingual-e5-large",
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "candidates": {}}
    order = sorted(new, key=lambda e: (not e.startswith("event"), e))
    for ev in order:
        uids = sorted(new[ev])
        rng.shuffle(uids)
        for i, u in enumerate(uids, start=1):
            store = new[ev][u]["store"]
            doc, pb = next((d, p) for d in store.values() for p in d.blocks
                           if p.block.block_uid == u)
            rid = f"{ev}-E{i:02d}"
            rows.append({"row_id": rid, "event": ev, "file": doc.version.source_file,
                         "lines": f"{pb.block.lines.start}-{pb.block.lines.end}",
                         "section": pb.block.block_id.split("::")[1], "block_text": pb.block.text,
                         "needs_revision": "", "needs_review": "", "kind": "",
                         "change_ids": "", "note": ""})
            key["candidates"][rid] = {"block_uid": u, "block_id": pb.block.block_id,
                                      "doc_key": pb.block.doc_key,
                                      "sources": sorted(new[ev][u]["ranks"]),
                                      "ranks": new[ev][u]["ranks"]}
    with sheet.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"K={args.k}: {len(rows)} new blocks to judge in {sheet.name}")


if __name__ == "__main__":
    main()
