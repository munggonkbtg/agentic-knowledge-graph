"""A blind sheet for *known* test cases the random sample missed.

The brief names cases each upload event must test (event 2: the severance
paragraph moves out of E3 into the new E2). When the random blind sample does
not contain them, they are checked here, in the same blind format, and
reported separately: a hand-picked case says whether that case works, not how
often the diff is right.

The person sees only the old blocks and uses the same catalogue of new blocks
as the random sheet (data/labels/m2_blind_new_blocks.csv, same refs), and fills
`answer` (same / edited / removed) and `new_refs` exactly as there.

Default cases: both blocks of E3's "Performance Improvement Plans" section in
the previous version (the severance paragraph and the paragraph before it), so
the sheet does not reveal which one moved.

Run:   uv run python eval/make_known_cases_sheet.py
Score: uv run python eval/blind_agreement.py --name m2_known
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from kg.config import load_config
from kg.layer0_structure import parse_corpus
from label_sources import refuse_overwrite

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels"
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
DEFAULT_CASES = [
    ("event2", "en-making-a-career::Performance Improvement Plans::b0"),
    ("event2", "en-making-a-career::Performance Improvement Plans::b1"),
]
COLUMNS = ["row_id", "event", "old_file", "old_lines", "old_section", "old_text",
           "answer", "new_refs", "note"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="m2_known")
    ap.add_argument("--case", nargs=2, action="append", metavar=("EVENT", "OLD_BLOCK_ID"),
                    help="add a case (default: the E3 -> E2 severance section)")
    args = ap.parse_args()
    cases = args.case or DEFAULT_CASES
    sample, key_path = LABELS / f"{args.name}_sample.csv", LABELS / f"{args.name}_key.json"
    refuse_overwrite([sample, key_path])
    random_key = json.loads((LABELS / "m2_blind_key.json").read_text(encoding="utf-8"))

    cfg = load_config(ROOT / "config.yaml")
    blocks = {}
    for d in parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, T0):
        for pb in d.blocks:
            blocks[pb.block.block_id] = (d, pb.block)

    rows, key = [], {"kind": "known cases (hand-picked, reported separately)",
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "rows": {}, "refs": {}}
    events = {ev for ev, _ in cases}
    key["refs"] = {r: v for r, v in random_key["refs"].items()
                   if any(r.startswith(f"{ev[0]}{ev[-1]}-") for ev in events)}
    for i, (ev, block_id) in enumerate(cases, start=1):
        if block_id not in blocks:
            raise SystemExit(f"unknown old block {block_id}")
        d, b = blocks[block_id]
        row_id = f"{ev}-K{i:02d}"
        rows.append({"row_id": row_id, "event": ev, "old_file": d.version.source_file,
                     "old_lines": f"{b.lines.start}-{b.lines.end}",
                     "old_section": block_id.split("::")[1], "old_text": b.text,
                     "answer": "", "new_refs": "", "note": ""})
        key["rows"][row_id] = {"doc_key": b.doc_key, "old_block_uid": b.block_uid,
                               "old_block_id": block_id, "stratum": "known_case"}
    with sample.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} known-case rows -> {sample.name}; use the {', '.join(sorted(events))} "
          f"rows of m2_blind_new_blocks.csv for new_refs")


if __name__ == "__main__":
    main()
