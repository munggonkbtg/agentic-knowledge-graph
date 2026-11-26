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


def test_view_from_graph_records_gives_the_same_signals(tmp_path):
    act = _doc(tmp_path, "act.md", "t-act", "พระราชบัญญัติทดสอบ พ.ศ. 2541", "th",
               "## หมวด 11 ค่าชดเชย\n\n### มาตรา ๑๑๘\n\n"
               "ค่าชดเชย หมายความว่า เงินที่นายจ้างจ่ายให้แก่ลูกจ้างเมื่อเลิกจ้าง\n")
    reg = _doc(tmp_path, "reg.md", "t-reg", "ระเบียบทดสอบ", "th",
               "## ข้อ 1\n\nตามมาตรา ๑๑๘ แห่งพระราชบัญญัติทดสอบ พ.ศ. ๒๕๔๑\n\n"
               "## ข้อ 2\n\nให้จ่ายค่าชดเชยภายในสามสิบวัน\n")
    mem = GraphView([act, reg], CFG.layer1, hub_cut=None)
    # records shaped like Store.current_body_blocks / Store.impact_edges
    blocks = [{"uid": u, "text": b.text, "doc_key": b.doc_key, "language": b.language}
              for u, b in mem.blocks.items()]
    refs = [{"uid": u, "target": t, "cited_section": s}
            for t, rows in mem.refs.items() for u, s in rows]
    mentions = []
    for u, b in mem.blocks.items():
        for e in b.entities:
            vals = [a for a in b.values if a.entity_id == e]
            mentions.append({"uid": u, "entity": e, "hub": False,
                             "value": [a.value.value for a in vals] or None,
                             "unit": [a.value.unit for a in vals],
                             "family": [a.value.family for a in vals],
                             "base_value": [a.value.base_value for a in vals],
                             "base_unit": [a.value.base_unit for a in vals],
                             "value_text": [a.value.value_text for a in vals],
                             "attribute": [a.attribute for a in vals]})
    graph = GraphView.from_graph(blocks, {"refs": refs, "mentions": mentions, "loose": [],
                                          "hubs": []}, [act, reg])
    change = ChangeItem("X", "t-act", "หมวด 11 ค่าชดเชย > มาตรา 118",
                        "ให้จ่ายค่าชดเชยภายในสามสิบวัน", "ให้จ่ายค่าชดเชยภายในเจ็ดวัน", "th")
    cands = {u for u, b in mem.blocks.items() if b.doc_key == "t-reg"}
    assert graph_signals(graph, change, cands) == graph_signals(mem, change, cands)


def test_check_labels_and_reorders_but_never_drops():
    from kg.impact import order_after_check

    order = ["a", "b", "c", "d", "e"]
    verdicts = {"a": "not_affected", "b": "needs_update", "c": "needs_update", "d": "unsure"}
    out = order_after_check(order, verdicts, historical={"c"}, top=4)
    assert out == ["b", "a", "c", "d", "e"]  # c is historical: not moved up
    assert sorted(out) == sorted(order)
    assert order_after_check(order, {}, set(), 4) == order


def test_evidence_matches_despite_quote_style_and_ellipsis():
    from kg.impact import evidence_in

    text = "You’re eligible for coverage on your first day. Shares max out after 10 years."
    assert evidence_in("You're eligible for coverage on your first day.", text)
    assert evidence_in('"You\'re eligible for coverage..." Shares max out after 10 years.', text)
    assert not evidence_in("You're eligible after 90 days.", text)
    assert not evidence_in("", text)


def test_link_to_a_renamed_heading_is_a_broken_reference(tmp_path):
    from kg.impact import citable_targets

    old = _doc(tmp_path, "making-a-career.md", "t-career", "Making a Career", "en",
               "## Your First 90 Days\n\nIn your first 90 days you get aligned.\n")
    guide = _doc(tmp_path, "guide.md", "t-guide", "Guide", "en",
                 "## Start\n\nSee [your first 90 days](making-a-career.md#your-first-90-days).\n")
    (tmp_path / "v2").mkdir()
    new = _doc(tmp_path / "v2", "making-a-career.md", "t-career", "Making a Career", "en",
               "## Your First Year\n\nIn your first year you get aligned.\n")
    view = GraphView([old, guide], CFG.layer1, hub_cut=None)
    uid = guide.blocks[0].block.block_uid
    change = ChangeItem("X", "t-career", "Your First 90 Days", "old", "new", "en")
    after = {"t-career": citable_targets(new), "t-guide": citable_targets(guide)}
    sig = graph_signals(view, change, {uid}, targets_after=after)
    assert uid in sig["broken_reference"] and uid in sig["cite_section"]
    # the heading still exists -> not broken
    same = {"t-career": citable_targets(old)}
    assert graph_signals(view, change, {uid}, targets_after=same)["broken_reference"] == {}
    assert graph_first(sig, [uid])[0] == uid


def test_citation_of_a_removed_section_is_broken_and_subsections_count(tmp_path):
    from kg.impact import citable_targets, target_exists

    act = _doc(tmp_path, "act.md", "t-act", "พระราชบัญญัติทดสอบ พ.ศ. 2541", "th",
               "## หมวด 1 บททั่วไป\n\n### มาตรา ๙\n\nข้อความ\n\n### มาตรา ๑๑๘\n\nข้อความ\n")
    t = citable_targets(act)
    assert {"มาตรา9", "มาตรา118", "หมวด1"} <= t
    assert target_exists("มาตรา118(6)", t) and target_exists("มาตรา118วรรคหนึ่ง", t)
    assert not target_exists("มาตรา119", t) and not target_exists("มาตรา1181", t)
    assert target_exists("", t)  # a document-level citation is never broken


def test_merges_depends_and_rejected_citations_in_the_signals(tmp_path):
    act = _doc(tmp_path, "act.md", "t-act", "พระราชบัญญัติทดสอบ พ.ศ. 2541", "th",
               "## หมวด 11 ค่าชดเชย\n\n### มาตรา ๑๑๘\n\n"
               "ค่าชดเชย หมายความว่า เงินที่นายจ้างจ่ายให้แก่ลูกจ้างเมื่อเลิกจ้าง\n")
    guide = _doc(tmp_path, "guide.md", "t-guide", "Guide", "en",
                 "## Severance Pay\n\nSeverance pay is paid when employment ends.\n\n"
                 "## Notes\n\nKeep your contract.\n\n"
                 "## Cites\n\nSee มาตรา ๑๑๘ แห่งพระราชบัญญัติทดสอบ พ.ศ. ๒๕๔๑.\n")
    base = GraphView([act, guide], CFG.layer1, hub_cut=None)
    th = base.registry.get("th", "ค่าชดเชย").entity_id
    en = base.registry.get("en", "Severance Pay").entity_id
    uid = {pb.block.block_id.split("::")[1]: pb.block.block_uid for pb in guide.blocks}
    changed = act.blocks[0].block.block_uid
    change = ChangeItem("X", "t-act", "หมวด 11 ค่าชดเชย > มาตรา 118",
                        "ค่าชดเชย หมายความว่า เงินที่นายจ้างจ่ายให้แก่ลูกจ้างเมื่อเลิกจ้าง",
                        "ค่าชดเชย หมายความว่า เงินที่จ่ายเมื่อเลิกจ้าง", "th", changed)
    cands = set(uid.values())
    # without the merge the Thai change and the English block share no entity
    assert uid["Severance Pay"] not in graph_signals(base, change, cands)["entity"]
    merged = GraphView([act, guide], CFG.layer1, hub_cut=None, merges={en: th},
                       depends=[(uid["Notes"], changed)])
    sig = graph_signals(merged, change, cands)
    assert uid["Severance Pay"] in sig["entity"]
    assert sig["depends"] == {uid["Notes"]: 1.0}
    # a citation rejected in review keeps its signal at a lower strength
    merged.ref_conf[(uid["Cites"], "t-act", "มาตรา118")] = 0.5
    assert graph_signals(merged, change, cands)["cite_section"][uid["Cites"]] == 0.5
