"""Synthetic change events for M5, written by a person (option 2, 2026-11-25).

The real pilot uploads gave only one block that truly needs revision, so recall
per passage kind cannot be measured on them. Here a PERSON (not the pipeline,
not an AI) picks a fact in the store that other passages repeat, cite or rely on,
and writes a changed version of the block that states it. Each edit is its own
upload event against the store after all real events. Results from these
events are reported apart from the real ones.

Step 1, template:   uv run python eval/make_synthetic_events.py --template
  writes data/labels/m5s_store_blocks.csv (every body block, ref x-S…) and
  data/labels/m5s_edits.csv. Fill one row per edit:
    store_ref    the block to change (ref from m5s_store_blocks.csv)
    new_text     the whole new text of that block (copy the old text, change the fact)
    what_changed one line, e.g. "severance for 10+ years: 300 -> 400 days"
    note         optional
  Aim for edits whose fact other passages state, cite, or depend on, so that
  all three kinds appear. Leave unused rows empty.

Step 2, build:      uv run python eval/make_synthetic_events.py --build
  for each edit: writes the changed document to data/uploads_synthetic/<edit>/,
  checks that the diff finds exactly that one edited block, and pools candidates
  the same way as the real events (char3, cite, graph, 5 random per edit).
  Writes m5s_changes.csv, m5s_candidates.csv (same columns as m5_candidates.csv,
  including needs_review) and m5s_key.json. Label it like m5_candidates.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from make_change_test_set import (  # same pooling as the real events
    LABELS,
    ROOT,
    T0,
    pool_candidates,
    store_after_events,
)

from kg.config import load_config
from kg.diff import MatchStatus, diff_versions
from kg.layer0_structure import Normalizer, parse_file
from label_sources import refuse_overwrite

SEED = 20261128
RANDOM_PER_EDIT = 5
TEMPLATE_ROWS = 15
EDIT_COLUMNS = ["edit_id", "store_ref", "new_text", "what_changed", "note"]
CANDIDATE_COLUMNS = ["row_id", "event", "file", "lines", "section", "block_text",
                     "needs_revision", "needs_review", "kind", "change_ids", "note"]
OUT_DIR = ROOT / "data" / "uploads_synthetic"


def source_path(doc) -> Path:
    for folder in [ROOT / "data" / "initial_corpus", *sorted((ROOT / "data" / "uploads").glob("*"))]:
        p = folder / doc.version.source_file
        if p.exists() and parse_file(p, load_config(ROOT / "config.yaml").layer0, T0)\
                .version.file_hash == doc.version.file_hash:
            return p
    raise FileNotFoundError(doc.version.source_file)


def apply_edit(original: Path, start: int, end: int, new_text: str, dest: Path) -> None:
    """Copy ``original`` to ``dest`` with lines start..end (1-based, inclusive)
    replaced by ``new_text``."""
    lines = original.read_text(encoding="utf-8").splitlines()
    out = lines[: start - 1] + new_text.strip("\n").splitlines() + lines[end:]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def template() -> None:
    edits, catalogue = LABELS / "m5s_edits.csv", LABELS / "m5s_store_blocks.csv"
    refuse_overwrite([edits, catalogue])
    cfg = load_config(ROOT / "config.yaml")
    store = store_after_events(cfg)
    rows, refs = [], {}
    blocks = sorted(((d, pb) for d in store.values() for pb in d.blocks
                     if pb.block.role.value == "body"),
                    key=lambda x: (x[1].block.doc_key, x[1].block.lines.start))
    for i, (d, pb) in enumerate(blocks, start=1):
        ref = f"x-S{i:03d}"
        rows.append({"ref": ref, "file": d.version.source_file,
                     "lines": f"{pb.block.lines.start}-{pb.block.lines.end}",
                     "section": pb.block.block_id.split("::")[1], "block_text": pb.block.text})
        refs[ref] = pb.block.block_uid
    LABELS.mkdir(parents=True, exist_ok=True)
    write_csv(catalogue, rows, ["ref", "file", "lines", "section", "block_text"])
    write_csv(edits, [{"edit_id": f"S{i:02d}", "store_ref": "", "new_text": "",
                       "what_changed": "", "note": ""} for i in range(1, TEMPLATE_ROWS + 1)],
              EDIT_COLUMNS)
    (LABELS / "m5s_store_refs.json").write_text(json.dumps(refs, indent=1), encoding="utf-8")
    print(f"{len(rows)} blocks in {catalogue.name}; fill {edits.name}")


def build() -> None:
    outputs = [LABELS / n for n in ("m5s_changes.csv", "m5s_candidates.csv", "m5s_key.json")]
    refuse_overwrite(outputs)
    cfg = load_config(ROOT / "config.yaml")
    norm = Normalizer(cfg.layer0)
    rng = random.Random(SEED)
    refs = json.loads((LABELS / "m5s_store_refs.json").read_text(encoding="utf-8"))
    with (LABELS / "m5s_edits.csv").open(encoding="utf-8-sig", newline="") as f:
        edits = [r for r in csv.DictReader(f) if r["store_ref"].strip() and r["new_text"].strip()]
    if not edits:
        raise SystemExit("no filled rows in m5s_edits.csv")
    store = store_after_events(cfg)
    by_uid = {pb.block.block_uid: (d, pb) for d in store.values() for pb in d.blocks}

    changes, cands_rows = [], []
    key: dict = {"seed": SEED, "base": "store after events 1-3",
                 "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "note": "synthetic edits written by a person; report apart from real events; "
                         "pool sources include 'graph' (layer 1)",
                 "changes": {}, "candidates": {}}
    for e in edits:
        eid = e["edit_id"].strip()
        uid = refs.get(e["store_ref"].strip())
        if uid is None:
            raise SystemExit(f"{eid}: unknown store_ref {e['store_ref']}")
        doc, pb = by_uid[uid]
        dest = OUT_DIR / eid / doc.version.source_file
        apply_edit(source_path(doc), pb.block.lines.start, pb.block.lines.end,
                   e["new_text"], dest)
        new_doc = parse_file(dest, cfg.layer0, T0)
        diff = [m for m in diff_versions(doc, new_doc, cfg.diff, norm)
                if m.status != MatchStatus.UNCHANGED]
        if len(diff) != 1 or diff[0].status != MatchStatus.EDITED or \
                diff[0].old.block.block_uid != uid:
            raise SystemExit(f"{eid}: the diff should find exactly this one edited block, "
                             f"found {[(m.status.value, m.similarity) for m in diff]} "
                             "(check new_text: same block, changed fact)")
        m = diff[0]
        cid = f"X{eid}"
        changes.append({"change_id": cid, "event": eid, "document": pb.block.doc_key,
                        "change": "edited", "section": pb.block.block_id.split("::")[1],
                        "old_text": pb.block.text, "new_text": m.new.block.text,
                        "what_changed": e["what_changed"]})
        key["changes"][cid] = {"event": eid, "old_block_uid": uid,
                               "new_block_id": m.new.block.block_id,
                               "file": (str(dest.relative_to(ROOT))
                                        if dest.is_relative_to(ROOT) else str(dest))}
        cands, sources = pool_candidates(store, {uid}, [m], cfg, rng, RANDOM_PER_EDIT)
        pooled = sorted(sources)
        rng.shuffle(pooled)
        for i, u in enumerate(pooled, start=1):
            cdoc, cpb = cands[u]
            rid = f"{eid}-B{i:02d}"
            cands_rows.append({"row_id": rid, "event": eid, "file": cdoc.version.source_file,
                               "lines": f"{cpb.block.lines.start}-{cpb.block.lines.end}",
                               "section": cpb.block.block_id.split("::")[1],
                               "block_text": cpb.block.text, "needs_revision": "",
                               "needs_review": "", "kind": "", "change_ids": "", "note": ""})
            key["candidates"][rid] = {"block_uid": u, "block_id": cpb.block.block_id,
                                      "doc_key": cpb.block.doc_key, "sources": sorted(sources[u])}
        print(f"{eid}: {pb.block.doc_key} similarity {m.similarity:.2f}, "
              f"{len(pooled)} candidates")
    write_csv(LABELS / "m5s_changes.csv", changes,
              ["change_id", "event", "document", "change", "section", "old_text", "new_text",
               "what_changed"])
    write_csv(LABELS / "m5s_candidates.csv", cands_rows, CANDIDATE_COLUMNS)
    (LABELS / "m5s_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"{len(changes)} synthetic edits, {len(cands_rows)} candidates to judge")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--template", action="store_true")
    g.add_argument("--build", action="store_true")
    args = ap.parse_args()
    template() if args.template else build()


if __name__ == "__main__":
    main()
