"""Values on MENTIONS: number words, units and comparable forms (no corpus)."""

import pytest

from kg.values import extract_values, normalization_table, parse_number, thai_words_to_number


@pytest.mark.parametrize("words,n", [
    ("สาม", 3), ("สิบ", 10), ("สิบเอ็ด", 11), ("ยี่สิบ", 20), ("ยี่สิบเอ็ด", 21),
    ("สามสิบ", 30), ("เก้าสิบแปด", 98), ("หนึ่งร้อยยี่สิบ", 120), ("ร้อยยี่สิบ", 120),
    ("สี่ร้อย", 400), ("สองหมื่น", 20000), ("หนึ่งแสน", 100000), ("สองล้าน", 2000000),
    ("หนึ่งพันห้าร้อย", 1500)])
def test_thai_number_words(words, n):
    assert thai_words_to_number(words) == n


def test_numbers_in_other_forms():
    assert parse_number("๓๐") == 30
    assert parse_number("3,000") == 3000
    assert parse_number("seven") == 7
    assert parse_number("twenty-one") == 21
    assert parse_number("สามารถ") is None


def _vals(text, lang):
    return [(v.value, v.unit, v.comparable()) for v in extract_values(text, lang)]


def test_thai_values_keep_the_fine_unit():
    assert _vals("ลาได้ไม่น้อยกว่าสามวันทำงาน", "th") == [
        (3, "work_day", ("work_days", 3))]
    assert _vals("ภายในสามวันนับแต่วันเลิกจ้าง", "th") == [(3, "day", ("calendar_days", 3))]
    assert _vals("ไม่เกินเก้าสิบแปดวัน", "th") == [(98, "day", ("calendar_days", 98))]
    assert _vals("ร้อยละห้าสิบ ของค่าจ้าง", "th") == [(50, "percent", ("percent", 50))]
    assert _vals("ปรับไม่เกินสองหมื่นบาท", "th") == [(20000, "baht", ("money_thb", 20000))]


def test_years_after_pho_so_and_bare_numbers_are_not_values():
    assert _vals("ตามพระราชบัญญัติ พ.ศ. ๒๕๔๑ มาตรา ๑๑๘", "th") == []
    assert _vals("ลูกจ้างสามารถลาได้", "th") == []


def test_comparable_forms_convert_only_exactly():
    one_year = extract_values("within 1 year", "en")[0]
    twelve = extract_values("within 12 months", "en")[0]
    assert one_year.comparable() == twelve.comparable() == ("months", 12)
    assert one_year.unit == "year" and twelve.unit == "month"  # fine units kept
    two_weeks = extract_values("two weeks", "en")[0]
    assert two_weeks.comparable() == ("calendar_days", 14)
    ninety = extract_values("your first 90 days", "en")[0]
    three = extract_values("the first 3 months", "en")[0]
    assert ninety.comparable() != three.comparable()  # days are not months


def test_english_modifiers_decide_work_or_calendar_days():
    assert _vals("a 7-calendar-day waiting period", "en") == [(7, "day", ("calendar_days", 7))]
    assert _vals("more than 7 consecutive work days", "en") == [
        (7, "work_day", ("work_days", 7))]
    assert _vals("within 5 working days", "en")[0][1] == "work_day"
    assert _vals("a 30-day notice", "en") == [(30, "day", ("calendar_days", 30))]


def test_percent_and_dollars():
    assert _vals("up to 70% of your salary and up to $3,000 per week", "en") == [
        (70, "percent", ("percent", 70)), (3000, "usd", ("money_usd", 3000))]
    assert _vals("we pay 75 percent", "en") == [(75, "percent", ("percent", 75))]


def test_offsets_and_original_wording():
    text = "Leave of six months."
    v = extract_values(text, "en")[0]
    assert text[v.start:v.end] == v.value_text == "six months"


def test_table_lists_every_unit():
    table = normalization_table()
    for w in ("วันทำงาน", "calendar day", "ร้อยละ"):
        assert w in table


def test_entity_spans_point_into_the_original_thai_text():
    from kg.layer2_entities import EntityMatcher, EntityRegistry

    reg = EntityRegistry()
    reg.add("ค่าชดเชย", "Concept", "th", "test")
    text = "ให้นายจ้างจ่ายค่า ชดเชย[๓] ภายในสามสิบวัน"
    (eid, surface, a, b), = EntityMatcher(reg).find_spans(text, "th")
    assert text[a:b] == "ค่า ชดเชย" and surface == "ค่าชดเชย"


def test_values_attach_to_the_nearest_non_hub_entity():
    from kg.layer2_entities import EntityMatcher, EntityRegistry
    from kg.values import attach_values

    reg = EntityRegistry()
    for name in ("ลูกจ้าง", "ค่าชดเชย", "วันลา"):
        reg.add(name, "Concept", "th", "test")
    text = "ลูกจ้างมีวันลาสามวันทำงาน และได้ค่าชดเชยสามสิบวัน"
    m = EntityMatcher(reg)
    spans = m.find_spans(text, "th")
    hub = reg.get("th", "ลูกจ้าง").entity_id
    att = attach_values(extract_values(text, "th"), spans, {hub})
    names = [reg.entries[a.entity_id].name for a in att]
    assert names == ["วันลา", "ค่าชดเชย"]
    assert att[0].attribute.endswith("|work_days") and att[1].attribute.endswith("|calendar_days")
    # no entity in the block: the value is kept, unattached
    alone = attach_values(extract_values("within 30 days", "en"), [], set())
    assert alone[0].entity_id is None and alone[0].attribute == "|calendar_days"
