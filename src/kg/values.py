"""Values on MENTIONS (M4 step 3): numbers with units, found by rules.

A value is a number followed by a unit ("สามสิบวัน", "7 calendar days", "75%",
"ร้อยละห้าสิบ", "$3,000"). Bare numbers without a unit are not values (section
numbers, list items, years after พ.ศ.).

Normalization keeps two things apart:
* the **fine unit** as written: วันทำงาน is not วัน, "work days" are not
  "calendar days";
* a **comparable form** (family, base unit, value) so that equal quantities
  written differently compare equal: 1 year = 12 months, 2 weeks = 14 days.
  Units are only converted inside a family where the conversion is exact.
  Days and months are NOT converted into each other (a month is not 30 days in
  law: "90 days" and "3 months" stay different, and are reported as such).

The tables below are the whole rule set; `normalization_table()` prints them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ---------------------------------------------------------------- numbers

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

THAI_DIGIT_WORDS = {"ศูนย์": 0, "หนึ่ง": 1, "เอ็ด": 1, "สอง": 2, "ยี่": 2, "สาม": 3, "สี่": 4,
                    "ห้า": 5, "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9}
THAI_MULTIPLIERS = {"สิบ": 10, "ร้อย": 100, "พัน": 1_000, "หมื่น": 10_000, "แสน": 100_000,
                    "ล้าน": 1_000_000}

EN_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "a hundred": 100, "one hundred": 100,
}

_THAI_WORD = "|".join(sorted([*THAI_DIGIT_WORDS, *THAI_MULTIPLIERS], key=len, reverse=True))
THAI_NUMBER = re.compile(f"(?:{_THAI_WORD})+")


def thai_words_to_number(text: str) -> int | None:
    """'สามสิบ' -> 30, 'เก้าสิบแปด' -> 98, 'หนึ่งร้อยยี่สิบ' -> 120, 'สิบเอ็ด' -> 11,
    'สองหมื่น' -> 20000. None if the text is not only number words."""
    tokens = re.findall(_THAI_WORD, text)
    if not tokens or "".join(tokens) != text:
        return None
    total = current = 0
    for t in tokens:
        if t in THAI_DIGIT_WORDS:
            current = THAI_DIGIT_WORDS[t]
        elif t == "ล้าน":
            total = (total + (current or 1)) * 1_000_000
            current = 0
        else:
            total += (current or 1) * THAI_MULTIPLIERS[t]
            current = 0
    return total + current


def parse_number(text: str) -> float | None:
    """Arabic or Thai digits (with , separators and a decimal point), Thai number
    words, or English number words."""
    t = unicodedata.normalize("NFC", text).strip().translate(THAI_DIGITS).lower()
    if re.fullmatch(r"\d[\d,]*(\.\d+)?", t):
        return float(t.replace(",", ""))
    if t in EN_NUMBER_WORDS:
        return float(EN_NUMBER_WORDS[t])
    m = re.fullmatch(r"(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[- ]"
                     r"(one|two|three|four|five|six|seven|eight|nine)", t)
    if m:
        return float(EN_NUMBER_WORDS[m.group(1)] + EN_NUMBER_WORDS[m.group(2)])
    n = thai_words_to_number(t)
    return float(n) if n is not None else None


# ---------------------------------------------------------------- units


@dataclass(frozen=True)
class Unit:
    fine: str          # the unit as kept on the edge (unit property)
    family: str        # values compare only inside one family
    base: str          # comparable unit inside the family
    factor: float      # value in `base` = value * factor


U = Unit
# Thai units: longest first when matching. Fine units stay apart: วันทำงาน is its
# own family, so "สามวันทำงาน" never equals "สามวัน".
THAI_UNITS: dict[str, Unit] = {
    "วันทำงาน": U("work_day", "work_days", "work_day", 1),
    "วันทำการ": U("work_day", "work_days", "work_day", 1),
    "วัน": U("day", "calendar_days", "day", 1),
    "สัปดาห์": U("week", "calendar_days", "day", 7),
    "เดือน": U("month", "months", "month", 1),
    "ปี": U("year", "months", "month", 12),
    "ชั่วโมง": U("hour", "duration_minutes", "minute", 60),
    "นาที": U("minute", "duration_minutes", "minute", 1),
    "บาท": U("baht", "money_thb", "baht", 1),
    "ครั้ง": U("times", "count_times", "times", 1),
    "คน": U("persons", "count_persons", "persons", 1),
}
# English units, matched case-insensitively with an optional plural "s".
# A modifier between number and unit decides the fine unit:
# "7 calendar days" -> day; "7 consecutive work days", "5 working days",
# "3 business days" -> work_day.
ENGLISH_UNITS: dict[str, Unit] = {
    "work day": U("work_day", "work_days", "work_day", 1),
    "working day": U("work_day", "work_days", "work_day", 1),
    "business day": U("work_day", "work_days", "work_day", 1),
    "workday": U("work_day", "work_days", "work_day", 1),
    "calendar day": U("day", "calendar_days", "day", 1),
    "day": U("day", "calendar_days", "day", 1),
    "week": U("week", "calendar_days", "day", 7),
    "month": U("month", "months", "month", 1),
    "year": U("year", "months", "month", 12),
    "hour": U("hour", "duration_minutes", "minute", 60),
    "minute": U("minute", "duration_minutes", "minute", 1),
}
PERCENT = U("percent", "percent", "percent", 1)
USD = U("usd", "money_usd", "usd", 1)


@dataclass(frozen=True)
class Value:
    value: float        # normalized number, in the fine unit
    unit: str           # fine unit (Unit.fine)
    family: str
    base_value: float   # value in the family's base unit
    base_unit: str
    value_text: str     # original wording
    start: int          # character offsets in the block text
    end: int

    def comparable(self) -> tuple[str, float]:
        return (self.family, round(self.base_value, 6))


# ---------------------------------------------------------------- extraction

_TH_NUM = rf"(?:[0-9๐-๙][0-9๐-๙,]*(?:\.[0-9๐-๙]+)?|{THAI_NUMBER.pattern})"
_TH_UNIT = "|".join(sorted(THAI_UNITS, key=len, reverse=True))
THAI_VALUE = re.compile(rf"(?<!พ\.ศ\.)(?<!พ\.ศ\. )({_TH_NUM})\s*({_TH_UNIT})")
THAI_PERCENT = re.compile(rf"ร้อยละ\s*({_TH_NUM})")

_EN_WORDS = "|".join(sorted((w for w in EN_NUMBER_WORDS if " " not in w), key=len, reverse=True))
_EN_NUM = (rf"(?:\d[\d,]*(?:\.\d+)?|(?:{_EN_WORDS})(?:[- ](?:one|two|three|four|five|six|"
           rf"seven|eight|nine))?)")
_EN_UNIT = "|".join(re.escape(u).replace(r"\ ", r"[\s-]+")
                    for u in sorted(ENGLISH_UNITS, key=len, reverse=True))
ENGLISH_VALUE = re.compile(
    rf"(?<![\w$])({_EN_NUM})(?:[\s-]+(?:consecutive|full|additional|more))?[\s-]+"
    rf"({_EN_UNIT})s?\b", re.I)
ENGLISH_PERCENT = re.compile(rf"(?<![\w.])({_EN_NUM})\s*(?:%|percent\b)", re.I)
ENGLISH_USD = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")


def _make(number: str, unit: Unit, text: str, m: re.Match) -> Value | None:
    n = parse_number(number)
    if n is None:
        return None
    return Value(n, unit.fine, unit.family, n * unit.factor, unit.base,
                 text[m.start():m.end()], m.start(), m.end())


def _english_unit(raw: str) -> Unit:
    key = re.sub(r"[\s-]+", " ", raw.lower()).rstrip("s")
    if key == "workday":
        return ENGLISH_UNITS["workday"]
    return ENGLISH_UNITS[key]


def extract_values(text: str, language: str) -> list[Value]:
    """Every value in the text, in text order, without overlaps."""
    text = unicodedata.normalize("NFC", text)
    found: list[Value] = []
    if language == "th":
        for m in THAI_VALUE.finditer(text):
            v = _make(m.group(1), THAI_UNITS[m.group(2)], text, m)
            if v:
                found.append(v)
        for m in THAI_PERCENT.finditer(text):
            v = _make(m.group(1), PERCENT, text, m)
            if v:
                found.append(v)
    # English patterns also run on Thai text (Arabic "75%" occurs in both)
    for m in ENGLISH_VALUE.finditer(text):
        v = _make(m.group(1), _english_unit(m.group(2)), text, m)
        if v:
            found.append(v)
    for m in ENGLISH_PERCENT.finditer(text):
        v = _make(m.group(1), PERCENT, text, m)
        if v:
            found.append(v)
    for m in ENGLISH_USD.finditer(text):
        v = _make(m.group(1), USD, text, m)
        if v:
            found.append(v)
    found.sort(key=lambda v: (v.start, -(v.end - v.start)))
    out: list[Value] = []
    for v in found:
        if not out or v.start >= out[-1].end:
            out.append(v)
    return out


def normalization_table() -> str:
    """The rule set as Markdown (shown to the user before any corpus run)."""
    rows = ["| written | fine unit | family | comparable as |", "|---|---|---|---|"]
    for lang, table in (("th", THAI_UNITS), ("en", ENGLISH_UNITS)):
        for w, u in table.items():
            conv = (f"x {u.factor:g} {u.base}" if u.factor != 1 else u.base)
            rows.append(f"| {w} ({lang}) | {u.fine} | {u.family} | {conv} |")
    rows += [f"| ร้อยละ N, N%, N percent | {PERCENT.fine} | {PERCENT.family} | percent |",
             f"| $N | {USD.fine} | {USD.family} | usd |"]
    return "\n".join(rows)


# ---------------------------------------------------------------- attachment


@dataclass(frozen=True)
class AttachedValue:
    value: Value
    entity_id: str | None  # nearest non-hub entity mention in the block, if any
    attribute: str         # PROVISIONAL rule: "<entity_id>|<family>" or "|<family>"


def attach_values(values: list[Value], spans: list[tuple[str, str, int, int]],
                  hubs: set[str] = frozenset()) -> list[AttachedValue]:
    """Attach each value to the nearest non-hub entity mention in the same block
    (by character distance between the two spans; ties go to the entity before
    the value). The attribute is the pair (entity, unit family): a rule-based
    stand-in for "what the value is about", coarser than e.g. "payment deadline".
    A value with no entity in the block keeps entity_id None."""
    spans = [s for s in spans if s[0] not in hubs]
    out = []
    for v in values:
        best, best_d = None, None
        for eid, _, a, b in spans:
            d = v.start - b if b <= v.start else (a - v.end if a >= v.end else 0)
            d_key = (d, 0 if b <= v.start else 1)
            if best_d is None or d_key < best_d:
                best, best_d = eid, d_key
        out.append(AttachedValue(v, best, f"{best or ''}|{v.family}"))
    return out
