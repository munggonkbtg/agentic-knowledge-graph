"""M2 'done' check: how often does the diff agree with a person?

Reads the review sheet after a person has filled in the ``verdict`` column
('correct' or 'wrong') and reports agreement per event and per status.

Rows with identical text at the same position are not in the sheet (nothing to
judge) and are counted separately as "not reviewed, identical".

Run:  uv run python eval/diff_agreement.py [data/labels/m2_diff_review.csv]
Writes counts only (no document text) to eval/results/m2_diff_agreement.md.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHEET = ROOT / "data" / "labels" / "m2_diff_review.csv"
VALID = {"correct", "wrong"}


def summarize(rows: list[dict]) -> dict:
    groups: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"rows": 0, "labelled": 0, "correct": 0})
    invalid: list[str] = []
    wrong_scores: list[tuple[str, str, str]] = []
    for r in rows:
        g = groups[(r["event"], r["status"])]
        g["rows"] += 1
        verdict = r.get("verdict", "").strip().lower()
        if not verdict:
            continue
        if verdict not in VALID:
            invalid.append(r["row_id"])
            continue
        g["labelled"] += 1
        if verdict == "correct":
            g["correct"] += 1
        else:
            score = r["similarity"] or r["closest_other_similarity"]
            wrong_scores.append((r["row_id"], r["status"], score))
    total = {k: sum(g[k] for g in groups.values()) for k in ("rows", "labelled", "correct")}
    return {"groups": dict(groups), "total": total, "invalid": invalid,
            "wrong_scores": wrong_scores}


def _pct(a: int, b: int) -> str:
    return f"{a / b:.0%}" if b else "-"


def render(s: dict) -> str:
    out = ["# M2: diff agreement with a person", "",
           "| event | status | rows | labelled | correct | agreement |", "|---|---|---|---|---|---|"]
    for (ev, st), g in sorted(s["groups"].items()):
        out.append(f"| {ev} | {st} | {g['rows']} | {g['labelled']} | {g['correct']} | "
                   f"{_pct(g['correct'], g['labelled'])} |")
    t = s["total"]
    out += ["", f"**All rows:** {t['labelled']} of {t['rows']} labelled, "
            f"agreement {_pct(t['correct'], t['labelled'])}."]
    if s["invalid"]:
        out.append(f"\nRows with a verdict other than correct/wrong (ignored): "
                   f"{', '.join(s['invalid'])}")
    if s["wrong_scores"]:
        out += ["", "## Rows marked wrong", "", "| row | status | similarity |", "|---|---|---|"]
        out += [f"| {rid} | {st} | {sc} |" for rid, st, sc in s["wrong_scores"]]
    return "\n".join(out)


def main() -> None:
    sheet = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SHEET
    with sheet.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    text = render(summarize(rows))
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / "m2_diff_agreement.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
