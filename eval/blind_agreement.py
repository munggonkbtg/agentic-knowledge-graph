"""Score the diff against the person's blind answers (m2_blind_sample.csv).

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
plus the rows where the two disagree. Counts only (no document text) go to
eval/results/m2_blind_agreement.md.

Run:  uv run python eval/blind_agreement.py
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
          diff: dict[str, tuple[str, tuple[str, str] | None]]) -> dict:
    """diff: old_block_uid -> (diff status, (doc_key, new_block_id) or None)."""
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
        partner_ok = (d_partner is None and not p_partners) or (d_partner in p_partners)
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
                    partner = (m.new.block.doc_key, m.new.block.block_id) if m.new else None
                    out[m.old.block.block_uid] = (m.status.value, partner)
    return out


def main() -> None:
    key = json.loads((LABELS / "m2_blind_key.json").read_text(encoding="utf-8"))
    with (LABELS / "m2_blind_sample.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    text = render(score(rows, key, current_diff()))
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / "m2_blind_agreement.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
