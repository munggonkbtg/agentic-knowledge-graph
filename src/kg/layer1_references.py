"""Layer 1: REFERENCES from a block to the logical document it cites.

No LLM. Rules approved on 2026-11-25 (docs/plan.md, M3):

1. A section cited inside the same act gets an edge to its own document with
   ``self_reference = true``.
2. A bare "มาตรา N" (no law named next to it) goes to the law named most recently
   before it in the same block; if none, inside an act it is the act itself, and
   inside a regulation it is the act the regulation is issued under (from its
   title / first blocks), with lower confidence.
3. A law that is not in the store gets a stub ``Document`` (``in_store = false``)
   so the citation is kept.
4. One edge per cited section (``cited_section`` e.g. "มาตรา 118 (6)"), plus one
   document-level edge (``cited_section = ""``) for a law named without any
   section.

Matching works on a *compact* form of the text: Unicode NFC, Thai digits turned
into Arabic, all whitespace removed. Thai legal text is spaced inconsistently
("พระราชบัญญัติ คุ้มครองแรงงาน"), so names are compared without spaces. Every
compact character remembers its position in the original block, so the
evidence span quotes the original text.

English documents: Markdown links (to a known handbook file -> that document,
with the #anchor as the cited section; any other URL -> an external stub) and
the exact title of another English document in the text.

Footnote entries (``role = footnote``) are skipped: they record amendment
history, not citations a reader relies on.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_left
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import yaml

from kg.config import Layer1Settings
from kg.layer0_structure import THAI_TO_ARABIC, ParsedDocument
from kg.models import BlockRole

LAW_KEYWORDS = "พระราชบัญญัติ|พระราชกำหนด|พระราชกฤษฎีกา"
REG_KEYWORDS = "กฎกระทรวง|ระเบียบ|ประกาศ"
LAW_WITH_YEAR = re.compile(
    rf"(?:{LAW_KEYWORDS})(?!นี้|ฉบับนี้)(?:(?!{LAW_KEYWORDS}|มาตรา).){{1,80}}?พ\.ศ\.\d{{4}}")
# A regulation named with its year; the name may contain the act it is issued
# under, and amending regulations end in "(ฉบับที่ N) พ.ศ. YYYY".
REG_WITH_YEAR = re.compile(
    rf"(?:{REG_KEYWORDS})(?!นี้|ฉบับนี้)(?:(?!มาตรา\d|ข้อ\d|{REG_KEYWORDS}).){{1,200}}?"
    rf"พ\.ศ\.\d{{4}}\)?(?:\(ฉบับที่\d+\)พ\.ศ\.\d{{4}}|พ\.ศ\.\d{{4}})*")
# A ministerial regulation named without a year, e.g. "กฎกระทรวงคุ้มครองแรงงานในงาน
# เกษตรกรรม". Found in the original text: the name ends at the next space.
REG_NO_YEAR = re.compile(r"กฎกระทรวง(?!นี้|ฉบับนี้|ฉบับที่|ที่|ว่า)[^\s()\[\],]{6,}")
CODE = re.compile(r"ประมวลกฎหมาย(?:วิธีพิจารณาความ)?(?:อาญา|แพ่ง(?:และพาณิชย์)?)")
SELF = re.compile(rf"(?:{LAW_KEYWORDS}|{REG_KEYWORDS})(?:ฉบับ)?นี้")
PARAGRAPH = r"(?:วรรค(?:หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ|\d+)(?:\(\d+\))*)?"
# "มาตรา 159 วรรคสาม": the paragraph (วรรค) is part of the citation but not of
# cited_section, so the law after it ("… แห่งพระราชบัญญัติ…") is still adjacent.
SECTION = re.compile(rf"(มาตรา|ข้อ|หมวด)(\d+(?:/\d+)?)((?:\(\d+\))*){PARAGRAPH}")
ACT_LIKE = re.compile(rf"(?:{LAW_KEYWORDS}|ประมวลกฎหมาย|กฎหมายว่าด้วย)")
RUN_GAP = re.compile(r"(?:,|และ|หรือ|ถึง|รวมทั้ง)*")
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
UPDATE_SUFFIX = re.compile(r"\s*\((?:ฉบับ\s*)?Update[^)]*\).*$")


# ---------------------------------------------------------------- compact text


def compact(text: str) -> tuple[str, list[int]]:
    """NFC, Thai digits -> Arabic, whitespace removed. Returns the compact text and,
    for each of its characters, the index in the NFC original."""
    text = unicodedata.normalize("NFC", text)
    out, idx = [], []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        out.append(ch.translate(THAI_TO_ARABIC))
        idx.append(i)
    return "".join(out), idx


def base_name(compact_name: str) -> str:
    """A law name without "(ฉบับที่ N)" and "พ.ศ. YYYY"."""
    return re.sub(r"\(ฉบับที่\d+\)|พ\.ศ\.\d{4}", "", compact_name)


def law_name_from_title(title: str) -> str:
    """'พระราชบัญญัติ… พ.ศ. 2541 (ฉบับ Update ล่าสุด)' -> 'พระราชบัญญัติ… พ.ศ. 2541'."""
    return UPDATE_SUFFIX.sub("", title).strip()


def slug(text: str) -> str:
    """Letters (Thai vowel marks included), digits and dots; anything else -> '-'."""
    keep = "".join(ch if unicodedata.category(ch)[0] in "LMN" or ch == "." else "-"
                   for ch in unicodedata.normalize("NFC", text.lower()))
    return re.sub(r"-+", "-", keep).strip("-")


# ---------------------------------------------------------------- registry


@dataclass(frozen=True)
class RegistryEntry:
    doc_key: str
    title: str
    language: str
    file_names: tuple[str, ...] = ()  # basenames of source_url / source_file


class Registry:
    """Names by which a document can be cited, built from the graph's Document
    nodes plus reviewed extra aliases (registry/aliases.yaml)."""

    def __init__(self, entries: list[RegistryEntry],
                 extra_aliases: dict[str, list[str]] | None = None) -> None:
        # sorted, so the result never depends on the order the entries came in
        entries = sorted(entries, key=lambda e: e.doc_key)
        self.entries = {e.doc_key: e for e in entries}
        self.by_name: dict[str, str] = {}
        self.by_base: dict[str, set[str]] = {}
        self.by_file: dict[str, str] = {}
        self.en_titles: dict[str, str] = {}
        for e in entries:
            names = [law_name_from_title(e.title)] + list((extra_aliases or {}).get(e.doc_key, []))
            for name in names:
                c, _ = compact(name)
                if not c:
                    continue
                self.by_name.setdefault(c, e.doc_key)
                # a long title is cited by its first part: "กฎกระทรวง ฉบับที่ 9 (พ.ศ. 2541)"
                short = REG_WITH_YEAR.match(c) or LAW_WITH_YEAR.match(c)
                if short and short.group(0) != c:
                    self.by_name.setdefault(short.group(0), e.doc_key)
                if re.match(LAW_KEYWORDS, c) and base_name(c) != c:
                    self.by_base.setdefault(base_name(c), set()).add(e.doc_key)
            for f in e.file_names:
                self.by_file.setdefault(f.lower(), e.doc_key)
            if e.language == "en" and len(e.title.split()) >= 2:
                self.en_titles[e.title] = e.doc_key

    def is_act(self, doc_key: str) -> bool:
        e = self.entries.get(doc_key)
        return bool(e and compact(e.title)[0].startswith("พระราชบัญญัติ"))

    def principal(self, base: str) -> str | None:
        """Document for a law named without year. With several candidates (the act
        and its amending acts share a base name), the one without "(ฉบับที่ N)"."""
        keys = sorted(self.by_base.get(base, ()))
        if len(keys) == 1:
            return keys[0]
        plain = [k for k in keys
                 if "(ฉบับที่" not in compact(law_name_from_title(self.entries[k].title))[0]]
        return plain[0] if len(plain) == 1 else None


def load_extra_aliases(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): [str(a) for a in (v or [])] for k, v in data.items()}


# ---------------------------------------------------------------- extraction


@dataclass(frozen=True)
class Reference:
    block_uid: str
    target: str  # doc_key (registry or external stub)
    cited_section: str  # "" for a document-level reference
    resolution: str  # explicit | same_block_context | self_document | issued_under |
    #                  name_without_year | link | title_mention
    confidence: float
    evidence_span: str
    self_reference: bool


@dataclass
class Extraction:
    references: list[Reference] = field(default_factory=list)
    stubs: dict[str, dict[str, str]] = field(default_factory=dict)  # doc_key -> props
    unresolved: list[str] = field(default_factory=list)  # evidence of sections with no target


@dataclass(frozen=True)
class _Mention:
    start: int
    end: int
    target: str
    self_ref: bool
    resolution: str  # how the *name* was resolved: explicit | name_without_year | subject_name
    act_like: bool = False  # an act or code (numbers its parts with มาตรา, never ข้อ)


def _span(original: str, idx: list[int], start: int, end: int, limit: int = 240) -> str:
    text = original[idx[start]: idx[end - 1] + 1]
    return text if len(text) <= limit else text[:limit] + "…"


class ReferenceExtractor:
    def __init__(self, registry: Registry, cfg: Layer1Settings) -> None:
        self.registry = registry
        self.conf = cfg.confidence

    # -- law names in one block -----------------------------------------------

    def _external(self, name: str, out: Extraction, language: str = "th") -> str:
        # key from the compact form, so spacing and digit style do not split one law
        key = "ext-" + slug(compact(name)[0])
        out.stubs.setdefault(key, {"doc_key": key, "title": name, "language": language})
        return key

    def _mentions(self, c: str, own: str, out: Extraction, original: str,
                  idx: list[int]) -> list[_Mention]:
        found: list[_Mention] = []
        taken: list[tuple[int, int]] = []

        def free(s: int, e: int) -> bool:
            return all(e <= a or s >= b for a, b in taken)

        def act_like(key: str, name: str) -> bool:
            return self.registry.is_act(key) or bool(ACT_LIKE.match(name))

        def add(s: int, e: int, key: str, how: str, name: str) -> None:
            found.append(_Mention(s, e, key, key == own, how, act_like(key, name)))
            taken.append((s, e))

        def resolve(name_compact: str, span: tuple[int, int]) -> str:
            return (self.registry.by_name.get(name_compact)
                    or self._external(_span(original, idx, *span), out))

        def to_compact(o_start: int, o_end: int) -> tuple[int, int]:
            s = bisect_left(idx, o_start)
            e = bisect_left(idx, o_end)
            return s, e

        for m in SELF.finditer(c):
            found.append(_Mention(m.start(), m.end(), own, True, "explicit",
                                  self.registry.is_act(own)))
            taken.append(m.span())
        for m in REG_WITH_YEAR.finditer(c):
            name = m.group(0)
            # "ระเบียบ" / "ประกาศ" are also plain nouns: only a proper title counts
            if not free(*m.span()) or "วันที่" in name or (
                    not name.startswith("กฎกระทรวง") and "ว่าด้วย" not in name
                    and "ฉบับที่" not in name):
                continue
            add(m.start(), m.end(), resolve(name, m.span()), "explicit", name)
        for m in LAW_WITH_YEAR.finditer(c):
            if free(*m.span()):
                add(m.start(), m.end(), resolve(m.group(0), m.span()), "explicit", m.group(0))
        for m in CODE.finditer(c):
            if free(*m.span()):
                add(m.start(), m.end(), resolve(m.group(0), m.span()), "explicit", m.group(0))
        for m in REG_NO_YEAR.finditer(original):
            s, e = to_compact(*m.span())
            if s < e and free(s, e):
                add(s, e, resolve(c[s:e], (s, e)), "name_without_year", c[s:e])
        for m in re.finditer("กฎหมายว่าด้วย", c):
            if not free(*m.span()):
                continue
            keys, end = self._subject_targets(c, m.end(), out)
            for key in keys:
                found.append(_Mention(m.start(), end, key, key == own, "subject_name", True))
            if keys:
                taken.append((m.start(), end))
        for base in sorted(self.registry.by_base, key=lambda b: (-len(b), b)):
            for m in re.finditer(re.escape(base), c):
                if not free(*m.span()):
                    continue
                key = self.registry.principal(base)
                if key is None:
                    continue
                add(m.start(), m.end(), key, "name_without_year", base)
        return sorted(found, key=lambda x: x.start)

    def _topics(self, out: Extraction) -> list[tuple[str, str]]:
        """(topic, doc_key) for every law known so far: the registry, plus laws
        already named (stubs) earlier in this document. Topic = compact name
        without its keyword, "(ฉบับที่ N)" and year."""
        # One document per topic, the registry first; amending acts ("(ฉบับที่ N)")
        # share the topic of the act they amend and are never a subject target.
        # Sorted by length, then text, so the result never depends on set order.
        by_topic: dict[str, str] = {}
        for base in sorted(self.registry.by_base):
            key = self.registry.principal(base)
            topic = re.sub(rf"^(?:{LAW_KEYWORDS})", "", base)
            if key and topic:
                by_topic.setdefault(topic, key)
        for key in sorted(out.stubs):
            full = compact(out.stubs[key]["title"])[0]
            name = base_name(full)
            if re.match(LAW_KEYWORDS, name) and "(ฉบับที่" not in full:
                topic = re.sub(rf"^(?:{LAW_KEYWORDS})", "", name)
                if topic:
                    by_topic.setdefault(topic, key)
        return sorted(by_topic.items(), key=lambda p: (-len(p[0]), p[0]))

    def _subject_targets(self, c: str, pos: int, out: Extraction) -> tuple[list[str], int]:
        """After "กฎหมายว่าด้วย" at ``pos``: the known laws whose topic the text
        continues with ("การคุ้มครองแรงงานและ…" -> the labour protection act, then
        the next subject after "และ"). A subject that matches no known law gives no
        edge: a Thai subject phrase has no clear end, so guessing a name would
        invent wrong documents."""
        keys, topics = [], self._topics(out)
        while True:
            if c.startswith("การ", pos):
                pos += 3
            hit = next(((t, k) for t, k in topics if c.startswith(t, pos)), None)
            if hit is None:
                return keys, pos
            keys.append(hit[1])
            pos += len(hit[0])
            if not c.startswith("และ", pos):
                return keys, pos
            pos += 3

    # -- one document -----------------------------------------------------------

    def issued_under(self, doc: ParsedDocument, out: Extraction) -> str | None:
        """For a regulation: the act it is issued under (first law named in its
        title or first blocks)."""
        own = doc.document.doc_key
        if self.registry.is_act(own):
            return None
        texts = [doc.document.title] + [pb.block.text for pb in doc.blocks[:5]]
        for text in texts:
            c, idx = compact(text)
            for m in self._mentions(c, own, out, unicodedata.normalize("NFC", text), idx):
                if not m.self_ref:
                    return m.target
        return None

    def extract(self, doc: ParsedDocument) -> Extraction:
        out = Extraction()
        own = doc.document.doc_key
        default_act = self.issued_under(doc, out)
        for pb in doc.blocks:
            if pb.block.role == BlockRole.FOOTNOTE:
                continue
            self._thai(pb.block.block_uid, pb.block.text, own, default_act, out)
            self._english(pb.block.block_uid, pb.block.text, own, out)
        # one edge per (block, target, section)
        seen, unique = set(), []
        for r in out.references:
            k = (r.block_uid, r.target, r.cited_section)
            if k not in seen:
                seen.add(k)
                unique.append(r)
        out.references = unique
        return out

    def _thai(self, uid: str, text: str, own: str, default_act: str | None,
              out: Extraction) -> None:
        original = unicodedata.normalize("NFC", text)
        c, idx = compact(original)
        mentions = self._mentions(c, own, out, original, idx)
        sections = list(SECTION.finditer(c))

        # group sections joined only by connectors into runs ("มาตรา 70 มาตรา 75 หรือมาตรา 76")
        runs: list[list[re.Match]] = []
        for m in sections:
            if runs and RUN_GAP.fullmatch(c[runs[-1][-1].end():m.start()]):
                runs[-1].append(m)
            else:
                runs.append([m])

        used: set[_Mention] = set()
        own_is_act = self.registry.is_act(own)
        for run in runs:
            start, end = run[0].start(), run[-1].end()
            target, how, span = None, "", (start, end)
            keyword = run[0].group(1)
            # Acts number their parts with มาตรา, regulations with ข้อ. So "this
            # regulation" is never the target of a มาตรา citation, and an act or
            # code is never the target of a ข้อ citation.
            usable = [m for m in mentions
                      if not (m.self_ref and keyword == "มาตรา" and not own_is_act)
                      and not (keyword == "ข้อ" and m.act_like)]
            after = next((m for m in usable if m.start >= end
                          and c[end:m.start] in ("", "แห่ง", "ของ", "ตาม")), None)
            before = next((m for m in reversed(usable) if m.end <= start
                           and c[m.end:start] in ("", ",")), None)
            context = next((m for m in reversed(usable) if m.end <= start), None)
            # In a list "law A มาตรา X law B มาตรา Y", each section belongs to the law
            # right before it. The law after it wins only when joined by แห่ง / ของ /
            # ตาม ("มาตรา 6 แห่งพระราชบัญญัติ…"), or when no law stands right before.
            if after and (c[end:after.start] != "" or before is None):
                target, how, span, used_m = after.target, after.resolution, (start, after.end), after
            elif before:
                target, how, span, used_m = before.target, before.resolution, (before.start, end), before
            elif context:
                target, how, used_m = context.target, "same_block_context", context
            else:
                used_m = None
                if keyword in ("ข้อ", "หมวด") or own_is_act:
                    target, how = own, "self_document"
                elif default_act:
                    target, how = default_act, "issued_under"
            if used_m is not None:
                used.add(used_m)
            evidence = _span(original, idx, *span)
            if target is None:
                out.unresolved.append(evidence)
                continue
            conf = getattr(self.conf, how)
            for m in run:
                section = f"{m.group(1)} {m.group(2)}" + (
                    " " + m.group(3) if m.group(3) else "")
                out.references.append(Reference(uid, target, section, how, conf, evidence,
                                                target == own))
        # a law named without any section: one document-level edge
        for m in mentions:
            if m in used or m.self_ref:
                continue
            out.references.append(Reference(uid, m.target, "", m.resolution,
                                            getattr(self.conf, m.resolution),
                                            _span(original, idx, m.start, m.end), False))

    def _english(self, uid: str, text: str, own: str, out: Extraction) -> None:
        link_spans = []
        for m in LINK.finditer(text):
            label, url = m.group(1), m.group(2)
            link_spans.append(m.span())
            if url.startswith("mailto:"):
                continue
            parsed = urlparse(url)
            anchor = f"#{parsed.fragment}" if parsed.fragment else ""
            if not parsed.scheme and not parsed.path:  # "#anchor" on the same page
                target = own
            elif parsed.path.lower().endswith(".md"):
                name = PurePosixPath(parsed.path).name.lower()
                target = self.registry.by_file.get(name) or self._external(
                    f"handbook/{name}", out, "en")
            else:
                no_frag = url.split("#", 1)[0]
                key = "ext-url-" + hashlib.sha1(no_frag.encode()).hexdigest()[:10]
                out.stubs.setdefault(key, {"doc_key": key, "title": label or no_frag,
                                           "language": "en", "url": no_frag})
                target, anchor = key, ""
            out.references.append(Reference(uid, target, anchor, "link", self.conf.link,
                                            m.group(0)[:240], target == own))
        for title, key in self.registry.en_titles.items():
            if key == own:
                continue
            for m in re.finditer(re.escape(title), text):
                if any(a <= m.start() < b for a, b in link_spans):
                    continue
                out.references.append(Reference(uid, key, "", "title_mention",
                                                self.conf.title_mention, title, False))
