"""Build a *blind* review set for the diff (review point 4).

The person sees an old block and the list of blocks in the uploaded files, and
decides where the old block went. They never see the diff's status, its
pairing or any similarity score, so their answer cannot lean on the system's.

Sampling (fixed seed, recorded in the key file):
* Only old blocks with role "body" (footnote entries are matched by exact text
  by rule, so there is nothing to judge).
* Per upload event, PER_EVENT blocks: half whose exact text still appears
  somewhere in that event's uploaded files, half whose text does not. This split
  uses only the text, not the diff's judgement, and keeps the sample from being
  mostly trivial. Results are reported per half (stratum).

Files written to data/labels/ (not in git: they contain document text):
* m2_blind_sample.csv       – one row per sampled old block. Fill in:
    answer    : same | edited | removed
                same    = this text appears again with no change of meaning
                          (wording identical apart from formatting)
                edited  = a revised version of this text is in the new files
                          (in the same section, another section, or another file)
                removed = nothing in the new files corresponds to it
    new_refs  : the ref(s) of the new block(s) from m2_blind_new_blocks.csv,
                separated by ";" (more than one if it was split or merged).
                Empty for "removed".
    note      : optional.
* m2_blind_new_blocks.csv   – every block of the uploaded files, in document
                              order, with a short ref (e.g. e1-N007).
* m2_blind_key.json         – which block each row and ref stands for, the seed
                              and the strata. Not needed while answering.

Run:  uv run python eval/make_blind_sheet.py
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from kg.config import load_config
from kg.layer0_structure import parse_corpus
from kg.models import BlockRole
from label_sources import refuse_overwrite

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels"
SAMPLE = LABELS / "m2_blind_sample.csv"
CATALOGUE = LABELS / "m2_blind_new_blocks.csv"
KEY = LABELS / "m2_blind_key.json"
EVENTS = ("event1", "event2", "event3")
SEED = 20261125
PER_EVENT = 10
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)

SAMPLE_COLUMNS = ["row_id", "event", "old_file", "old_lines", "old_section", "old_text",
                  "answer", "new_refs", "note"]
CATALOGUE_COLUMNS = ["ref", "event", "new_file", "new_lines", "new_section", "new_text"]


def section_of(block_id: str) -> str:
    return block_id.split("::")[1]


def pick(rng: random.Random, same: list, other: list, k: int) -> list[tuple[str, object]]:
    """k blocks, half from each stratum; a short stratum is topped up from the other."""
    k_other = min(len(other), k - k // 2)
    k_same = min(len(same), k - k_other)
    k_other = min(len(other), k - k_same)
    return ([("text_still_present", b) for b in rng.sample(same, k_same)]
            + [("text_not_present", b) for b in rng.sample(other, k_other)])


def main() -> None:
    refuse_overwrite([SAMPLE, CATALOGUE, KEY])
    cfg = load_config(ROOT / "config.yaml")
    olds = {d.document.doc_key: d
            for d in parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, T0)}

    sample_rows, catalogue_rows = [], []
    key: dict = {"seed": SEED, "per_event": PER_EVENT, "rows": {}, "refs": {},
                 "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for ev in EVENTS:
        uploaded = parse_corpus(ROOT / "data" / "uploads" / ev, cfg.layer0, T0)
        new_hashes = {pb.block.content_hash for d in uploaded for pb in d.blocks}
        old_blocks = [(olds[d.document.doc_key], pb) for d in uploaded
                      if d.document.doc_key in olds
                      for pb in olds[d.document.doc_key].blocks
                      if pb.block.role == BlockRole.BODY]
        same = [x for x in old_blocks if x[1].block.content_hash in new_hashes]
        other = [x for x in old_blocks if x[1].block.content_hash not in new_hashes]
        rng = random.Random(f"{SEED}-{ev}")
        chosen = pick(rng, same, other, PER_EVENT)
        rng.shuffle(chosen)  # so the strata are not in blocks of rows
        for i, (stratum, (doc, pb)) in enumerate(chosen, start=1):
            b = pb.block
            row_id = f"{ev}-S{i:02d}"
            sample_rows.append({
                "row_id": row_id, "event": ev, "old_file": doc.version.source_file,
                "old_lines": f"{b.lines.start}-{b.lines.end}", "old_section": section_of(b.block_id),
                "old_text": b.text, "answer": "", "new_refs": "", "note": ""})
            key["rows"][row_id] = {"doc_key": b.doc_key, "old_block_uid": b.block_uid,
                                   "old_block_id": b.block_id, "stratum": stratum}
        n = 0
        for d in uploaded:
            for pb in d.blocks:
                n += 1
                b = pb.block
                ref = f"{ev[0]}{ev[-1]}-N{n:03d}"
                catalogue_rows.append({
                    "ref": ref, "event": ev, "new_file": d.version.source_file,
                    "new_lines": f"{b.lines.start}-{b.lines.end}",
                    "new_section": section_of(b.block_id), "new_text": b.text})
                key["refs"][ref] = {"doc_key": b.doc_key, "new_block_id": b.block_id}

    LABELS.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel shows Thai text correctly
    for path, cols, rows in ((SAMPLE, SAMPLE_COLUMNS, sample_rows),
                             (CATALOGUE, CATALOGUE_COLUMNS, catalogue_rows)):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    KEY.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    strata = {}
    for r in key["rows"].values():
        strata[r["stratum"]] = strata.get(r["stratum"], 0) + 1
    print(f"{len(sample_rows)} sampled old blocks {strata}; "
          f"{len(catalogue_rows)} new blocks in the catalogue")


if __name__ == "__main__":
    main()
