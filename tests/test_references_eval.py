"""Reading the person's REFERENCES labels and scoring them (no files, no database)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from make_references_sheet import EN_CUES, TH_CUES  # noqa: E402,F401
from references_agreement import parse_citations, score  # noqa: E402

from kg.layer1_references import Registry, RegistryEntry  # noqa: E402

REG = Registry([
    RegistryEntry("th-act", "พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541 (ฉบับ Update ล่าสุด)", "th"),
    RegistryEntry("th-reg", "ระเบียบทดสอบ", "th"),
    RegistryEntry("en-career", "Making a Career", "en", ("making-a-career.md",)),
])


def test_parse_items_self_and_external_names():
    got = parse_citations(
        "th-act | มาตรา ๑๑๘ (๖); self | ข้อ 3; ext: ประมวลกฎหมายอาญา |", "th-reg", REG)
    assert got == {("th-act", "มาตรา118(6)"), ("th-reg", "ข้อ3"), ("ext-ประมวลกฎหมายอาญา", "")}


def test_external_name_of_a_law_in_the_store_maps_to_it():
    got = parse_citations("ext: พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑ | มาตรา 6", "th-reg", REG)
    assert got == {("th-act", "มาตรา6")}


def test_links_map_like_layer1():
    got = parse_citations(
        "ext: https://github.com/x/handbook/blob/master/making-a-career.md | #your-first-90-days;"
        " ext: https://github.com/x/handbook/blob/master/titles-for-ops.md |", "en-x", REG)
    assert ("en-career", "#your-first-90-days") in got
    assert ("ext-handbook-titles-for-ops.md", "") in got


def test_none_blank_and_unknown():
    assert parse_citations("none", "th-reg", REG) == set()
    assert parse_citations("  ", "th-reg", REG) is None
    with pytest.raises(ValueError):
        parse_citations("th-typo | มาตรา 1", "th-reg", REG)


def test_score_exact_and_document_level():
    key = {"rows": {
        "R1": {"doc_key": "th-reg", "block_uid": "u1", "language": "th", "stratum": "th_cue"},
        "R2": {"doc_key": "th-reg", "block_uid": "u2", "language": "th", "stratum": "th_cue"},
        "R3": {"doc_key": "th-reg", "block_uid": "u3", "language": "th", "stratum": "th_no_cue"},
    }}
    system = {
        "u1": [("th-act", "มาตรา 6", "explicit"), ("th-act", "มาตรา 7", "same_block_context")],
        "u2": [("th-act", "มาตรา 22", "issued_under")],
    }
    rows = [{"row_id": "R1", "citations": "th-act | มาตรา ๖"},
            {"row_id": "R2", "citations": "th-act | มาตรา 23"},   # right document, wrong section
            {"row_id": "R3", "citations": ""}]                    # not labelled
    s = score(rows, key, REG, system)
    c = s["groups"]["all"]
    assert (c["blocks"], c["tp"], c["fp"], c["fn"]) == (2, 1, 2, 1)
    assert (c["doc_tp"], c["doc_fp"], c["doc_fn"]) == (2, 0, 0)
    assert s["unlabelled"] == 1
    assert s["by_resolution"]["explicit"] == {"tp": 1, "fp": 0}
    assert s["by_resolution"]["issued_under"] == {"tp": 0, "fp": 1}


def test_unreadable_row_is_reported_not_scored():
    key = {"rows": {"R1": {"doc_key": "th-reg", "block_uid": "u1", "language": "th",
                           "stratum": "th_cue"}}}
    s = score([{"row_id": "R1", "citations": "nobody | x"}], key, REG, {})
    assert s["errors"] and "all" not in s["groups"]
