"""Blind review: sampling and scoring logic (no files, no database)."""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from blind_agreement import person_view, score  # noqa: E402
from make_blind_sheet import pick  # noqa: E402

KEY = {
    "rows": {
        "e1-S01": {"doc_key": "doc-a", "old_block_uid": "u1", "stratum": "text_still_present"},
        "e1-S02": {"doc_key": "doc-a", "old_block_uid": "u2", "stratum": "text_not_present"},
        "e1-S03": {"doc_key": "doc-a", "old_block_uid": "u3", "stratum": "text_not_present"},
        "e1-S04": {"doc_key": "doc-a", "old_block_uid": "u4", "stratum": "text_not_present"},
    },
    "refs": {
        "e1-N001": {"doc_key": "doc-a", "new_block_id": "doc-a::S::b0"},
        "e1-N002": {"doc_key": "doc-a", "new_block_id": "doc-a::S::b1"},
        "e1-N003": {"doc_key": "doc-b", "new_block_id": "doc-b::_::b0"},
    },
}


def row(rid, answer, refs="", event="event1"):
    return {"row_id": rid, "event": event, "answer": answer, "new_refs": refs}


def test_person_view_derives_moved_from_the_ref_document():
    assert person_view(row("e1-S01", "same", "e1-N001"), KEY) == \
           ("same", {("doc-a", "doc-a::S::b0")})
    assert person_view(row("e1-S02", "edited", "e1-N003"), KEY)[0] == "moved"
    assert person_view(row("e1-S03", "removed"), KEY) == ("removed", set())


@pytest.mark.parametrize("bad", [
    row("e1-S01", "maybe", "e1-N001"),     # unknown answer
    row("e1-S01", "same", "e1-N999"),      # unknown ref
    row("e1-S01", "removed", "e1-N001"),   # removed with a ref
    row("e1-S01", "edited", ""),           # edited without a ref
])
def test_person_view_rejects_inconsistent_rows(bad):
    with pytest.raises(ValueError):
        person_view(bad, KEY)


def test_score_status_and_partner_separately():
    diff = {
        "u1": ("unchanged", frozenset({("doc-a", "doc-a::S::b0")})),  # agrees fully
        "u2": ("removed", frozenset()),                  # person: moved -> disagrees
        "u3": ("edited", frozenset({("doc-a", "doc-a::S::b1")})),  # right status, wrong partner
        "u4": ("removed", frozenset()),                  # unanswered
    }
    rows = [row("e1-S01", "same", "e1-N001"), row("e1-S02", "edited", "e1-N003"),
            row("e1-S03", "edited", "e1-N001; e1-N003"), row("e1-S04", "")]
    s = score(rows, KEY, diff)
    assert s["unanswered"] == 1
    assert s["total"] == {"answered": 3, "status_agree": 1, "partner_agree": 1, "both_agree": 1}
    assert [d["row_id"] for d in s["disagreements"]] == ["e1-S02", "e1-S03"]
    # e1-S03: the person named two refs (split), one in another document -> moved
    assert s["disagreements"][1]["person"] == "moved"


def test_pick_balances_strata_and_tops_up_a_short_one():
    rng = random.Random(1)
    chosen = pick(rng, same=list(range(20)), other=list(range(100, 103)), k=10)
    strata = [s for s, _ in chosen]
    assert strata.count("text_not_present") == 3 and strata.count("text_still_present") == 7
    chosen = pick(random.Random(1), same=list(range(20)), other=list(range(100, 120)), k=10)
    assert [s for s, _ in chosen].count("text_not_present") == 5


def test_split_counts_only_when_the_person_named_every_block():
    key = {"rows": {"e1-S01": {"doc_key": "doc-a", "old_block_uid": "u1",
                               "stratum": "known_case"}},
           "refs": KEY["refs"]}
    both = frozenset({("doc-b", "doc-b::_::b0"), ("doc-a", "doc-a::S::b0")})
    diff = {"u1": ("moved", both)}
    key["refs"] = {**KEY["refs"], "e1-N004": {"doc_key": "doc-b", "new_block_id": "doc-b::_::b0"}}
    full = score([row("e1-S01", "edited", "e1-N004; e1-N001")], key, diff)
    part = score([row("e1-S01", "edited", "e1-N004")], key, diff)
    assert full["total"]["partner_agree"] == 1 and part["total"]["partner_agree"] == 0
