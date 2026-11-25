"""Label sheets kept apart by who filled them in.

A generator writes a blank sheet, e.g. m3_references_test_sample.csv. Answers
live in copies named by their source:

* <stem>_human.csv  a person, blind to the system's output, without AI help
* <stem>_ai.csv     an AI reviewer (not a person's blind answers)
* <stem>_person_seen_ai.csv  a person who answered after reading the AI answers
                    for the same rows (not blind, not independent of the AI)

Only a person's blind answers (_human) count for a milestone's "done" check.
Scoring scripts take --labels human | ai | person_seen_ai | all and name the
source in every result.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels"
SOURCES = ("human", "ai", "person_seen_ai")

DESCRIPTION = {
    "human": "a person, blind to the system's output, without AI help",
    "ai": "an AI reviewer, not a person; does not count for a milestone's done check",
    "person_seen_ai": ("a person who had read the AI reviewer's answers for the same rows; "
                       "not independent of them, so not a blind human label"),
}


def sheet(stem: str, source: str, labels: Path = LABELS) -> Path:
    if source not in SOURCES:
        raise ValueError(f"label source must be one of {SOURCES}")
    return labels / f"{stem}_{source}.csv"


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def answered(rows: list[dict], columns: list[str]) -> int:
    """Rows with at least one answer (a note alone is not an answer)."""
    cols = [c for c in columns if c != "note"]
    return sum(1 for r in rows if any(r.get(c, "").strip() for c in cols))


def sources_to_score(choice: str, stem: str, columns: list[str],
                     labels: Path = LABELS) -> list[str]:
    """The sources to report: one named source, or with 'both' every source whose
    sheet exists and has at least one answered row. Exits with a message when the
    named source has no sheet or no answered row (no empty report is written)."""
    if choice in ("all", "both"):  # "both" kept from when there were two sources
        return [s for s in SOURCES if sheet(stem, s, labels).exists()
                and answered(read_rows(sheet(stem, s, labels)), columns)]
    path = sheet(stem, choice, labels)
    if not path.exists():
        raise SystemExit(f"no {choice} labels: {path.name} does not exist")
    if not answered(read_rows(path), columns):
        raise SystemExit(f"no {choice} labels yet: {path.name} has no answered rows")
    return [choice]


def source_line(source: str, rows: list[dict], columns: list[str]) -> str:
    return (f"**Label source: {source}** ({DESCRIPTION[source]}); "
            f"{answered(rows, columns)} of {len(rows)} rows answered.")


def _norm(value: str) -> str:
    """Compare answers ignoring case, spaces around items and item order."""
    items = [x.strip().lower() for x in value.split(";") if x.strip()]
    return ";".join(sorted(items))


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa for two raters over the same items (None if undefined)."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in ca) / (n * n)
    return None if math.isclose(pe, 1.0) else (po - pe) / (1 - pe)


def source_agreement(human: list[dict], ai: list[dict], columns: list[str]) -> str:
    """Markdown table: per answer column, rows both answered, exact agreement and
    Cohen's kappa (kappa only for columns with few distinct answers)."""
    by_id = {r["row_id"]: r for r in ai}
    out = ["## Agreement between the human and the AI labels", "",
           "Rows answered by both; answers compared ignoring case and item order.", "",
           "| column | rows | agree | kappa |", "|---|---|---|---|"]
    for col in columns:
        pairs = [(_norm(h[col]), _norm(by_id[h["row_id"]][col])) for h in human
                 if h["row_id"] in by_id and h[col].strip() and by_id[h["row_id"]][col].strip()]
        agree = sum(a == b for a, b in pairs)
        k = kappa(pairs) if len({x for p in pairs for x in p}) <= 6 else None
        out.append(f"| {col} | {len(pairs)} | "
                   f"{f'{agree / len(pairs):.2f}' if pairs else '-'} | "
                   f"{f'{k:.2f}' if k is not None else '-'} |")
    return "\n".join(out)


def refuse_overwrite(paths: list[Path]) -> None:
    """Exit if a sheet, or a labelled copy of it, already exists; otherwise back up
    data/labels/ before the caller writes anything."""
    for p in paths:
        variants = [p] + ([p.with_name(f"{p.stem}_{s}.csv") for s in SOURCES]
                          if p.suffix == ".csv" else [])
        for v in variants:
            if v.exists():
                raise SystemExit(f"{v} exists (it may hold labels); not overwriting")
    from kg.backup import backup_labels

    dest = backup_labels(LABELS)
    if dest is not None:
        print(f"labels backed up to {dest}")
