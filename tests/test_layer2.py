"""Layer 2 entity registry and MENTIONS (no LLM, no database)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from kg.config import load_config
from kg.layer0_structure import parse_file
from kg.layer2_entities import (
    EntityMatcher,
    EntityRegistry,
    block_share,
    body_block_counts,
    build_registry,
    english_heading_entities,
    flag_hubs,
    load_manual,
    thai_definitions,
    thai_heading_terms,
    thai_title_subjects,
    thai_type,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
CFG = load_config(ROOT / "config.yaml")
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_definitions_from_thai_text():
    text = ("ในพระราชบัญญัตินี้ นายจ้าง[๒] หมายความว่า ผู้ซึ่งตกลงรับลูกจ้างเข้าทำงาน "
            "ค่าชดเชย หมายความว่า เงินที่นายจ้างจ่ายให้แก่ลูกจ้างเมื่อเลิกจ้าง "
            "อัตราค่าจ้างขั้นต่ำพื้นฐาน[๔] (ยกเลิก) "
            "อธิบดี หมายความว่า อธิบดีกรมสวัสดิการและคุ้มครองแรงงาน "
            "พ.ศ. ๒๕๔๑ หมายความว่า พระราชบัญญัติคุ้มครองแรงงาน")
    assert thai_definitions(text) == [("นายจ้าง", "Role"), ("ค่าชดเชย", "Concept"),
                                      ("อธิบดี", "Role")]  # repealed term and year skipped


def test_definition_inside_a_section_drops_its_scope_words():
    doc = parse_file(FIX / "th_lpa_old.md", CFG.layer0, T0)
    reg = build_registry([doc])
    assert reg.get("th", "การเลิกจ้าง").entity_type == "Concept"
    assert reg.get("th", "การเลิกจ้างตามมาตรานี้") is None  # scope words are not a name


def test_types_by_rule():
    assert thai_type("คณะกรรมการค่าจ้าง") == "Body"
    assert thai_type("กองทุนสงเคราะห์ลูกจ้าง") == "Body"
    assert thai_type("ทะเบียนลูกจ้าง") == "Artifact"
    assert thai_type("พนักงานตรวจแรงงาน") == "Role"
    assert thai_type("นิติกร", "ข้าราชการพลเรือน") == "Role"
    assert thai_type("ค่าล่วงเวลา") == "Concept"


def test_heading_lists_and_titles():
    assert thai_heading_terms("หมวด 5 ค่าจ้าง ค่าล่วงเวลา และค่าทำงานในวันหยุด") == [
        "ค่าจ้าง", "ค่าล่วงเวลา", "ค่าทำงานในวันหยุด"]
    assert thai_heading_terms("หมวด 12 การยื่นคำร้องและการพิจารณาคำร้อง") == [
        "การยื่นคำร้อง", "การพิจารณาคำร้อง"]
    assert thai_heading_terms("หมวด 1 บททั่วไป") == []
    assert thai_heading_terms("มาตรา 34") == []
    assert thai_title_subjects(
        "ระเบียบกรมสวัสดิการและคุ้มครองแรงงานว่าด้วยการดำเนินคดีอาญาและการเปรียบเทียบ"
        "ผู้กระทำความผิดตามกฎหมายว่าด้วยการคุ้มครองแรงงาน พ.ศ. 2558") == [
        "การดำเนินคดีอาญา", "การเปรียบเทียบผู้กระทำความผิด"]


def test_english_headings():
    assert english_heading_entities("Flexible Spending Account (FSA)") == [
        ("Flexible Spending Account", "Concept", ["FSA"])]
    assert english_heading_entities("Oregon Medical and Family Leave") == [
        ("Oregon Medical and Family Leave", "Concept", []), ("Oregon", "Place", [])]
    assert english_heading_entities("Your First Month") == []


def test_thai_matching_takes_the_longest_name_without_overlap():
    reg = EntityRegistry()
    for name in ("วันหยุด", "ค่าล่วงเวลา", "ค่าล่วงเวลาในวันหยุด"):
        reg.add(name, "Concept", "th", "test")
    found = EntityMatcher(reg).find("ให้นายจ้างจ่ายค่าล่วงเวลา ในวันหยุด และวันหยุด", "th")
    names = [reg.entries[e].name for e, _ in found]
    assert names == ["ค่าล่วงเวลาในวันหยุด", "วันหยุด"]  # spaces ignored in Thai


def test_english_matching_case_plural_and_hyphen():
    reg = EntityRegistry()
    reg.add("Short Term Disability", "Concept", "en", "test")
    reg.add("Sabbatical", "Concept", "en", "test")
    m = EntityMatcher(reg)
    assert len(m.find("You may file a short-term disability claim.", "en")) == 1
    assert len(m.find("Two sabbaticals so far.", "en")) == 1
    assert m.find("sabbaticalness", "en") == []


def test_aliases_and_manual_entries(tmp_path):
    f = tmp_path / "manual.yaml"
    f.write_text("- {name: Sick Days, type: Concept, language: en, aliases: [sick leave], "
                 "source: documents, added_by: tester, added_on: 2026-11-25}\n"
                 "- {name: Gym, type: Concept, language: en, source: test_pairs, "
                 "added_by: tester, added_on: 2026-11-25}\n", encoding="utf-8")
    doc = parse_file(FIX / "en_policy_old.md", CFG.layer0, T0)
    reg = build_registry([doc], load_manual(f))
    e = reg.get("en", "sick leave")
    assert e is not None and e.name == "Sick Days" and "manual:documents" in e.sources
    assert reg.get("en", "Gym").sources == {"manual:test_pairs"}
    assert [m["name"] for m in load_manual(f, sources=["documents"])] == ["Sick Days"]
    bad = tmp_path / "bad.yaml"
    bad.write_text("- {name: X, type: Concept, language: en}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing source, added_by, added_on"):
        load_manual(bad)
    bad.write_text("- {name: X, type: Concept, language: en, source: label_sheet, "
                   "added_by: a, added_on: 2026-11-25}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source must be one of"):
        load_manual(bad)
    with pytest.raises(ValueError):
        reg.add("x", "Person", "en", "test")


def test_hub_flag_from_block_share():
    doc = parse_file(FIX / "th_lpa_old.md", CFG.layer0, T0)
    reg = build_registry([doc], [{"name": "ลูกจ้าง", "type": "Role", "language": "th"}])
    ms = EntityMatcher(reg).mentions(doc)
    share = block_share(ms, body_block_counts([doc]), reg)
    flag_hubs(reg, share, 0.5)
    assert reg.get("th", "ลูกจ้าง").hub  # in nearly every block of the excerpt
    assert not reg.get("th", "การเลิกจ้าง").hub
    flag_hubs(reg, share, None)
    assert not any(e.hub for e in reg.entries.values())


def test_registry_is_deterministic():
    docs = [parse_file(FIX / n, CFG.layer0, T0) for n in ("th_lpa_old.md", "en_policy_old.md")]
    a = {k: (v.name, v.entity_type, sorted(v.aliases)) for k, v in build_registry(docs).entries.items()}
    b = {k: (v.name, v.entity_type, sorted(v.aliases))
         for k, v in build_registry(list(reversed(docs))).entries.items()}
    assert a == b
