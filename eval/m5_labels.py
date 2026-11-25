"""The M5 needs_review labels, merged from every sheet, in one place.

Sheets (per label source, eval/label_sources.py):
* m5_candidates, m5s_candidates, m5e_candidates  pooled candidates
* m5_additions, m5s_additions                    blocks the pools missed, added by
                                                 the labeller (store_ref or block_uid)
A (change, block) pair labelled in two sheets counts once.

Each pair carries `historical` (kg.historical): blocks of an amending act or
reason notes appended to a consolidated act. They are reported apart and left
out of the main numbers (decided 2026-11-25).
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from label_sources import sheet

from kg.historical import historical_reason

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels"
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
POOLS = ("m5", "m5s", "m5e")
ADDITIONS = ("m5", "m5s")


@dataclass(frozen=True)
class Positive:
    change_id: str
    block_uid: str
    kind: str
    needs_revision: str
    origin: str  # sheet and row, e.g. "m5s_candidates:S08-B09"
    historical: str | None  # amending_act | reason_note | None


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _ids(cell: str) -> list[str]:
    return [x.strip() for x in cell.split(";") if x.strip()]


def block_info() -> dict[str, tuple[str, str]]:
    """block_uid -> (document title, block text) over the initial corpus, every
    upload event and the synthetic events."""
    from kg.config import load_config
    from kg.layer0_structure import parse_corpus

    cfg = load_config(ROOT / "config.yaml")
    out = {}
    dirs = [ROOT / "data" / "initial_corpus", *sorted((ROOT / "data" / "uploads").glob("*")),
            *sorted((ROOT / "data" / "uploads_synthetic").glob("*"))]
    for d in dirs:
        if d.is_dir():
            for doc in parse_corpus(d, cfg.layer0, T0):
                for pb in doc.blocks:
                    out.setdefault(pb.block.block_uid, (doc.document.title, pb.block.text))
    return out


def positives(source: str, info: dict[str, tuple[str, str]] | None = None) -> list[Positive]:
    info = block_info() if info is None else info
    seen: dict[tuple[str, str], Positive] = {}

    def add(cid, uid, kind, revision, origin):
        title, text = info.get(uid, ("", ""))
        p = Positive(cid, uid, kind.strip().lower(), revision.strip().lower(), origin,
                     historical_reason(title, text))
        seen.setdefault((cid, uid), p)

    for prefix in POOLS:
        path = sheet(f"{prefix}_candidates", source)
        if not path.exists():
            continue
        key = json.loads((LABELS / f"{prefix}_key.json").read_text(encoding="utf-8"))
        for r in _read(path):
            if r["needs_review"].strip().lower() == "yes":
                for cid in _ids(r["change_ids"]):
                    add(cid, key["candidates"][r["row_id"]]["block_uid"], r["kind"],
                        r.get("needs_revision", ""), f"{prefix}_candidates:{r['row_id']}")
    refs_path = LABELS / "m5s_store_refs.json"
    refs = json.loads(refs_path.read_text(encoding="utf-8")) if refs_path.exists() else {}
    for prefix in ADDITIONS:
        path = sheet(f"{prefix}_additions", source)
        if not path.exists():
            continue
        for r in _read(path):
            if r.get("needs_review", "yes").strip().lower() not in ("yes", ""):
                continue
            uid = r.get("block_uid") or refs.get(r["store_ref"], "")
            for cid in _ids(r["change_ids"]):
                add(cid, uid, r["kind"], r.get("needs_revision", ""),
                    f"{prefix}_additions:{r['store_ref']}:{cid}")
    return list(seen.values())


def by_change(pos: list[Positive], include_historical: bool = False) -> dict[str, list[Positive]]:
    out: dict[str, list[Positive]] = defaultdict(list)
    for p in pos:
        if include_historical or not p.historical:
            out[p.change_id].append(p)
    return out
