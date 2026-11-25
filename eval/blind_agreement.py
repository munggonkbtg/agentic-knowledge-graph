"""Score the diff against blind answers (m2_blind_sample_<source>.csv).

For each answered row, the person's view and the diff's view are reduced to:

* status:  same | edited | moved | removed
           The person answers same/edited/removed; it counts as "moved" when the
           new block(s) they name are in a different document (cross-document
           move), whatever the wording change.
           The diff's unchanged -> same, edited -> edited, moved -> moved,
           removed -> removed.
* partner: the new block(s). The diff agrees on the partner when its new block
           is one of the person's refs (or both say removed).

Reported per event and per stratum (text_still_present / text_not_present),
plus the rows where the two disagree. Counts only (no document text).

The answers are read per label source (eval/label_sources.py): _human (a
person) or _ai (an AI reviewer). Only a person's answers count for "done".

Run:  uv run python eval/blind_agreement.py [--name m2_known] [--labels human|ai|both]
Writes eval/results/<name>_agreement_<source>.md, and <name>_labels_human_vs_ai.md
when both sources have answers.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels"
ANSWERS = {"same", "edited", "removed"}
DIFF_TO_STATUS = {"unchanged": "same", "edited": "edited", "moved": "moved",
                  "removed": "removed"}


def person_view(row: dict, key: dict) -> tuple[str, set[tuple[str, str]]]:
    answer = row["answer"].strip().lower()
    if answer not in ANSWERS:
        raise ValueError(f"{row['row_id']}: answer must be one of {sorted(ANSWERS)}")
    refs = {r.strip() for r in row["new_refs"].split(";") if r.strip()}
    unknown = refs - set(key["refs"])
    if unknown:
        raise ValueError(f"{row['row_id']}: unknown ref(s) {sorted(unknown)}")
    partners = {(key["refs"][r]["doc_key"], key["refs"][r]["new_block_id"]) for r in refs}
    if answer == "removed":
        if partners:
            raise ValueError(f"{row['row_id']}: 'removed' should have no new_refs")
        return "removed", set()
    if not partners:
        raise ValueError(f"{row['row_id']}: '{answer}' needs at least one ref")
    old_doc = key["rows"][row["row_id"]]["doc_key"]
    if any(doc != old_doc for doc, _ in partners):
        return "moved", partners
    return answer, partners


def score(rows: list[dict], key: dict,
          diff: dict[str, tuple[str, frozenset[tuple[str, str]]]]) -> dict:
    """diff: old_block_uid -> (diff status, set of (doc_key, new_block_id); empty if none)."""
    groups: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"answered": 0, "status_agree": 0, "partner_agree": 0, "both_agree": 0})
    disagreements = []
    unanswered = 0
    for row in rows:
        if not row["answer"].strip():
            unanswered += 1
            continue
        info = key["rows"][row["row_id"]]
        p_status, p_partners = person_view(row, key)
        if info["old_block_uid"] not in diff:
            raise ValueError(f"{row['row_id']}: block not found in the current diff "
                             "(was layer 0 changed after the sheet was made?)")
        d_raw, d_partner = diff[info["old_block_uid"]]
        d_status = DIFF_TO_STATUS[d_raw]
        status_ok = p_status == d_status
        # Agree when every new block the diff names is one the person named (both
        # empty for "removed"). A split the diff found counts only if the person
        # named all of its blocks.
        partner_ok = (not d_partner and not p_partners) or (bool(d_partner)
                                                             and d_partner <= p_partners)
        g = groups[(row["event"], info["stratum"])]
        g["answered"] += 1
        g["status_agree"] += status_ok
        g["partner_agree"] += partner_ok
        g["both_agree"] += status_ok and partner_ok
        if not (status_ok and partner_ok):
            disagreements.append({"row_id": row["row_id"], "person": p_status,
                                  "diff": d_status, "partner_agree": partner_ok})
    total = {k: sum(g[k] for g in groups.values())
             for k in ("answered", "status_agree", "partner_agree", "both_agree")}
    return {"groups": dict(groups), "total": total, "unanswered": unanswered,
            "disagreements": disagreements}


def _pct(a: int, b: int) -> str:
    return f"{a / b:.0%}" if b else "-"


def render(s: dict) -> str:
    out = ["# M2: diff vs the person's blind answers", "",
           "| event | stratum | answered | status agrees | partner agrees | both |",
           "|---|---|---|---|---|---|"]
    for (ev, st), g in sorted(s["groups"].items()):
        out.append(f"| {ev} | {st} | {g['answered']} | {_pct(g['status_agree'], g['answered'])} "
                   f"| {_pct(g['partner_agree'], g['answered'])} "
                   f"| {_pct(g['both_agree'], g['answered'])} |")
    t = s["total"]
    out += ["", f"**All answered rows ({t['answered']}):** status {_pct(t['status_agree'], t['answered'])}, "
            f"partner {_pct(t['partner_agree'], t['answered'])}, "
            f"both {_pct(t['both_agree'], t['answered'])}. Unanswered: {s['unanswered']}."]
    if s["disagreements"]:
        out += ["", "## Disagreements", "", "| row | person | diff | partner agrees |",
                "|---|---|---|---|"]
        out += [f"| {d['row_id']} | {d['person']} | {d['diff']} | {d['partner_agree']} |"
                for d in s["disagreements"]]
    return "\n".join(out)


def current_diff() -> dict[str, tuple[str, tuple[str, str] | None]]:
    from kg.config import load_config
    from kg.diff import diff_event
    from kg.layer0_structure import Normalizer, parse_corpus

    cfg = load_config(ROOT / "config.yaml")
    norm = Normalizer(cfg.layer0)
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    olds = {d.document.doc_key: d
            for d in parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, t0)}
    out = {}
    for ev in ("event1", "event2", "event3"):
        uploaded = parse_corpus(ROOT / "data" / "uploads" / ev, cfg.layer0, t0)
        for d in diff_event(olds, uploaded, cfg.diff, norm):
            for m in d.matches:
                if m.old is not None:
                    partners = frozenset((pb.block.doc_key, pb.block.block_id)
                                         for pb in m.new_blocks)
                    out[m.old.block.block_uid] = (m.status.value, partners)
    return out


ANSWER_COLUMNS = ["answer", "new_refs", "note"]


def main() -> None:
    import argparse

    from label_sources import read_rows, sheet, source_agreement, source_line, sources_to_score

    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="m2_blind",
                    help="m2_blind (random sample) or m2_known (hand-picked known cases)")
    ap.add_argument("--labels", default="both", choices=["human", "ai", "both"],
                    help="whose answers to score against (both = every source with answers)")
    args = ap.parse_args()
    name, stem = args.name, f"{args.name}_sample"
    key = json.loads((LABELS / f"{name}_key.json").read_text(encoding="utf-8"))
    sources = sources_to_score(args.labels, stem, ANSWER_COLUMNS)
    if not sources:
        raise SystemExit(f"no answered rows in any {stem}_<source>.csv")
    diff = current_diff()
    kind = "" if name == "m2_blind" else f" — {name} (hand-picked cases, not a random sample)"
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    rows_by = {src: read_rows(sheet(stem, src)) for src in sources}
    for src, rows in rows_by.items():
        text = (render(score(rows, key, diff))
                .replace("# M2: diff vs the person's blind answers",
                         f"# M2: diff vs blind answers{kind}\n\n"
                         + source_line(src, rows, ANSWER_COLUMNS))
                .replace("| row | person | diff |", f"| row | {src} | diff |"))
        (ROOT / "eval" / "results" / f"{name}_agreement_{src}.md").write_text(text, encoding="utf-8")
        print(text, "\n")
    if len(rows_by) == 2:
        text = f"# {name}: human vs AI labels\n\n" + source_agreement(
            rows_by["human"], rows_by["ai"], ANSWER_COLUMNS[:2])
        (ROOT / "eval" / "results" / f"{name}_labels_human_vs_ai.md").write_text(text, encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
