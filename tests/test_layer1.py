"""Layer 1 REFERENCES: one rule per test, on short synthetic blocks (no database)."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kg.config import load_config
from kg.layer0_structure import parse_file
from kg.layer1_references import (
    Registry,
    RegistryEntry,
    ReferenceExtractor,
    compact,
    law_name_from_title,
    slug,
)

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)

ACT = RegistryEntry("th-act", "พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541 (ฉบับ Update ล่าสุด)", "th")
AMEND = RegistryEntry("th-amend7", "พระราชบัญญัติคุ้มครองแรงงาน (ฉบับที่ 7) พ.ศ. 2562", "th")
REG = RegistryEntry("th-reg", "กฎกระทรวง ฉบับที่ 9 (พ.ศ. 2541) ออกตามความในพระราชบัญญัติคุ้มครองแรงงาน "
                    "พ.ศ. 2541", "th")
CAREER = RegistryEntry("en-career", "Making a Career", "en", ("making-a-career.md",))
GUIDE = RegistryEntry("en-guide", "Getting Started", "en", ("getting-started.md",))
REGISTRY = Registry([ACT, AMEND, REG, CAREER, GUIDE])
EXTRACTOR = ReferenceExtractor(REGISTRY, CFG.layer1)


def refs(tmp_path, entry: RegistryEntry, body: str, heading: str = "## S"):
    f = tmp_path / "d.md"
    f.write_text(f"---\ndoc_key: {entry.doc_key}\ntitle: \"{entry.title}\"\nlanguage: "
                 f"{entry.language}\n---\n# {entry.title}\n\n{heading}\n\n{body}\n",
                 encoding="utf-8")
    out = EXTRACTOR.extract(parse_file(f, CFG.layer0, T0, doc_key=entry.doc_key))
    return out, {(r.target, r.cited_section, r.resolution) for r in out.references}


# ------------------------------------------------------------- helpers


def test_compact_removes_spaces_and_unifies_digits():
    c, idx = compact("มาตรา ๑๑๘ (๖)")
    assert c == "มาตรา118(6)" and len(idx) == len(c)


def test_law_name_from_title_drops_update_note():
    assert law_name_from_title(ACT.title) == "พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541"


def test_slug_keeps_thai_vowel_marks():
    assert slug("พระราชบัญญัติคุ้มครองแรงงาน") == "พระราชบัญญัติคุ้มครองแรงงาน"


# ------------------------------------------------------------- Thai rules


def test_law_named_after_the_section(tmp_path):
    _, r = refs(tmp_path, REG, "อาศัยอำนาจตามความในมาตรา ๖ แห่งพระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑")
    assert ("th-act", "มาตรา 6", "explicit") in r


def test_law_named_before_the_section(tmp_path):
    _, r = refs(tmp_path, REG, "พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑ มาตรา ๑๕๙ บัญญัติให้")
    assert ("th-act", "มาตรา 159", "explicit") in r


def test_spacing_and_arabic_digits_do_not_matter(tmp_path):
    _, r = refs(tmp_path, REG, "ตามมาตรา 139 (3) แห่งพระราชบัญญัติ คุ้มครองแรงงาน พ.ศ. 2541")
    assert ("th-act", "มาตรา 139 (3)", "explicit") in r


def test_a_list_of_sections_gives_one_edge_each(tmp_path):
    _, r = refs(tmp_path, REG, "มาตรา ๗๐ มาตรา ๗๕ หรือมาตรา ๗๖ แห่งพระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑")
    assert {s for t, s, _ in r if t == "th-act"} >= {"มาตรา 70", "มาตรา 75", "มาตรา 76"}


def test_bare_section_uses_the_law_named_earlier_in_the_block(tmp_path):
    _, r = refs(tmp_path, REG, "พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑ กำหนดโทษไว้ และผู้ฝ่าฝืน"
                               "ต้องระวางโทษตามมาตรา ๑๔๔")
    assert ("th-act", "มาตรา 144", "same_block_context") in r


def test_bare_section_inside_an_act_is_a_self_reference(tmp_path):
    out, r = refs(tmp_path, ACT, "ให้นายจ้างจ่ายค่าชดเชยตามมาตรา ๑๑๘")
    assert ("th-act", "มาตรา 118", "self_document") in r
    assert all(x.self_reference for x in out.references)


def test_bare_section_inside_a_regulation_goes_to_the_act_it_is_issued_under(tmp_path):
    _, r = refs(tmp_path, REG, "ลูกจ้างมีสิทธิตามมาตรา ๓๔")
    assert ("th-act", "มาตรา 34", "issued_under") in r


def test_this_regulation_is_never_the_target_of_a_section(tmp_path):
    _, r = refs(tmp_path, REG, "ตามกฎกระทรวงนี้ ให้นายจ้างปฏิบัติตามมาตรา ๒๒")
    assert ("th-act", "มาตรา 22", "issued_under") in r
    assert not any(t == "th-reg" and s.startswith("มาตรา") for t, s, _ in r)


def test_clause_in_a_regulation_is_a_self_reference(tmp_path):
    _, r = refs(tmp_path, REG, "ให้นำความในข้อ ๓ มาใช้บังคับ")
    assert ("th-reg", "ข้อ 3", "self_document") in r


def test_law_not_in_the_store_gets_one_stub(tmp_path):
    out, r = refs(tmp_path, REG,
                  "พระราชบัญญัติความปลอดภัย อาชีวอนามัย และสภาพแวดล้อมในการทำงาน พ.ศ. ๒๕๕๔ มาตรา ๗๑ "
                  "และพระราชบัญญัติความปลอดภัย อาชีวอนามัยและสภาพแวดล้อมในการทำงาน พ.ศ. 2554 มาตรา ๗๒")
    assert len(out.stubs) == 1  # spacing and digit style do not split it
    (key,) = out.stubs
    assert {("มาตรา 71"), ("มาตรา 72")} <= {s for t, s, _ in r if t == key}


def test_law_named_without_section_is_a_document_level_reference(tmp_path):
    _, r = refs(tmp_path, REG, "ทั้งนี้ ให้เป็นไปตามพระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑")
    assert ("th-act", "", "explicit") in r


def test_name_without_year_picks_the_principal_act_not_the_amendment(tmp_path):
    _, r = refs(tmp_path, REG, "ทั้งนี้ ตามที่พระราชบัญญัติคุ้มครองแรงงานกำหนด")
    assert ("th-act", "", "name_without_year") in r
    assert not any(t == "th-amend7" for t, _, _ in r)


def test_footnote_entries_are_skipped(tmp_path):
    out, _ = refs(tmp_path, ACT, "[๑] มาตรา ๓๔ แก้ไขเพิ่มเติมโดยพระราชบัญญัติคุ้มครองแรงงาน (ฉบับที่ ๗) "
                                 "พ.ศ. ๒๕๖๒", heading="## เชิงอรรถ")
    assert out.references == []


def test_evidence_quotes_the_original_text(tmp_path):
    out, _ = refs(tmp_path, REG, "อาศัยอำนาจตามความในมาตรา ๖ แห่งพระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑")
    (ref,) = [x for x in out.references if x.cited_section == "มาตรา 6"]
    assert ref.evidence_span == "มาตรา ๖ แห่งพระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑"


# ------------------------------------------------------------- English rules


def test_link_to_a_known_handbook_file_with_anchor(tmp_path):
    _, r = refs(tmp_path, GUIDE, "Read the [expectations](https://github.com/x/handbook/blob/"
                                 "master/making-a-career.md#your-first-90-days) first.")
    assert ("en-career", "#your-first-90-days", "link") in r


def test_link_to_an_unknown_file_or_site_gets_a_stub(tmp_path):
    out, r = refs(tmp_path, GUIDE, "See [titles](https://github.com/x/handbook/blob/master/"
                                   "titles-for-ops.md) and [the app](https://example.com/a#b).")
    assert len(out.stubs) == 2 and all(k.startswith("ext-") for k in out.stubs)
    assert all(s == "" for t, s, _ in r)  # no anchor kept for a site link


def test_link_to_an_anchor_on_the_same_page_is_a_self_reference(tmp_path):
    out, r = refs(tmp_path, GUIDE, "Jump to [below](#more-help).")
    assert ("en-guide", "#more-help", "link") in r and out.references[0].self_reference


def test_exact_title_of_another_page_is_a_document_level_reference(tmp_path):
    _, r = refs(tmp_path, GUIDE, "The Making a Career page explains titles.")
    assert ("en-career", "", "title_mention") in r


def test_same_reference_twice_in_a_block_is_one_edge(tmp_path):
    out, _ = refs(tmp_path, ACT, "ตามมาตรา ๑๑๘ และตามมาตรา ๑๑๘ อีกครั้ง")
    assert [x.cited_section for x in out.references] == ["มาตรา 118"]


@pytest.mark.parametrize("text", ["มาตรการความปลอดภัย", "มาตรฐานฝีมือ", "ข้อความในสัญญา"])
def test_words_that_start_like_keywords_are_not_citations(tmp_path, text):
    out, _ = refs(tmp_path, REG, text)
    assert out.references == []


# ------------------------------------------------------------- fixes after the dev labels (L1-v2)


def test_paragraph_does_not_hide_the_law_after_the_section(tmp_path):
    _, r = refs(tmp_path, REG, "ตามมาตรา ๑๕๙ วรรคสาม แห่งพระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑ "
                               "หรือมาตรา ๔๙ วรรคสาม แห่งพระราชบัญญัติอื่น พ.ศ. ๒๕๕๓")
    assert ("th-act", "มาตรา 159", "explicit") in r
    (other,) = {t for t, s, _ in r if s == "มาตรา 49"}
    assert other.startswith("ext-") and other != "th-act"


def test_in_a_list_each_section_takes_the_law_right_before_it(tmp_path):
    _, r = refs(tmp_path, REG, "พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑ มาตรา ๑๕๙ "
                               "พระราชบัญญัติอื่น พ.ศ. ๒๕๕๓ มาตรา ๔๙")
    assert ("th-act", "มาตรา 159", "explicit") in r
    assert {t for t, s, _ in r if s == "มาตรา 49"} != {"th-act"}


def test_clause_of_another_regulation_named_without_year(tmp_path):
    out, r = refs(tmp_path, REG, "ให้เป็นไปตามข้อ ๔ ของกฎกระทรวงคุ้มครองแรงงานในงานเกษตรกรรม")
    (key,) = [k for k in out.stubs]
    assert key.startswith("ext-กฎกระทรวงคุ้มครองแรงงานในงานเกษตรกรรม")
    assert (key, "ข้อ 4", "name_without_year") in r


def test_a_clause_never_points_to_an_act(tmp_path):
    _, r = refs(tmp_path, REG, "พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. ๒๕๔๑ กำหนดไว้ และให้ปฏิบัติตามข้อ ๓")
    assert ("th-reg", "ข้อ 3", "self_document") in r
    assert not any(t == "th-act" and s.startswith("ข้อ") for t, s, _ in r)


def test_regulation_title_with_year_is_a_document_reference(tmp_path):
    out, r = refs(tmp_path, ACT, "ระเบียบกระทรวงแรงงานว่าด้วยการตรวจ (ฉบับที่ ๒) พ.ศ. ๒๕๖๐")
    (key,) = out.stubs
    assert (key, "", "explicit") in r and key.endswith("พ.ศ.2560")


def test_plain_word_regulation_with_a_date_is_not_a_title(tmp_path):
    out, r = refs(tmp_path, ACT, "ตามระเบียบที่อธิบดีกำหนด เมื่อวันที่ ๑ มกราคม พ.ศ. ๒๕๖๐")
    assert out.stubs == {} and r == set()


def test_short_title_of_a_regulation_in_the_store(tmp_path):
    _, r = refs(tmp_path, ACT, "ตามกฎกระทรวง ฉบับที่ ๙ (พ.ศ. ๒๕๔๑) ข้อ ๒")
    assert ("th-reg", "ข้อ 2", "explicit") in r


def test_law_named_by_subject(tmp_path):
    _, r = refs(tmp_path, REG, "ทั้งนี้ ตามกฎหมายว่าด้วยการคุ้มครองแรงงาน")
    assert ("th-act", "", "subject_name") in r


def test_unknown_subject_gives_no_edge(tmp_path):
    out, r = refs(tmp_path, REG, "ทั้งนี้ ตามกฎหมายว่าด้วยการประมง")
    assert r == set() and out.stubs == {}


def test_chapter_is_a_cited_section(tmp_path):
    _, r = refs(tmp_path, REG, "ให้ดำเนินการตามหมวด ๒")
    assert ("th-reg", "หมวด 2", "self_document") in r


def test_subject_goes_to_the_registry_act_not_an_amending_act_stub(tmp_path):
    # The amending act (ฉบับที่ 2) is named first and becomes a stub with the same
    # subject as the act; "กฎหมายว่าด้วยการคุ้มครองแรงงาน" must still mean the act.
    _, r = refs(tmp_path, REG, "แก้ไขโดยพระราชบัญญัติคุ้มครองแรงงาน (ฉบับที่ ๒) พ.ศ. ๒๕๕๑ "
                               "ทั้งนี้ ตามกฎหมายว่าด้วยการคุ้มครองแรงงาน")
    assert ("th-act", "", "subject_name") in r


def test_extraction_does_not_depend_on_hash_seed():
    import subprocess

    code = ("import sys; sys.path.insert(0, 'eval');"
            "from references_agreement import registry_from_corpus, system_references;"
            "print(sorted((u, d, s, r) for u, i in system_references(registry_from_corpus()).items()"
            " for d, s, r in i))")
    if not (ROOT / "data" / "initial_corpus").exists():
        pytest.skip("data/initial_corpus not present")
    outs = {subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                           env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8"},
                           check=True).stdout for seed in ("1", "2", "3")}
    assert len(outs) == 1
