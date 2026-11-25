"""Build a *blind* labelling sheet for REFERENCES (M3 "done" check).

The person reads a block and lists every document it cites, without seeing what
layer 1 found. Precision and recall are then computed by
eval/references_agreement.py.

Sampling (fixed seed, recorded in the key file), body blocks of the initial
corpus only (footnote entries are skipped by layer 1 by rule):
* Thai blocks with a citation cue (มาตรา, ข้อ, พระราชบัญญัติ, ประมวลกฎหมาย,
  กฎกระทรวง, ระเบียบ): a fixed number per document.
* Thai blocks without a cue: a few, to catch citations the cue list misses.
* English blocks with a link: all. English blocks without: a few.
The cue is a plain word list on the text, not layer 1's output. Results are
reported per stratum.

Files written to data/labels/ (not in git: they contain document text):
* m3_references_sample.csv – one row per block. Fill in `citations`:
    one citation per item, items separated by ";", each item "<document> | <section>"
      <document> = a doc_key from m3_references_documents.csv,
                   or "self" for the block's own document,
                   or "ext: <name as written>" for a law / page not in the store
                   (for a web link, "ext: <the URL>")
      <section>  = what is cited, e.g. "มาตรา 118 (6)", "ข้อ 3", "#your-first-90-days";
                   leave empty when the whole document is mentioned
    Write "none" if the block cites nothing.
    Example:  th-labour-protection-act-2541 | มาตรา 6; ext: ประมวลกฎหมายอาญา |
* m3_references_documents.csv – the documents in the store (doc_key, title).
* m3_references_key.json – seed, strata and which block each row is.

Run:  uv run python eval/make_references_sheet.py
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

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels"
SAMPLE = LABELS / "m3_references_sample.csv"
DOCS = LABELS / "m3_references_documents.csv"
KEY = LABELS / "m3_references_key.json"
SEED = 20261125
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)

TH_CUES = ("มาตรา", "ข้อ", "พระราชบัญญัติ", "ประมวลกฎหมาย", "กฎกระทรวง", "ระเบียบ")
EN_CUES = ("](", "http")
TH_PER_DOC = {"th-labour-protection-act-2541": 20, "th-ministerial-regulation-9-2541": 5,
              "th-regulation-workplace-inspection-2542": 5,
              "th-regulation-criminal-proceedings-2558": 10}
TH_NO_CUE = 10
EN_NO_CUE = 10

SAMPLE_COLUMNS = ["row_id", "file", "lines", "document_title", "section", "block_text",
                  "citations", "note"]


def main() -> None:
    for p in (SAMPLE, DOCS, KEY):
        if p.exists():
            raise SystemExit(f"{p} exists (it may hold labels); not overwriting")
    cfg = load_config(ROOT / "config.yaml")
    docs = parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, T0)
    rng = random.Random(SEED)

    pools: dict[str, list] = {}
    for d in docs:
        lang = d.document.language.value
        cues = TH_CUES if lang == "th" else EN_CUES
        for pb in d.blocks:
            if pb.block.role != BlockRole.BODY:
                continue
            cue = any(c in pb.block.text for c in cues)
            if lang == "th" and cue:
                stratum = f"th_cue:{d.document.doc_key}"
            else:
                stratum = f"{lang}_{'cue' if cue else 'no_cue'}"
            pools.setdefault(stratum, []).append((d, pb))

    chosen = []
    for key, n in TH_PER_DOC.items():
        pool = pools.get(f"th_cue:{key}", [])
        chosen += [("th_cue", x) for x in rng.sample(pool, min(n, len(pool)))]
    chosen += [("th_no_cue", x) for x in rng.sample(pools.get("th_no_cue", []),
                                                    min(TH_NO_CUE, len(pools.get("th_no_cue", []))))]
    chosen += [("en_cue", x) for x in pools.get("en_cue", [])]
    chosen += [("en_no_cue", x) for x in rng.sample(pools.get("en_no_cue", []),
                                                    min(EN_NO_CUE, len(pools.get("en_no_cue", []))))]
    rng.shuffle(chosen)

    rows, key = [], {"seed": SEED, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "rows": {}}
    for i, (stratum, (d, pb)) in enumerate(chosen, start=1):
        b = pb.block
        row_id = f"R{i:03d}"
        rows.append({"row_id": row_id, "file": d.version.source_file,
                     "lines": f"{b.lines.start}-{b.lines.end}", "document_title": d.document.title,
                     "section": b.block_id.split("::")[1], "block_text": b.text,
                     "citations": "", "note": ""})
        key["rows"][row_id] = {"doc_key": b.doc_key, "block_uid": b.block_uid,
                               "language": d.document.language.value, "stratum": stratum}

    LABELS.mkdir(parents=True, exist_ok=True)
    with SAMPLE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SAMPLE_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with DOCS.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["doc_key", "title", "language"])
        w.writeheader()
        w.writerows({"doc_key": d.document.doc_key, "title": d.document.title,
                     "language": d.document.language.value} for d in docs)
    KEY.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    strata: dict[str, int] = {}
    for r in key["rows"].values():
        strata[r["stratum"]] = strata.get(r["stratum"], 0) + 1
    print(f"{len(rows)} blocks to label {strata}")


if __name__ == "__main__":
    main()
