"""Layer 0: split a Markdown file into Document -> Version -> Section -> Block.

No LLM and no database here: this module only reads a file and returns validated
models. ``store.py`` writes them to Neo4j.

Terms used below:
* *front matter*: the YAML block between the two ``---`` lines at the top of a file.
* *token*: one piece of the Markdown structure as markdown-it-py reports it
  (heading, paragraph, list...). Each block token carries ``map = [start, end)``,
  0-based line numbers relative to the text we gave the parser.
* *normalized text*: text with differences that do not change meaning removed
  (Unicode form, whitespace, footnote markers, Thai vs Arabic digits). Two blocks
  with the same normalized text get the same ``content_hash``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from markdown_it import MarkdownIt

from kg.config import Layer0Settings
from kg.models import (
    Block,
    BlockKind,
    BlockRole,
    Document,
    Language,
    LineRange,
    Section,
    Version,
    path_key,
)

THAI_TO_ARABIC = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_WS = re.compile(r"\s+")

# Top-level token types that start a block, and the kind we record.
_BLOCK_TOKENS: dict[str, BlockKind] = {
    "paragraph_open": BlockKind.PARAGRAPH,
    "bullet_list_open": BlockKind.LIST,
    "ordered_list_open": BlockKind.LIST,
    "table_open": BlockKind.TABLE,
    "blockquote_open": BlockKind.BLOCKQUOTE,
    "fence": BlockKind.CODE,
    "code_block": BlockKind.CODE,
    "html_block": BlockKind.HTML,
}

REQUIRED_FRONT_MATTER = ("doc_key", "title", "language")


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSection:
    section: Section
    parent_id: str | None  # None: the root section, contained by the Version


@dataclass(frozen=True)
class ParsedBlock:
    block: Block
    section_id: str


@dataclass(frozen=True)
class ParsedDocument:
    document: Document
    version: Version
    sections: tuple[ParsedSection, ...]
    blocks: tuple[ParsedBlock, ...]  # in document order


# ------------------------------------------------------------ normalization


class Normalizer:
    def __init__(self, cfg: Layer0Settings) -> None:
        self.cfg = cfg
        self._marker = re.compile(cfg.footnote_marker_pattern)

    def footnote_markers(self, text: str) -> tuple[str, ...]:
        return tuple(self._marker.findall(text)) if self.cfg.strip_footnote_markers else ()

    def normalize(self, text: str) -> str:
        text = unicodedata.normalize("NFC", text)
        if self.cfg.strip_footnote_markers:
            text = self._marker.sub(" ", text)
        if self.cfg.thai_digits_to_arabic:
            text = text.translate(THAI_TO_ARABIC)
        return _WS.sub(" ", text).strip()

    def content_hash(self, text: str) -> str:
        return hashlib.sha256(self.normalize(text).encode("utf-8")).hexdigest()


# ------------------------------------------------------------ front matter


def split_front_matter(lines: list[str]) -> tuple[dict, int]:
    """Return (front matter dict, index of the first body line)."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            meta = yaml.safe_load("\n".join(lines[1:i])) or {}
            if not isinstance(meta, dict):
                raise ParseError("front matter is not a key/value mapping")
            return meta, i + 1
    raise ParseError("front matter starts with '---' but is never closed")


# ------------------------------------------------------------ parsing


def _markdown() -> MarkdownIt:
    return MarkdownIt("commonmark").enable("table")


@dataclass
class _OpenSection:
    level: int
    key: str  # normalized heading
    section_id: str
    title: str
    start: int  # 1-based file line of the heading
    heading_path: tuple[str, ...]
    parent_id: str | None


def parse_file(path: Path, cfg: Layer0Settings, valid_from: datetime) -> ParsedDocument:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    meta, body_start = split_front_matter(lines)
    missing = [k for k in REQUIRED_FRONT_MATTER if not meta.get(k)]
    if missing:
        raise ParseError(f"{path.name}: front matter is missing {', '.join(missing)}")

    norm = Normalizer(cfg)
    doc_key = str(meta["doc_key"])
    document = Document(doc_key=doc_key, title=str(meta["title"]), language=Language(meta["language"]))
    version = Version(
        doc_key=doc_key,
        file_hash=hashlib.sha256(raw).hexdigest(),
        version_label=str(meta.get("version", "")),
        source_file=path.name,
        source_url=meta.get("source_url"),
        license=meta.get("license"),
        valid_from=valid_from,
    )
    vid = version.version_id

    tokens = _markdown().parse("\n".join(lines[body_start:]) + "\n")

    def file_lines(token_map: list[int]) -> tuple[int, int]:
        """Token map -> 1-based inclusive file lines, trailing blank lines dropped."""
        start = body_start + token_map[0] + 1
        end = body_start + token_map[1]
        while end > start and not lines[end - 1].strip():
            end -= 1
        return start, end

    top = [t for t in tokens if t.level == 0]
    h1_count = sum(1 for t in top if t.type == "heading_open" and t.tag == "h1")
    first_heading = next((t for t in top if t.type == "heading_open"), None)
    title_is_root = (
        not cfg.title_heading_in_path
        and h1_count == 1
        and first_heading is not None
        and first_heading.tag == "h1"
    )

    root_id = f"{vid}::{path_key(())}"
    opened: list[_OpenSection] = [
        _OpenSection(0, "", root_id, document.title, body_start + 1, (), None)
    ]
    stack: list[_OpenSection] = []  # currently open headings, outermost first
    seen_paths: dict[tuple[str, ...], int] = {}
    block_counts: dict[str, int] = {}
    blocks: list[ParsedBlock] = []

    for i, tok in enumerate(tokens):
        if tok.level != 0:
            continue
        if tok.type == "heading_open":
            title = tokens[i + 1].content.strip()
            start, _ = file_lines(tok.map)
            if title_is_root and tok is first_heading:
                opened[0].title = title
                opened[0].start = start
                continue
            level = int(tok.tag[1])
            while stack and stack[-1].level >= level:
                stack.pop()
            key = norm.normalize(title)
            heading_path = tuple(s.key for s in stack) + (key,)
            n = seen_paths.get(heading_path, 0) + 1
            seen_paths[heading_path] = n
            if n > 1:  # same heading twice under the same parent
                key = f"{key} ~{n}"
                heading_path = heading_path[:-1] + (key,)
            parent_id = stack[-1].section_id if stack else root_id
            sec = _OpenSection(level, key, f"{vid}::{path_key(heading_path)}", title,
                               start, heading_path, parent_id)
            stack.append(sec)
            opened.append(sec)
            continue

        kind = _BLOCK_TOKENS.get(tok.type)
        if kind is None or tok.map is None:
            continue  # e.g. horizontal rules, closing tokens
        current = stack[-1] if stack else opened[0]
        role = (BlockRole.FOOTNOTE
                if any(h in cfg.footnote_sections for h in current.heading_path)
                else BlockRole.BODY)
        start, end = file_lines(tok.map)

        # A long top-level list becomes one block per top-level item.
        pieces: list[tuple[BlockKind, int, int]] = [(kind, start, end)]
        limit = cfg.split_list_over_chars
        if kind == BlockKind.LIST and limit is not None:
            whole = "\n".join(lines[start - 1 : end])
            if len(whole) > limit:
                pieces = [(BlockKind.LIST_ITEM, *file_lines(t.map))
                          for t in _top_level_items(tokens, i)]

        for piece_kind, p_start, p_end in pieces:
            block_text = "\n".join(lines[p_start - 1 : p_end])
            order = block_counts.get(current.section_id, 0)
            block_counts[current.section_id] = order + 1
            block = Block(
                doc_key=doc_key,
                block_id=f"{doc_key}::{path_key(current.heading_path)}::b{order}",
                kind=piece_kind,
                role=role,
                text=block_text,
                content_hash=norm.content_hash(block_text),
                lines=LineRange(start=p_start, end=p_end),
                order=order,
                footnotes=norm.footnote_markers(block_text),
            )
            blocks.append(ParsedBlock(block, current.section_id))

    sections = _close_sections(opened, vid, lines)
    return ParsedDocument(document, version, sections, tuple(blocks))


def _top_level_items(tokens: list, list_open_index: int) -> list:
    """The list_item_open tokens that belong directly to the list opened at
    ``tokens[list_open_index]`` (nested lists stay inside their item)."""
    opener = tokens[list_open_index]
    item_level = opener.level + 1
    closer = opener.type.replace("_open", "_close")
    items = []
    for tok in tokens[list_open_index + 1 :]:
        if tok.type == closer and tok.level == opener.level:
            break
        if tok.type == "list_item_open" and tok.level == item_level:
            items.append(tok)
    return items


def _close_sections(
    opened: list[_OpenSection], vid: str, lines: list[str]
) -> tuple[ParsedSection, ...]:
    """A section ends just before the next heading of the same or higher level."""
    last_line = len(lines)
    while last_line > 1 and not lines[last_line - 1].strip():
        last_line -= 1
    result = []
    for idx, sec in enumerate(opened):
        end = last_line
        if sec.level > 0:
            for later in opened[idx + 1 :]:
                if later.level <= sec.level:
                    end = later.start - 1
                    break
        while end > sec.start and not lines[end - 1].strip():
            end -= 1
        section = Section(
            version_id=vid,
            heading_path=sec.heading_path,
            level=sec.level,
            title=sec.title,
            lines=LineRange(start=sec.start, end=max(end, sec.start)),
        )
        assert section.section_id == sec.section_id
        result.append(ParsedSection(section, sec.parent_id))
    return tuple(result)


def parse_corpus(folder: Path, cfg: Layer0Settings, valid_from: datetime) -> list[ParsedDocument]:
    """Parse every ``*.md`` file in a folder (sorted by name, so order is stable)."""
    files = sorted(folder.glob("*.md"))
    if not files:
        raise ParseError(f"no .md files in {folder}")
    return [parse_file(f, cfg, valid_from) for f in files]
