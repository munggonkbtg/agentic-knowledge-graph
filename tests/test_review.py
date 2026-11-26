"""Review sheet and review history (M5 step 14), no database."""

import csv
from datetime import datetime, timezone

import pytest

from kg.review import import_decisions, review_rows, write_sheet

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def _cand(rank, uid, verdict="not_affected", rule=""):
    return {"rank": rank, "file": "f.md", "block_id": f"d::A::b{rank}", "lines": "1-2",
            "block_uid": uid, "text": f"text {uid}", "signals": "entity", "rule": rule,
            "verdict": verdict, "reason": "r", "evidence": "e", "historical": False}


def _change(name, cands):
    return {"document": "doc", "change": name, "changed_section": "A", "old_text": "old",
            "new_text": "new", "changed_block_uid": f"chg-{name}", "candidates": cands}


def test_only_flagged_changes_go_to_the_sheet_with_their_whole_top():
    changes = [
        _change("c1", [_cand(1, "a", "needs_update"), _cand(2, "b"), _cand(3, "x")]),
        _change("c2", [_cand(1, "c"), _cand(2, "d")]),                      # nothing flagged
        _change("c3", [_cand(1, "e", rule="broken reference"), _cand(2, "f")]),
        _change("c4", [_cand(1, "g"), _cand(2, "h"), _cand(3, "i", "needs_update")]),  # beyond top
    ]
    rows = review_rows(changes, top=2)
    assert [(r["change"], r["block_uid"]) for r in rows] == [
        ("c1", "a"), ("c1", "b"), ("c3", "e"), ("c3", "f")]
    assert rows[0]["candidate_text"] == "text a" and rows[0]["change_old_text"] == "old"
    assert all(r["decision"] == "" for r in rows)
    assert [r["review_id"] for r in rows] == ["R0001", "R0002", "R0003", "R0004"]


def _fill(path, decisions):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["decision"] = decisions.get(r["review_id"], "")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_import_appends_decisions_once_and_latest_counts(tmp_path):
    sheet = tmp_path / "review_x.csv"
    rows = review_rows([_change("c1", [_cand(1, "a", "needs_update"), _cand(2, "b")])], top=2)
    write_sheet(sheet, rows)
    with pytest.raises(FileExistsError):
        write_sheet(sheet, rows)
    history = tmp_path / "review_history.csv"
    _fill(sheet, {"R0001": "needs_update", "R0002": "Review only"})
    assert import_decisions(sheet, history, NOW) == {"decided": 2, "new": 2, "changed": 0,
                                                     "unchanged": 0}
    assert import_decisions(sheet, history, NOW)["unchanged"] == 2  # rerun: nothing new
    _fill(sheet, {"R0001": "not_affected", "R0002": "review_only"})
    assert import_decisions(sheet, history, NOW) == {"decided": 2, "new": 0, "changed": 1,
                                                     "unchanged": 1}
    with history.open(encoding="utf-8-sig", newline="") as f:
        hist = list(csv.DictReader(f))
    assert [h["decision"] for h in hist] == ["needs_update", "review_only", "not_affected"]
    assert {h["label_source"] for h in hist} == {"human_review"}
    assert hist[0]["llm_verdict"] == "needs_update" and hist[0]["block_uid"] == "a"


def test_unknown_decision_stops_the_import(tmp_path):
    sheet = tmp_path / "review_y.csv"
    write_sheet(sheet, review_rows([_change("c1", [_cand(1, "a", "needs_update")])], top=1))
    _fill(sheet, {"R0001": "maybe"})
    with pytest.raises(ValueError, match="maybe"):
        import_decisions(sheet, tmp_path / "h.csv", NOW)
    assert not (tmp_path / "h.csv").exists()
