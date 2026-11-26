"""Impact candidates (M5): graph signals and rankings on small synthetic documents."""

from datetime import datetime, timezone
from pathlib import Path

from kg.config import load_config
from kg.impact import (
    ChangeItem,
    GraphView,
    graph_first,
    graph_signals,
    heading_anchor,
    impact_ranking,
    rrf,
    section_key,
)
from kg.layer0_structure import parse_file

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _doc(tmp_path, name, key, title, lang, body):
    f = tmp_path / name
    f.write_text(f"---\ndoc_key: {key}\ntitle: {title}\nlanguage: {lang}\n---\n# {title}\n\n{body}",
                 encoding="utf-8")
    return parse_file(f, CFG.layer0, T0)


def test_section_keys_and_anchors():
    assert section_key("หมวด 11 ค่าชดเชย > มาตรา ๑๑๘") == "มาตรา118"
    assert section_key("หมวด 1 > ข้อ 9/1") == "ข้อ9/1"
    assert section_key("Paid Time Off > Sabbatical") is None
    assert heading_anchor("Making a Career > Your First 90 Days") == "#your-first-90-days"
    assert heading_anchor("_") is None


def test_rrf_and_rankings_keep_every_candidate():
    assert rrf(["a", "b"], ["b", "c"]) == ["b", "a", "c"]
    signals = {"cite_section": {"c": 1.0}, "value": {}, "entity": {"b": 2.0, "a": 1.0},
               "cite_document": {}}
    hybrid = ["a", "b", "c", "d"]
    assert graph_first(signals, hybrid) == ["c", "b", "a", "d"]
    assert sorted(impact_ranking(signals, hybrid)) == ["a", "b", "c", "d"]


def test_signals_from_citations_entities_and_values(tmp_path):
    act = _doc(tmp_path, "act.md", "t-act", "พระราชบัญญัติทดสอบ พ.ศ. 2541", "th",
               "## หมวด 11 ค่าชดเชย\n\n### มาตรา ๑๑๘\n\n"
               "ค่าชดเชย หมายความว่า เงินที่นายจ้างจ่ายให้แก่ลูกจ้างเมื่อเลิกจ้าง\n\n"
               "### มาตรา ๑๑๙\n\nนายจ้างจ่ายค่าชดเชยภายในสามสิบวัน\n")
    reg = _doc(tmp_path, "reg.md", "t-reg", "ระเบียบทดสอบ", "th",
               "## ข้อ 1\n\nตามมาตรา ๑๑๘ แห่งพระราชบัญญัติทดสอบ พ.ศ. ๒๕๔๑\n\n"
               "## ข้อ 2\n\nให้จ่ายค่าชดเชยภายในสามสิบวัน\n\n"
               "## ข้อ 3\n\nเรื่องอื่นที่ไม่เกี่ยวข้อง\n")
    view = GraphView([act, reg], CFG.layer1, hub_cut=None)
    uid = {pb.block.block_id.split("::")[1]: pb.block.block_uid for pb in reg.blocks}
    change = ChangeItem("X1", "t-act", "หมวด 11 ค่าชดเชย > มาตรา 119",
                        "นายจ้างจ่ายค่าชดเชยภายในสามสิบวัน", "นายจ้างจ่ายค่าชดเชยภายในเจ็ดวัน", "th")
    sig = graph_signals(view, change, set(uid.values()))
    assert uid["ข้อ 2"] in sig["value"] and uid["ข้อ 2"] in sig["entity"]
    assert uid["ข้อ 3"] not in set().union(*sig.values())
    cite = ChangeItem("X2", "t-act", "หมวด 11 ค่าชดเชย > มาตรา 118", "a", "b", "th")
    assert uid["ข้อ 1"] in graph_signals(view, cite, set(uid.values()))["cite_section"]


def test_english_link_to_a_heading_is_a_section_citation(tmp_path):
    career = _doc(tmp_path, "making-a-career.md", "t-career", "Making a Career", "en",
                  "## Your First 90 Days\n\nIn your first 90 days you get aligned.\n")
    guide = _doc(tmp_path, "guide.md", "t-guide", "Guide", "en",
                 "## Start\n\nSee [your first 90 days](making-a-career.md#your-first-90-days).\n")
    view = GraphView([career, guide], CFG.layer1, hub_cut=None)
    uid = guide.blocks[0].block.block_uid
    change = ChangeItem("X3", "t-career", "Your First 90 Days", "old", "new", "en")
    assert uid in graph_signals(view, change, {uid})["cite_section"]
