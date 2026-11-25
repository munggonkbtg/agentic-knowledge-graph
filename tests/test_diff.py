"""Block matching tests: small synthetic files plus the 3 real upload events."""

from collections import Counter
from pathlib import Path

import pytest

from conftest import INITIAL, T0, UPLOADS
from kg.config import DiffSettings, Layer0Settings
from kg.diff import MatchStatus, diff_event, diff_versions
from kg.layer0_structure import Normalizer, parse_corpus, parse_file

L0 = Layer0Settings()
NORM = Normalizer(L0)
CFG = DiffSettings(edit_similarity_threshold=0.5, cross_section_edit_threshold=0.8,
                   move_similarity_threshold=0.5)

LOREM_A = "The quick brown fox jumps over the lazy dog near the river bank today."
LOREM_B = "Completely different sentence about quarterly budgets and spreadsheets."
LOREM_C = "Another unrelated paragraph that talks about mountains and weather."


def _doc(tmp_path: Path, name: str, body: str, doc_key: str = "test-doc"):
    f = tmp_path / name
    f.write_text(f"---\ndoc_key: {doc_key}\ntitle: T\nlanguage: en\n---\n# T\n\n{body}",
                 encoding="utf-8")
    return parse_file(f, L0, T0)


def _by_status(matches):
    return Counter(m.status for m in matches)


def _assert_one_to_one(old, new, matches):
    olds = [m.old.block.block_uid for m in matches if m.old]
    news = [m.new.block.block_uid for m in matches if m.new]
    assert sorted(olds) == sorted(pb.block.block_uid for pb in old.blocks)
    assert sorted(news) == sorted(pb.block.block_uid for pb in new.blocks)


# ------------------------------------------------------------- synthetic


def test_inserted_paragraph_keeps_others_unchanged(tmp_path):
    old = _doc(tmp_path, "a.md", f"## S\n\n{LOREM_A}\n\n{LOREM_B}\n")
    new = _doc(tmp_path, "b.md", f"## S\n\n{LOREM_C}\n\n{LOREM_A}\n\n{LOREM_B}\n")
    m = diff_versions(old, new, CFG, NORM)
    assert _by_status(m) == {MatchStatus.UNCHANGED: 2, MatchStatus.ADDED: 1}
    assert not any(x.same_position for x in m if x.status == MatchStatus.UNCHANGED)
    _assert_one_to_one(old, new, m)


def test_small_edit_is_edited_and_rewrite_is_removed_plus_added(tmp_path):
    old = _doc(tmp_path, "a.md", f"## S\n\n{LOREM_A}\n\n{LOREM_B}\n")
    edited = LOREM_A.replace("lazy", "sleepy")
    new = _doc(tmp_path, "b.md", f"## S\n\n{edited}\n\n{LOREM_C}\n")
    m = diff_versions(old, new, CFG.model_copy(update={"edit_similarity_threshold": 0.8}), NORM)
    assert _by_status(m) == {MatchStatus.EDITED: 1, MatchStatus.REMOVED: 1, MatchStatus.ADDED: 1}
    (e,) = [x for x in m if x.status == MatchStatus.EDITED]
    assert e.new.block.text == edited and 0.8 <= e.similarity < 1.0


def test_cross_section_edits_need_pass_2b(tmp_path):
    old = _doc(tmp_path, "a.md", f"## S1\n\n{LOREM_A}\n\n## S2\n\n{LOREM_B}\n")
    new = _doc(tmp_path, "b.md", f"## S1\n\n{LOREM_B}\n\n## S2\n\n{LOREM_A} Extra.\n")
    # LOREM_B moved section unchanged -> pass 1; LOREM_A edited AND in another section.
    off = diff_versions(old, new, CFG.model_copy(update={"cross_section_edit_threshold": None}),
                        NORM)
    assert _by_status(off)[MatchStatus.EDITED] == 0
    on = diff_versions(old, new, CFG.model_copy(update={"cross_section_edit_threshold": 0.8}),
                       NORM)
    (e,) = [x for x in on if x.status == MatchStatus.EDITED]
    assert e.old.block.text == LOREM_A and not e.same_position


def test_pass_2b_does_not_pair_unrelated_text(tmp_path):
    old = _doc(tmp_path, "a.md", f"## S1\n\n{LOREM_A}\n")
    new = _doc(tmp_path, "b.md", f"## S2\n\n{LOREM_C}\n")
    m = diff_versions(old, new, CFG.model_copy(update={"cross_section_edit_threshold": 0.8}),
                      NORM)
    assert _by_status(m) == {MatchStatus.REMOVED: 1, MatchStatus.ADDED: 1}


def test_duplicate_paragraphs_pair_in_order(tmp_path):
    old = _doc(tmp_path, "a.md", f"## S\n\n{LOREM_A}\n\n{LOREM_B}\n\n{LOREM_A}\n")
    new = _doc(tmp_path, "b.md", f"## S\n\n{LOREM_A}\n\n{LOREM_B}\n\n{LOREM_A}\n")
    m = diff_versions(old, new, CFG, NORM)
    assert all(x.status == MatchStatus.UNCHANGED and x.same_position for x in m)


def test_renamed_section_alignment_can_be_switched_off(tmp_path):
    body_old = f"## Old Name\n\n{LOREM_A}\n\n{LOREM_B}\n"
    body_new = f"## New Name\n\n{LOREM_A}\n\n{LOREM_B} Changed a little.\n"
    old, new = _doc(tmp_path, "a.md", body_old), _doc(tmp_path, "b.md", body_new)
    only_2 = CFG.model_copy(update={"cross_section_edit_threshold": None})
    on = diff_versions(old, new, only_2, NORM)
    off = diff_versions(old, new, only_2.model_copy(update={"align_renamed_sections": False}),
                        NORM)
    assert _by_status(on)[MatchStatus.EDITED] == 1
    assert _by_status(off)[MatchStatus.EDITED] == 0


def test_block_moved_to_another_document_in_same_event(tmp_path):
    old_a = _doc(tmp_path, "a1.md", f"## S\n\n{LOREM_A}\n\n{LOREM_B}\n", "doc-a")
    new_a = _doc(tmp_path, "a2.md", f"## S\n\n{LOREM_A}\n", "doc-a")
    new_b = _doc(tmp_path, "b2.md", f"## Moved here\n\n{LOREM_B}\n", "doc-b")
    res = diff_event({"doc-a": old_a}, [new_a, new_b], CFG, NORM)
    by_doc = {d.doc_key: _by_status(d.matches) for d in res}
    assert by_doc["doc-a"] == {MatchStatus.UNCHANGED: 1}
    assert by_doc["doc-b"] == {MatchStatus.MOVED: 1}


def test_different_documents_are_rejected(tmp_path):
    a = _doc(tmp_path, "a.md", f"{LOREM_A}\n", "doc-a")
    b = _doc(tmp_path, "b.md", f"{LOREM_A}\n", "doc-b")
    with pytest.raises(ValueError):
        diff_versions(a, b, CFG, NORM)


# ------------------------------------------------------------- real events


@pytest.fixture(scope="module")
def events(need_uploads):
    olds = {d.document.doc_key: d for d in parse_corpus(INITIAL, L0, T0)}
    return {
        ev: diff_event(olds, parse_corpus(UPLOADS / ev, L0, T0), CFG, NORM)
        for ev in ("event1", "event2", "event3")
    }


def test_every_block_is_used_exactly_once(events):
    for results in events.values():
        olds = [m.old.block.block_uid for d in results for m in d.matches if m.old]
        news = [m.new.block.block_uid for d in results for m in d.matches if m.new]
        assert len(olds) == len(set(olds))
        assert sorted(news) == sorted(pb.block.block_uid for d in results for pb in d.new.blocks)
        expected_old = [pb.block.block_uid for d in results if d.old for pb in d.old.blocks]
        assert sorted(olds) == sorted(expected_old)


def _find(results, doc_key, path_suffix):
    (d,) = [d for d in results if d.doc_key == doc_key]
    return [m for m in d.matches
            if m.old and m.old.block.block_id.split("::")[1].endswith(path_suffix)]


def test_e1_sabbatical_is_edited(events):
    (m,) = _find(events["event1"], "en-benefits-and-perks", "Sabbatical")
    assert m.status == MatchStatus.EDITED
    assert "30-day paid sabbatical" in m.old.block.text
    assert "6-week paid sabbatical" in m.new.block.text


def test_e1_vacation_paragraph_moved_into_paid_time_off(events):
    (m,) = _find(events["event1"], "en-benefits-and-perks", "Paid Time Off > Vacation Time")
    assert m.status == MatchStatus.EDITED
    assert m.new.block.block_id.split("::")[1] == "Paid Time Off"
    assert m.similarity >= 0.8


def test_e3_renamed_heading_is_followed(events):
    ms = _find(events["event2"], "en-making-a-career", "Your First 90 Days")
    assert ms and all(m.new is not None for m in ms)
    assert all(m.new.block.block_id.split("::")[1] == "Your First Year" for m in ms)


def test_t1_section_34_is_edited(events):
    (m,) = _find(events["event3"], "th-labour-protection-act-2541", "มาตรา 34")
    assert m.status == MatchStatus.EDITED
    assert "สามวันทำงาน" in m.new.block.text


def test_agreement_summary_counts_labels():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
    from diff_agreement import summarize

    base = {"event": "e1", "similarity": "0.6", "closest_other_similarity": ""}
    rows = [
        {**base, "row_id": "1", "status": "edited", "verdict": "correct"},
        {**base, "row_id": "2", "status": "edited", "verdict": "Wrong "},
        {**base, "row_id": "3", "status": "edited", "verdict": ""},
        {**base, "row_id": "4", "status": "added", "verdict": "maybe"},
    ]
    s = summarize(rows)
    assert s["groups"][("e1", "edited")] == {"rows": 3, "labelled": 2, "correct": 1}
    assert s["invalid"] == ["4"]
    assert s["wrong_scores"] == [("2", "edited", "0.6")]


FN_OLD = "[1] มาตรา 146 แก้ไขเพิ่มเติมโดยพระราชบัญญัติคุ้มครองแรงงาน (ฉบับที่ 4) พ.ศ. 2553"
FN_NEW = "[2] มาตรา 146 แก้ไขเพิ่มเติมโดยพระราชบัญญัติคุ้มครองแรงงาน (ฉบับที่ 7) พ.ศ. 2562"
FN_SAME = "[3] มาตรา 5 แก้ไขเพิ่มเติมโดยพระราชบัญญัติคุ้มครองแรงงาน (ฉบับที่ 2) พ.ศ. 2551"


def test_footnote_role_blocks_are_matched_by_exact_text_only(tmp_path):
    old = _doc(tmp_path, "a.md", f"## เชิงอรรถ\n\n{FN_OLD}\n\n{FN_SAME}\n")
    new = _doc(tmp_path, "b.md", f"## เชิงอรรถ\n\n{FN_NEW}\n\n{FN_SAME}\n")
    exact = diff_versions(old, new, CFG, NORM)
    assert _by_status(exact) == {MatchStatus.UNCHANGED: 1, MatchStatus.REMOVED: 1,
                                 MatchStatus.ADDED: 1}


def test_same_text_under_a_body_heading_is_paired_as_edit(tmp_path):
    # The rule follows the block role, not the text: as body text the two
    # template entries do pair up as an "edit".
    old = _doc(tmp_path, "a.md", f"## Notes\n\n{FN_OLD}\n\n{FN_SAME}\n")
    new = _doc(tmp_path, "b.md", f"## Notes\n\n{FN_NEW}\n\n{FN_SAME}\n")
    assert _by_status(diff_versions(old, new, CFG, NORM))[MatchStatus.EDITED] == 1


def test_move_threshold_is_separate_from_edit_threshold(tmp_path):
    moved = LOREM_B.replace("quarterly", "yearly").replace("spreadsheets", "reports")
    old_a = _doc(tmp_path, "a1.md", f"## S\n\n{LOREM_A}\n\n{LOREM_B}\n", "doc-a")
    new_a = _doc(tmp_path, "a2.md", f"## S\n\n{LOREM_A}\n", "doc-a")
    new_b = _doc(tmp_path, "b2.md", f"## T\n\n{moved}\n", "doc-b")

    def statuses(edit, move):
        cfg = CFG.model_copy(update={"edit_similarity_threshold": edit,
                                     "move_similarity_threshold": move})
        res = diff_event({"doc-a": old_a}, [new_a, new_b], cfg, NORM)
        return {d.doc_key: _by_status(d.matches) for d in res}

    # A strict edit threshold no longer blocks a move ...
    assert statuses(edit=0.99, move=0.5)["doc-b"] == {MatchStatus.MOVED: 1}
    # ... and a strict move threshold blocks it whatever the edit threshold is.
    assert statuses(edit=0.1, move=0.99)["doc-b"] == {MatchStatus.ADDED: 1}


def test_no_footnote_entry_is_paired_by_similarity(events):
    for results in events.values():
        for d in results:
            for m in d.matches:
                roles = {pb.block.role.value for pb in (m.old, m.new) if pb is not None}
                if "footnote" in roles:
                    assert m.status in (MatchStatus.UNCHANGED, MatchStatus.REMOVED,
                                        MatchStatus.ADDED)


def test_agreement_excludes_exact_only_rows():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
    from diff_agreement import summarize

    base = {"event": "e3", "status": "added", "similarity": "", "closest_other_similarity": "",
            "old_block_id": "", "verdict": "wrong"}
    rows = [
        {**base, "row_id": "1", "new_block_id": "th-x::เชิงอรรถ::b3"},
        {**base, "row_id": "2", "new_block_id": "th-x::หมวด 1 > มาตรา 5::b0"},
    ]
    s = summarize(rows, ["เชิงอรรถ"])  # old sheet: no role column, heading fallback
    assert s["excluded"] == 1
    assert s["total"] == {"rows": 1, "labelled": 1, "correct": 0}
    # New sheets carry a role column, which wins over the heading fallback.
    with_role = [{**rows[0], "role": "body"}, {**rows[1], "role": "footnote"}]
    s = summarize(with_role, ["เชิงอรรถ"])
    assert s["excluded"] == 1 and s["wrong_scores"][0][0] == "1"
