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
from kg.values import AttachedValue, attach_values, extract_values

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


MANUAL_SOURCES = ("documents", "test_pairs")
MANUAL_REQUIRED = ("name", "type", "language", "source", "added_by", "added_on")


def load_manual(path: Path, sources: Iterable[str] | None = None) -> list[dict]:
    """registry/entities_manual.yaml: a list of {name, type, language, aliases,
    source, added_by, added_on}. `source` is "documents" (found by reading the
    documents) or "test_pairs" (taken from the measured review pairs; kept out of
    headline numbers). `sources` keeps only entries from those sources."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    out = []
    for i, d in enumerate(data, start=1):
        missing = [k for k in MANUAL_REQUIRED if not d.get(k)]
        if missing:
            raise ValueError(f"{path.name} entry {i}: missing {', '.join(missing)}")
        if d["source"] not in MANUAL_SOURCES:
            raise ValueError(f"{path.name} entry {i}: source must be one of {MANUAL_SOURCES}")
        if sources is None or d["source"] in set(sources):
            out.append(dict(d))
    return out


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
        reg.add(m["name"], m["type"], m["language"], f"manual:{m.get('source', 'documents')}",
                m.get("aliases") or [])
    return reg


# ---------------------------------------------------------------- matching


@dataclass(frozen=True)
class Mention:
    block_uid: str
    entity_id: str
    surface: str  # the alias as found (compact form for Thai)
    values: tuple[AttachedValue, ...] = ()  # values attached to this entity (step 3)


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
        return [(eid, s) for eid, s, _, _ in self.find_spans(text, language)]

    def find_spans(self, text: str, language: str) -> list[tuple[str, str, int, int]]:
        """[(entity_id, surface, start, end)] in text order, no overlaps. start / end
        are character offsets in the NFC form of `text` (Thai surfaces are the
        compact form: no spaces, Arabic digits)."""
        taken: list[tuple[int, int]] = []
        found: list[tuple[int, str, str, int]] = []

        def free(s: int, e: int) -> bool:
            return all(e <= a or s >= b for a, b in taken)

        if language == "th":
            # blank out markers instead of removing them, so offsets stay valid
            nfc = unicodedata.normalize("NFC", text)
            c, idx = compact(_MARKERS.sub(lambda m: " " * len(m.group()), nfc))
            for key, eid in self._th:
                start = c.find(key)
                while start != -1:
                    end = start + len(key)
                    if free(start, end):
                        taken.append((start, end))
                        found.append((idx[start], eid, key, idx[end - 1] + 1))
                    start = c.find(key, start + 1)
        else:
            for pattern, _, eid in self._en:
                for m in pattern.finditer(text):
                    if free(m.start(), m.end()):
                        taken.append((m.start(), m.end()))
                        found.append((m.start(), eid, m.group(0), m.end()))
        return [(eid, s, a, b) for a, eid, s, b in sorted(found)]

    def mentions(self, doc: ParsedDocument) -> list[Mention]:
        """One mention per (block, entity): the first surface found."""
        return self.mentions_with_values(doc, None)[0]

    def mentions_with_values(self, doc: ParsedDocument, hubs: set[str] | None
                             ) -> tuple[list[Mention], dict[str, list[AttachedValue]]]:
        """Mentions as in mentions(); with `hubs` given (not None), every value in
        a block is attached to its nearest non-hub entity (kg.values.attach_values)
        and carried on that mention. Values in a block with no non-hub entity are
        returned per block_uid as the second item."""
        out: list[Mention] = []
        unattached: dict[str, list[AttachedValue]] = {}
        lang = doc.document.language.value
        for pb in doc.blocks:
            if pb.block.role.value != "body":
                continue
            spans = self.find_spans(pb.block.text, lang)
            by_entity: dict[str, list[AttachedValue]] = defaultdict(list)
            if hubs is not None:
                for av in attach_values(extract_values(pb.block.text, lang), spans, hubs):
                    if av.entity_id is None:
                        unattached.setdefault(pb.block.block_uid, []).append(av)
                    else:
                        by_entity[av.entity_id].append(av)
            seen = set()
            for eid, surface, _, _ in spans:
                if eid not in seen:
                    seen.add(eid)
                    out.append(Mention(pb.block.block_uid, eid, surface,
                                       tuple(by_entity.get(eid, ()))))
        return out, unattached


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


# ---------------------------------------------------------------- LLM fallback (M4 step 4)


@dataclass
class FallbackStats:
    blocks_called: int = 0
    failures: int = 0
    valid_first: int = 0
    returned: int = 0
    dropped: int = 0          # terms that do not occur in the block
    other: int = 0            # kept terms of type Other (counted, not linked)
    linked_existing: int = 0  # kept terms that match a registry alias
    new_terms: int = 0        # kept terms that became LLM-sourced entities


def occurs_in(term: str, text: str, language: str) -> bool:
    """The guard against invented entities: the term must occur in the block
    after the same normalization the registry matcher uses (Thai: compact form,
    markers removed; English: case-insensitive, space = hyphen)."""
    if not term.strip():
        return False
    if language == "th":
        return compact(_clean(term))[0] in compact(_clean(text))[0]
    words = [re.escape(w) for w in re.split(r"[\s-]+", term.strip()) if w]
    return re.search(r"(?<![\w-])" + r"[\s-]+".join(words) + r"(?![\w-])", text, re.I) \
        is not None


class LLMFallback:
    """Runs the LLM on blocks where the registry found few non-hub entities.
    Kept terms either link to an existing registry entity (by alias) or become
    LLM-sourced entities (id "llm:<type>:<lang>:<slug>", source "llm:<model>"),
    never merged into a registry entity (entity resolution is M6)."""

    def __init__(self, registry: EntityRegistry, client, max_entities: int | None) -> None:
        self.registry = registry
        self.client = client
        self.max_entities = max_entities
        self.new_entities: dict[str, EntityEntry] = {}
        self.stats = FallbackStats()

    def needs_llm(self, n_entities: int) -> bool:
        return self.max_entities is not None and n_entities <= self.max_entities

    def entities_for(self, text: str, language: str, registry_entities: set[str],
                     use_cache: bool = True) -> set[str]:
        """Entity ids the LLM adds for this text (empty when not needed)."""
        if not self.needs_llm(len(registry_entities)):
            return set()
        self.stats.blocks_called += 1
        res = self.client.extract_mentions(text, use_cache=use_cache)
        if res.mentions is None:
            self.stats.failures += 1
            return set()
        self.stats.valid_first += res.valid_first
        out = set()
        for m in res.mentions:
            self.stats.returned += 1
            if not occurs_in(m.term, text, language):
                self.stats.dropped += 1
                continue
            if m.type == "Other":
                self.stats.other += 1
                continue
            known = self.registry.get(language, m.term)
            if known is not None:
                self.stats.linked_existing += 1
                out.add(known.entity_id)
                continue
            key = EntityRegistry.key(language, m.term)
            eid = f"llm:{m.type.lower()}:{language}:{slug(key)}"
            e = self.new_entities.setdefault(eid, EntityEntry(eid, m.term, m.type, language))
            e.aliases.add(m.term)
            e.sources.add(f"llm:{getattr(self.client.s, 'model', 'unknown')}")
            self.stats.new_terms += 1
            out.add(eid)
        return out
