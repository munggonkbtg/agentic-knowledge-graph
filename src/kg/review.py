"""Human review of impact results (M5, workflow step 14).

`kg impact --check --review` writes a review sheet: for every change where the
broken-reference rule or the LLM check flagged a candidate, the top
`impact.check_top_n` candidates with the system's judgement shown (decided
2026-11-26). A person fills `decision` and `note`; `kg review-import` appends
the decisions to the review history. Label source of these decisions:
`human_review` (a person, not blind to the system); they are never mixed with
blind `_human` labels.

Decisions:
* needs_update  the candidate's text must change because of this change
* review_only   a person should look at it, but its text stays correct
* not_affected  the change does not concern it
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

DECISIONS = ("needs_update", "review_only", "not_affected")
SHEET_COLUMNS = [
    "review_id", "document", "change", "changed_section", "change_old_text",
    "change_new_text", "rank", "file", "block_id", "lines", "candidate_text",
    "signals", "rule", "llm_verdict", "llm_reason", "llm_evidence", "historical",
    "decision", "note", "changed_block_uid", "block_uid",
]
HISTORY_COLUMNS = [
    "reviewed_at", "sheet", "review_id", "document", "changed_block_uid", "block_uid",
    "decision", "note", "rank", "signals", "rule", "llm_verdict", "label_source",
]


def flagged(candidates: list[dict], top: int) -> bool:
    """A change goes to review when, in its checked top, the rule fired or the LLM
    said needs_update."""
    return any(c.get("rule") or c.get("verdict") == "needs_update" for c in candidates[:top])


def review_rows(changes: list[dict], top: int) -> list[dict]:
    """Rows of a review sheet. Each change: document, change, changed_section,
    old_text, new_text, changed_block_uid, candidates (in report order, each with
    rank, file, block_id, lines, block_uid, text, signals, rule, verdict, reason,
    evidence, historical)."""
    rows = []
    for ch in changes:
        if not flagged(ch["candidates"], top):
            continue
        for c in ch["candidates"][:top]:
            rows.append({
                "review_id": f"R{len(rows) + 1:04d}", "document": ch["document"],
                "change": ch["change"], "changed_section": ch["changed_section"],
                "change_old_text": ch["old_text"], "change_new_text": ch["new_text"],
                "rank": c["rank"], "file": c["file"], "block_id": c["block_id"],
                "lines": c["lines"], "candidate_text": c["text"], "signals": c["signals"],
                "rule": c.get("rule", ""), "llm_verdict": c.get("verdict", ""),
                "llm_reason": c.get("reason", ""), "llm_evidence": c.get("evidence", ""),
                "historical": c.get("historical", ""), "decision": "", "note": "",
                "changed_block_uid": ch["changed_block_uid"], "block_uid": c["block_uid"]})
    return rows


def write_sheet(path: Path, rows: list[dict]) -> None:
    if path.exists():
        raise FileExistsError(f"{path} exists (it may hold decisions); not overwriting")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def read_decisions(path: Path) -> tuple[list[dict], list[str]]:
    """Filled rows of a sheet, and the errors found (unknown decision values).
    Blank decisions are skipped, not errors."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    done, errors = [], []
    for r in rows:
        d = r.get("decision", "").strip().lower().replace(" ", "_")
        if not d:
            continue
        if d not in DECISIONS:
            errors.append(f"{r['review_id']}: decision {r['decision']!r} is not one of "
                          f"{', '.join(DECISIONS)}")
            continue
        done.append({**r, "decision": d})
    return done, errors


def import_decisions(sheet: Path, history: Path, now: datetime) -> dict[str, int]:
    """Append a sheet's decisions to the review history. A decision already in the
    history for the same (sheet, review_id) is skipped when unchanged; a changed
    decision is appended (the latest one counts)."""
    done, errors = read_decisions(sheet)
    if errors:
        raise ValueError("; ".join(errors))
    latest: dict[tuple[str, str], str] = {}
    if history.exists():
        with history.open(encoding="utf-8-sig", newline="") as f:
            for h in csv.DictReader(f):
                latest[(h["sheet"], h["review_id"])] = h["decision"]
    new = [r for r in done if latest.get((sheet.name, r["review_id"])) != r["decision"]]
    changed = sum(1 for r in new if (sheet.name, r["review_id"]) in latest)
    history.parent.mkdir(parents=True, exist_ok=True)
    first = not history.exists()
    with history.open("a", encoding="utf-8-sig" if first else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if first:
            w.writeheader()
        for r in new:
            w.writerow({"reviewed_at": now.isoformat(timespec="seconds"), "sheet": sheet.name,
                        "review_id": r["review_id"], "document": r["document"],
                        "changed_block_uid": r["changed_block_uid"],
                        "block_uid": r["block_uid"], "decision": r["decision"],
                        "note": r.get("note", ""), "rank": r["rank"],
                        "signals": r.get("signals", ""), "rule": r["rule"],
                        "llm_verdict": r["llm_verdict"], "label_source": "human_review"})
    return {"decided": len(done), "new": len(new) - changed, "changed": changed,
            "unchanged": len(done) - len(new)}


def latest_decisions(history: Path) -> list[dict]:
    """The latest decision per (sheet, review_id) in the review history."""
    if not history.exists():
        return []
    latest: dict[tuple[str, str], dict] = {}
    with history.open(encoding="utf-8-sig", newline="") as f:
        for h in csv.DictReader(f):
            latest[(h["sheet"], h["review_id"])] = h
    return list(latest.values())


def edges_to_review(store, row: dict) -> list[str]:
    """Edge ids that led from the changed block to the reviewed candidate: the
    candidate's open REFERENCES to the changed block's document at the changed
    section or heading (or the whole document), and DEPENDS between the two."""
    from kg.impact import _cites, heading_anchor, section_key

    pos = store.block_position(row["changed_block_uid"])
    if pos is None:
        return []
    path = pos["block_id"].split("::")[1] if pos["block_id"] else "_"
    key, anchor = section_key(path), heading_anchor(path)
    ids = []
    for e in store.citation_edges(row["block_uid"], pos["doc_key"]):
        from kg.layer1_references import compact
        cited = compact(e["cited_section"] or "")[0].lower()
        if cited == "" or (key and _cites(cited, key.lower())) or (anchor and cited == anchor):
            ids.append(e["id"])
    ids += store.depends_between(row["block_uid"], row["changed_block_uid"])
    return ids


def apply_reviews(store, history: Path, factor: float, now) -> dict[str, int]:
    """Step 15: a person's decisions change the confidence of the edges behind
    them. not_affected -> rejected (confidence x factor); needs_update and
    review_only -> approved (original confidence). Idempotent."""
    out = {"decisions": 0, "rejected_edges": 0, "approved_edges": 0, "without_edges": 0}
    for row in latest_decisions(history):
        out["decisions"] += 1
        ids = edges_to_review(store, row)
        if not ids:
            out["without_edges"] += 1
            continue
        status = "rejected" if row["decision"] == "not_affected" else "approved"
        out[f"{status}_edges"] += store.set_review_status(ids, status, factor, now)
    return out
