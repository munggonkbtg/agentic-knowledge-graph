"""Layer 2 (M4): entity registry and MENTIONS, without an LLM.

Purpose (continuation brief): find blocks to review when a fact changes, for
blocks that *state* the fact again or *depend* on it. Citations are layer 1.

Entity types
* Concept   right, benefit, defined term or procedure with rules or values
* Role      a role the text gives duties or powers to
* Artifact  a form, system or non-legal document
* Body      agency, committee, fund, company        (secondary: registry only)
* Place     jurisdiction                            (secondary: registry only)
Laws, sections, people, bare dates and amounts are not entities.

Registry sources (all deterministic, no NER model):
1. definitions "X หมายความว่า …" in the Thai documents (T1 มาตรา 5 and others)
2. Thai chapter headings "หมวด N a b และc" -> a, b, c
3. English section headings ("Flexible Spending Account (FSA)" -> alias FSA)
4. Thai regulation titles "… ว่าด้วยX …" -> X
5. a hand-kept file (registry/entities_manual.yaml): extra entities and aliases

Matching: Thai on compact text (no spaces, Arabic digits), English case-
insensitive on word boundaries with an optional plural "s". Longest alias
first, no overlaps, so "ค่าล่วงเวลาในวันหยุด" is not also "วันหยุด".

Hubs: an entity mentioned in more than `hub_block_share` of the body blocks of
its language is flagged hub = true; hubs are kept but not used for candidates.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from kg.layer0_structure import ParsedDocument
from kg.layer1_references import compact, slug

TYPES = ("Concept", "Role", "Artifact", "Body", "Place")
CORE_TYPES = ("Concept", "Role", "Artifact")

# ---------------------------------------------------------------- Thai rules

_MARKERS = re.compile(r"\[[0-9๐-๙]+\]|[\u0080-\u009f“”\"]")
DEFINITION = re.compile(r"(\S+)\s*หมายความว่า\s*(\S{0,40})")
HEADING_PREFIX = re.compile(r"^(หมวด|ส่วน|บท)\s*[0-9๐-๙/]*\s*")
TITLE_SUBJECT = re.compile(r"ว่าด้วย(.+?)(?:ตาม(?:พระราชบัญญัติ|กฎหมาย)|\s*พ\.ศ\.|\(|$)")
STRUCTURAL = {"บททั่วไป", "บทเฉพาะกาล", "เชิงอรรถ", "_"}
TH_ROLE_TITLES = ("อธิบดี", "รัฐมนตรี", "ปลัดกระทรวง", "ผู้อำนวยการ", "เลขาธิการ",
                  "พนักงานเจ้าหน้าที่", "พนักงานตรวจแรงงาน", "พนักงานสอบสวน", "นายจ้าง",
                  "ลูกจ้าง")
TH_BODY_PREFIXES = ("คณะกรรมการ", "กองทุน", "กรม", "กระทรวง", "สำนักงาน", "ศาล")
TH_ARTIFACT_PREFIXES = ("แบบ", "ทะเบียน", "หนังสือ", "เอกสาร", "บัตร")


def _clean(text: str) -> str:
    return unicodedata.normalize("NFC", _MARKERS.sub("", text)).strip()


def thai_type(term: str, definition_start: str = "") -> str:
    if term.startswith(TH_BODY_PREFIXES):
        return "Body"
    if term.startswith(TH_ARTIFACT_PREFIXES):
        return "Artifact"
    if term.startswith(TH_ROLE_TITLES) or term.startswith("ผู้") \
            or definition_start.startswith(("ผู้", "บุคคล", "ข้าราชการ", "เจ้าหน้าที่", "พนักงาน")):
        return "Role"
    return "Concept"


def thai_definitions(text: str) -> list[tuple[str, str]]:
    """[(term, type)] for every 'X หมายความว่า …' in the text. A term repealed
    ('X (ยกเลิก)') has no หมายความว่า and is skipped."""
    out = []
    for m in DEFINITION.finditer(_clean(text)):
        term = m.group(1).strip("()").removesuffix("ตามมาตรานี้")
        # "… พ.ศ. ๒๕๔๑ หมายความว่า" defines a law name (a Document, not an entity)
        if not re.search(r"[ก-ฮ]", term) or len(term) < 2:
            continue
        if term not in ("ในพระราชบัญญัตินี้", "ในระเบียบนี้", "ในกฎกระทรวงนี้"):
            out.append((term, thai_type(term, m.group(2))))
    return out


def thai_heading_terms(heading: str) -> list[str]:
    """'หมวด 5 ค่าจ้าง ค่าล่วงเวลา และค่าทำงานในวันหยุด' -> its list items."""
    h = HEADING_PREFIX.sub("", _clean(heading))
    if not h or h in STRUCTURAL or h.startswith(("มาตรา", "ข้อ")):
        return []
    terms = []
    for item in h.split():
        for part in re.split(r"และ(?=การ|ความ)", item.removeprefix("และ")):
            if len(part) >= 2 and part not in STRUCTURAL:
                terms.append(part)
    return terms


def thai_title_subjects(title: str) -> list[str]:
    """'ระเบียบ… ว่าด้วยการดำเนินคดีอาญาและการเปรียบเทียบผู้กระทำความผิดตามกฎหมาย…'
    -> ['การดำเนินคดีอาญา', 'การเปรียบเทียบผู้กระทำความผิด']."""
    m = TITLE_SUBJECT.search(_clean(title))
    if not m:
        return []
    subject = re.sub(r"\s+", "", m.group(1))
    return [p for p in re.split(r"และ(?=การ|ความ)", subject) if len(p) >= 2]


# ---------------------------------------------------------------- English rules

EN_SKIP_HEADING = re.compile(r"^(your\b|_$)", re.I)
ACRONYM = re.compile(r"\s*\(([A-Z]{2,6})\)\s*$")
EN_PLACES = re.compile(r"^(California|Colorado|Massachusetts|New Jersey|Oregon|Washington|"
                       r"New York)\b")


def english_heading_entities(heading: str) -> list[tuple[str, str, list[str]]]:
    """[(name, type, aliases)] for one heading. 'Oregon Medical and Family Leave'
    gives the leave (Concept) and the state (Place)."""
    h = heading.strip()
    if not h or EN_SKIP_HEADING.match(h):
        return []
    aliases = []
    m = ACRONYM.search(h)
    if m:
        aliases.append(m.group(1))
        h = h[: m.start()].strip()
    out = [(h, "Concept", aliases)]
    place = EN_PLACES.match(h)
    if place:
        out.append((place.group(1), "Place", []))
    return out


# ---------------------------------------------------------------- registry


@dataclass
class EntityEntry:
    entity_id: str
    name: str
    entity_type: str
    language: str
    aliases: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)  # where the registry found it
    hub: bool = False


def entity_id(entity_type: str, language: str, name: str) -> str:
    key = compact(name)[0] if language == "th" else name.lower()
    return f"{entity_type.lower()}:{language}:{slug(key)}"


class EntityRegistry:
    def __init__(self) -> None:
        self.entries: dict[str, EntityEntry] = {}
        self._by_key: dict[tuple[str, str], str] = {}  # (language, match key) -> id

    @staticmethod
    def key(language: str, name: str) -> str:
        return compact(name)[0] if language == "th" else name.lower()

    def add(self, name: str, entity_type: str, language: str, source: str,
            aliases: Iterable[str] = ()) -> EntityEntry:
        """Add a name, or add a source / aliases to the entity that already has it.
        The first type seen wins (definitions are added first)."""
        if entity_type not in TYPES:
            raise ValueError(f"unknown entity type {entity_type!r}")
        existing = self._by_key.get((language, self.key(language, name)))
        if existing:
            e = self.entries[existing]
        else:
            eid = entity_id(entity_type, language, name)
            e = self.entries.setdefault(eid, EntityEntry(eid, name, entity_type, language))
            self._by_key[(language, self.key(language, name))] = eid
        e.sources.add(source)
        for a in [name, *aliases]:
            # a name that already belongs to another entity stays with that one,
            # so each alias points to exactly one entity
            owner = self._by_key.setdefault((language, self.key(language, a)), e.entity_id)
            if owner == e.entity_id:
                e.aliases.add(a)
        return e

    def get(self, language: str, name: str) -> EntityEntry | None:
        eid = self._by_key.get((language, self.key(language, name)))
        return self.entries.get(eid) if eid else None

    def alias_keys(self) -> dict[tuple[str, str], str]:
        return dict(self._by_key)


def load_manual(path: Path) -> list[dict]:
    """registry/entities_manual.yaml: a list of
    {name, type, language, aliases: [...]} reviewed by a person."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [dict(d) for d in data]


def build_registry(docs: Iterable[ParsedDocument], manual: list[dict] = ()) -> EntityRegistry:
    docs = sorted(docs, key=lambda d: d.document.doc_key)  # deterministic order
    reg = EntityRegistry()
    # 1. definitions first, so their type wins
    for d in docs:
        if d.document.language.value != "th":
            continue
        for pb in d.blocks:
            if pb.block.role.value != "body":
                continue
            for term, typ in thai_definitions(pb.block.text):
                reg.add(term, typ, "th", f"definition:{pb.block.block_id}")
    # 2-4. headings and titles
    for d in docs:
        lang = d.document.language.value
        headings = sorted({h for pb in d.blocks
                           for h in pb.block.block_id.split("::")[1].split(" > ")})
        for h in headings:
            if lang == "th":
                for t in thai_heading_terms(h):
                    reg.add(t, thai_type(t), "th", f"heading:{d.document.doc_key}")
            else:
                for name, typ, aliases in english_heading_entities(h):
                    reg.add(name, typ, "en", f"heading:{d.document.doc_key}", aliases)
        if lang == "th":
            for t in thai_title_subjects(d.document.title):
                reg.add(t, thai_type(t), "th", f"title:{d.document.doc_key}")
    # 5. hand-kept entries
    for m in manual:
        reg.add(m["name"], m["type"], m["language"], "manual", m.get("aliases") or [])
    return reg


# ---------------------------------------------------------------- matching


@dataclass(frozen=True)
class Mention:
    block_uid: str
    entity_id: str
    surface: str  # the alias as found (compact form for Thai)


class EntityMatcher:
    def __init__(self, registry: EntityRegistry) -> None:
        self.registry = registry
        by_lang: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for (lang, key), eid in registry.alias_keys().items():
            by_lang[lang].append((key, eid))
        # longest first, so a long alias wins over a short one inside it
        self._th = sorted(by_lang["th"], key=lambda kv: (-len(kv[0]), kv[0]))
        en = sorted(by_lang["en"], key=lambda kv: (-len(kv[0]), kv[0]))
        # spaces and hyphens are interchangeable ("short-term" = "short term")
        self._en = [(re.compile(r"(?<![\w-])"
                                + r"[\s-]+".join(re.escape(w) for w in re.split(r"[\s-]+", k))
                                + r"s?(?![\w-])", re.I), k, eid) for k, eid in en]

    def find(self, text: str, language: str) -> list[tuple[str, str]]:
        """[(entity_id, surface)] in text order, no overlapping matches."""
        taken: list[tuple[int, int]] = []
        found: list[tuple[int, str, str]] = []

        def free(s: int, e: int) -> bool:
            return all(e <= a or s >= b for a, b in taken)

        if language == "th":
            c = compact(_clean(text))[0]
            for key, eid in self._th:
                start = c.find(key)
                while start != -1:
                    end = start + len(key)
                    if free(start, end):
                        taken.append((start, end))
                        found.append((start, eid, key))
                    start = c.find(key, start + 1)
        else:
            for pattern, _, eid in self._en:
                for m in pattern.finditer(text):
                    if free(m.start(), m.end()):
                        taken.append((m.start(), m.end()))
                        found.append((m.start(), eid, m.group(0)))
        return [(eid, s) for _, eid, s in sorted(found)]

    def mentions(self, doc: ParsedDocument) -> list[Mention]:
        """One mention per (block, entity): the first surface found."""
        out = []
        lang = doc.document.language.value
        for pb in doc.blocks:
            if pb.block.role.value != "body":
                continue
            seen = set()
            for eid, surface in self.find(pb.block.text, lang):
                if eid not in seen:
                    seen.add(eid)
                    out.append(Mention(pb.block.block_uid, eid, surface))
        return out


def block_share(mentions: Iterable[Mention], body_blocks: dict[str, int],
                registry: EntityRegistry) -> dict[str, float]:
    """Share of the body blocks of the entity's language that mention it."""
    blocks: dict[str, set[str]] = defaultdict(set)
    for m in mentions:
        blocks[m.entity_id].add(m.block_uid)
    return {eid: len(blocks[eid]) / body_blocks[e.language]
            for eid, e in registry.entries.items() if body_blocks.get(e.language)}


def flag_hubs(registry: EntityRegistry, share: dict[str, float], cutoff: float | None) -> None:
    for eid, e in registry.entries.items():
        e.hub = cutoff is not None and share.get(eid, 0.0) > cutoff


def body_block_counts(docs: Iterable[ParsedDocument]) -> dict[str, int]:
    return dict(Counter(d.document.language.value for d in docs for pb in d.blocks
                        if pb.block.role.value == "body"))
