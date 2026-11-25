"""Layer 0 and diff tests on the committed fixtures (tests/fixtures/).

Unlike the pilot-data tests, these always run, including on a fresh clone.
"""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from kg.config import load_config
from kg.diff import MatchStatus, diff_event, diff_versions
from kg.layer0_structure import Normalizer, parse_file
from kg.models import BlockKind, BlockRole

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
CFG = load_config(ROOT / "config.yaml")
NORM = Normalizer(CFG.layer0)
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)

TH_OLD, TH_NEW = FIX / "th_lpa_old.md", FIX / "th_lpa_new.md"
TH_ARABIC = FIX / "th_inspection_arabic_digits.md"
EN_OLD, EN_NEW, EN_SEV = FIX / "en_policy_old.md", FIX / "en_policy_new.md", FIX / "en_severance_new.md"
ALL = sorted(FIX.glob("*.md"))
ALL = [p for p in ALL if p.name != "README.md"]


def parse(p):
    return parse_file(p, CFG.layer0, T0)


def path_of(block_id: str) -> str:
    return block_id.split("::")[1]


# ------------------------------------------------------------- the fixtures themselves


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_fixture_license_allows_committing(path):
    text = path.read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---")[1])
    assert "CC0" in meta["license"] or "Synthetic" in meta["license"]
    assert meta["doc_key"].startswith("fixture-")


# ------------------------------------------------------------- layer 0


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_line_ranges_read_back_exact_text(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    doc = parse(path)
    assert doc.blocks
    for pb in doc.blocks:
        b = pb.block
        assert "\n".join(lines[b.lines.start - 1 : b.lines.end]) == b.text
    ids = [pb.block.block_id for pb in doc.blocks]
    assert len(ids) == len(set(ids))


def test_parse_twice_is_identical():
    def snap():
        return [(pb.block.block_uid, pb.block.lines, pb.section_id) for pb in parse(TH_NEW).blocks]

    assert snap() == snap()


def test_thai_heading_paths():
    paths = {path_of(pb.block.block_id) for pb in parse(TH_OLD).blocks}
    assert "หมวด 1 บททั่วไป > มาตรา 11/1" in paths  # Thai digits -> Arabic, "/" kept
    assert "หมวด 2 การใช้แรงงานทั่วไป > มาตรา 34" in paths
    assert not any("พระราชบัญญัติ" in p for p in paths)  # single # title left out


def test_arabic_digit_file_uses_the_same_path_style():
    assert [path_of(pb.block.block_id) for pb in parse(TH_ARABIC).blocks] == ["ข้อ 1", "ข้อ 2"]


def test_footnote_marker_kept_aside_and_not_hashed():
    (b,) = [pb.block for pb in parse(TH_NEW).blocks if path_of(pb.block.block_id).endswith("มาตรา 34")]
    assert b.footnotes == ("[๑๖]",)
    assert b.content_hash == NORM.content_hash(b.text.replace("[๑๖]", ""))


def test_footnote_entries_get_footnote_role():
    roles = Counter((path_of(pb.block.block_id) == "เชิงอรรถ", pb.block.role)
                    for pb in parse(TH_NEW).blocks)
    assert roles[(True, BlockRole.FOOTNOTE)] == 4
    assert roles[(True, BlockRole.BODY)] == 0 and roles[(False, BlockRole.FOOTNOTE)] == 0


def test_long_list_is_split_into_items_and_can_stay_whole():
    def kinds(cfg):
        return [pb.block.kind for pb in parse_file(TH_OLD, cfg, T0).blocks
                if path_of(pb.block.block_id).endswith("มาตรา 118")]

    assert kinds(CFG.layer0) == [BlockKind.PARAGRAPH] + [BlockKind.LIST_ITEM] * 5
    whole = CFG.layer0.model_copy(update={"split_list_over_chars": None})
    assert kinds(whole) == [BlockKind.PARAGRAPH, BlockKind.LIST]


# ------------------------------------------------------------- diff, Thai excerpt


@pytest.fixture(scope="module")
def th_diff():
    return diff_versions(parse(TH_OLD), parse(TH_NEW), CFG.diff, NORM)


def test_thai_one_to_one(th_diff):
    old, new = parse(TH_OLD), parse(TH_NEW)
    assert sorted(m.old.block.block_uid for m in th_diff if m.old) == \
           sorted(pb.block.block_uid for pb in old.blocks)
    assert sorted(m.new.block.block_uid for m in th_diff if m.new) == \
           sorted(pb.block.block_uid for pb in new.blocks)


def test_thai_unchanged_sections(th_diff):
    unchanged = {path_of(m.old.block.block_id) + "::" + m.old.block.block_id.split("::")[2]
                 for m in th_diff if m.status == MatchStatus.UNCHANGED}
    for p in ["หมวด 1 บททั่วไป > มาตรา 11/1::b0", "หมวด 2 การใช้แรงงานทั่วไป > มาตรา 35::b0",
              "หมวด 11 ค่าชดเชย > มาตรา 118::b0", "หมวด 11 ค่าชดเชย > มาตรา 118::b4"]:
        assert p in unchanged


def test_thai_section_34_is_edited(th_diff):
    (m,) = [m for m in th_diff if m.old and path_of(m.old.block.block_id).endswith("มาตรา 34")]
    assert m.status == MatchStatus.EDITED and m.same_position
    assert "ตามข้อบังคับเกี่ยวกับการทำงาน" in m.old.block.text
    assert "สามวันทำงาน" in m.new.block.text


def test_thai_new_footnote_entries_are_added_not_paired(th_diff):
    fn = [m for m in th_diff if any(pb is not None and pb.block.role == BlockRole.FOOTNOTE
                                    for pb in (m.old, m.new))]
    assert Counter(m.status for m in fn) == {MatchStatus.UNCHANGED: 1, MatchStatus.ADDED: 3}


# ------------------------------------------------------------- diff, synthetic English


@pytest.fixture(scope="module")
def en_results():
    old = parse(EN_OLD)
    res = diff_event({old.document.doc_key: old}, [parse(EN_NEW), parse(EN_SEV)], CFG.diff, NORM)
    return {d.doc_key: d.matches for d in res}


def _pairs(matches):
    return {(m.status, path_of(m.old.block.block_id) if m.old else None,
             path_of(m.new.block.block_id) if m.new else None) for m in matches}


def test_english_changes_are_labelled_as_written(en_results):
    U, E, A, M = (MatchStatus.UNCHANGED, MatchStatus.EDITED, MatchStatus.ADDED,
                  MatchStatus.MOVED)
    assert _pairs(en_results["fixture-en-leave-policy"]) == {
        (U, "Paid Time Off > Sick Days", "Paid Time Off > Sick Days"),  # shifted by an insert
        (A, None, "Paid Time Off > Sick Days"),                         # the inserted paragraph
        (U, "Your First Month", "Your First Quarter"),                  # heading renamed
        (E, "Your First Month", "Your First Quarter"),                  # month -> quarter
        (E, "Paid Time Off > Vacation", "Paid Time Off"),               # moved section + edited
        (E, "Sabbatical", "Sabbatical"),                                # 30-day -> 6-week
    }
    assert _pairs(en_results["fixture-en-severance"]) == {
        (M, "Leaving the Company", "_"),                                # moved to a new document
    }


def test_english_shifted_unchanged_blocks_keep_text_but_not_position(en_results):
    shifted = [m for m in en_results["fixture-en-leave-policy"]
               if m.status == MatchStatus.UNCHANGED and not m.same_position]
    assert len(shifted) == 3  # two Sick Days paragraphs + the renamed-heading paragraph
    assert all(m.old.block.content_hash == m.new.block.content_hash for m in shifted)


def test_english_sabbatical_fact_change(en_results):
    (m,) = [m for m in en_results["fixture-en-leave-policy"]
            if m.old and path_of(m.old.block.block_id) == "Sabbatical"]
    assert "30-day" in m.old.block.text and "6-week" in m.new.block.text
