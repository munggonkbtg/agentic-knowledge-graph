"""Build a *blind* labelling sheet for MENTIONS (M4 check).

The person reads a block and lists every entity it mentions, without seeing
what layer 2 found. Precision and recall per type and language, and the share
of mentions that fit no type, are then computed against layer 2.

DRAFT labelling guide (the user decides the final guide before labelling):
* Types: Concept (a right, benefit, defined term or procedure with rules or
  values attached), Role (a role given duties or powers), Artifact (a form,
  system or non-legal document), Body (agency, committee, fund, company),
  Place (jurisdiction), Other (an entity that fits none of these).
* Not entities: laws and their sections (those are REFERENCES), people's names,
  bare dates and amounts.
* Write the term as it appears in the block (Thai spacing does not matter).

Sampling (fixed seed, recorded in the key file): body blocks of the initial
corpus, 20 Thai and 20 English, random. English has only 74 body blocks, so
this is about a quarter of them.

Files written to data/labels/ (not in git: they contain document text):
* m4_mentions_sample.csv        blank template
* m4_mentions_sample_human.csv  the same, for a person to fill. Column
    `mentions`: items separated by ";", each "<Type> | <term as written>".
    Write "none" if the block mentions no entity.
    Example:  Concept | ค่าชดเชย; Role | พนักงานตรวจแรงงาน
  AI answers, if any, go in m4_mentions_sample_ai.csv (eval/label_sources.py).
* m4_mentions_key.json          seed and which block each row is

Run:  uv run python eval/make_mentions_sheet.py
"""

from __future__ import annotations

import csv
import json
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path

from kg.config import load_config
from kg.layer0_structure import parse_corpus
from kg.models import BlockRole
from label_sources import refuse_overwrite

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels"
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
SEED = 20261201
PER_LANGUAGE = {"th": 20, "en": 20}
COLUMNS = ["row_id", "file", "lines", "document_title", "section", "block_text",
           "mentions", "note"]


def main() -> None:
    sample, key_path = LABELS / "m4_mentions_sample.csv", LABELS / "m4_mentions_key.json"
    refuse_overwrite([sample, key_path])
    cfg = load_config(ROOT / "config.yaml")
    docs = parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, T0)
    rng = random.Random(SEED)
    pools: dict[str, list] = {}
    for d in sorted(docs, key=lambda d: d.document.doc_key):
        for pb in d.blocks:
            if pb.block.role == BlockRole.BODY:
                pools.setdefault(d.document.language.value, []).append((d, pb))
    chosen = [x for lang, n in PER_LANGUAGE.items() for x in rng.sample(pools[lang], n)]
    rng.shuffle(chosen)
    rows, key = [], {"seed": SEED, "created": datetime.now(timezone.utc).isoformat(
        timespec="seconds"), "rows": {}}
    for i, (d, pb) in enumerate(chosen, start=1):
        b = pb.block
        rid = f"M{i:03d}"
        rows.append({"row_id": rid, "file": d.version.source_file,
                     "lines": f"{b.lines.start}-{b.lines.end}", "document_title": d.document.title,
                     "section": b.block_id.split("::")[1], "block_text": b.text,
                     "mentions": "", "note": ""})
        key["rows"][rid] = {"doc_key": b.doc_key, "block_uid": b.block_uid,
                            "language": d.document.language.value}
    LABELS.mkdir(parents=True, exist_ok=True)
    with sample.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    shutil.copyfile(sample, LABELS / "m4_mentions_sample_human.csv")
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} blocks to label in m4_mentions_sample_human.csv")


if __name__ == "__main__":
    main()
