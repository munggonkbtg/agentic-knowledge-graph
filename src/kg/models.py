"""Data models for the graph (see brief section 3).

These are plain pydantic models: they describe and validate the data in Python.
``store.py`` is the only place that turns them into Neo4j nodes and relationships.

Identity keys (decided in the M0/M1 plan):

* ``Document.doc_key``  – from front matter, the same across versions.
* ``Version.version_id`` – ``doc_key@<short file hash>``.
* ``Section.section_id`` – ``version_id::H2 > H3``: sections belong to one version.
* ``Block.block_id``     – ``doc_key::H2 > H3::b<position>``: *where* the block is.
  " > " separates headings because Thai section numbers contain "/" (มาตรา ๑๑/๑).
* ``Block.block_uid``    – ``block_id#<short content hash>``: the node key. The same
  position with the same text reuses its node in a new version; edited text gets a
  new node, and the diff (M2) links it to the old one.

Because one Block node can appear in several versions, its line range and order are
stored on the Section-[:CONTAINS]->Block relationship (one per version), not on the
node. The ``Block`` model below still carries them for the version being parsed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

HASH_PREFIX_LEN = 12  # characters of the SHA-256 hex digest used inside IDs
PATH_SEP = " > "
ROOT_PATH = "_"  # path key of the document root (text before the first heading)


def path_key(heading_path: tuple[str, ...]) -> str:
    return PATH_SEP.join(heading_path) or ROOT_PATH


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- enums


class Language(StrEnum):
    TH = "th"
    EN = "en"


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST = "list"
    LIST_ITEM = "list_item"  # one item of a long list that was split
    BLOCKQUOTE = "blockquote"
    CODE = "code"
    HTML = "html"


class BlockRole(StrEnum):
    """What the block is for, independent of its Markdown kind."""

    BODY = "body"
    FOOTNOTE = "footnote"  # an entry in a footnote list (amendment history)


class Method(StrEnum):
    """How an edge was produced (provenance)."""

    PARSER = "parser"
    METADATA = "metadata"
    REGEX = "regex"
    NER = "ner"
    EMBEDDING = "embedding"
    LLM = "llm"
    HUMAN = "human"


class ReviewStatus(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class EdgeType(StrEnum):
    HAS_VERSION = "HAS_VERSION"
    CONTAINS = "CONTAINS"
    NEXT = "NEXT"
    SUPERSEDES = "SUPERSEDES"
    REFERENCES = "REFERENCES"
    MENTIONS = "MENTIONS"
    ALIAS_OF = "ALIAS_OF"
    DEPENDS = "DEPENDS"


# ---------------------------------------------------------------- nodes


class LineRange(_Model):
    """1-based, inclusive line numbers in the original file (front matter counted)."""

    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> LineRange:
        if self.end < self.start:
            raise ValueError(f"line range end {self.end} is before start {self.start}")
        return self


class Document(_Model):
    doc_key: str = Field(min_length=1)
    title: str
    language: Language
    # Access rights are stored but not enforced in this phase (no access control).
    access: tuple[str, ...] = ()


class Version(_Model):
    doc_key: str = Field(min_length=1)
    file_hash: str = Field(min_length=HASH_PREFIX_LEN)  # SHA-256 hex of the raw file
    version_label: str  # free text from front matter, e.g. "git c953606 (2026-05-01)"
    source_file: str  # file name only, so reruns from another folder match
    source_url: str | None = None
    license: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def version_id(self) -> str:
        return f"{self.doc_key}@{self.file_hash[:HASH_PREFIX_LEN]}"


class Section(_Model):
    version_id: str
    heading_path: tuple[str, ...]  # normalized headings from the top, () = document root
    level: int = Field(ge=0, le=6)  # 0 for the document root
    title: str  # heading text as written
    lines: LineRange

    @computed_field  # type: ignore[prop-decorator]
    @property
    def section_id(self) -> str:
        return f"{self.version_id}::{path_key(self.heading_path)}"


class Block(_Model):
    doc_key: str
    block_id: str = Field(min_length=1)
    kind: BlockKind
    role: BlockRole = BlockRole.BODY
    text: str = Field(min_length=1)  # original text, unchanged
    content_hash: str = Field(min_length=HASH_PREFIX_LEN)  # SHA-256 of normalized text
    lines: LineRange
    order: int = Field(ge=0)  # position within its section
    footnotes: tuple[str, ...] = ()  # footnote markers removed before hashing
    embedding: tuple[float, ...] | None = None  # filled later (model not chosen yet)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def block_uid(self) -> str:
        return f"{self.block_id}#{self.content_hash[:HASH_PREFIX_LEN]}"


class Alias(_Model):
    """A name exactly as written in the text."""

    alias_id: str
    surface: str = Field(min_length=1)
    language: Language | None = None


class Entity(_Model):
    """What aliases refer to: a unit, system, regulation, defined value..."""

    entity_id: str
    entity_type: str  # the list of types is still an open question (M4)
    canonical_name: str


# ---------------------------------------------------------------- edges


class Provenance(_Model):
    method: Method
    evidence_block: str | None = None  # block_uid the edge was derived from
    evidence_span: str | None = None  # quoted text supporting the edge
    model: str | None = None  # LLM / NER model name, when one was used
    prompt_version: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _llm_needs_model(self) -> Provenance:
        if self.method == Method.LLM and not (self.model and self.prompt_version):
            raise ValueError("LLM-produced edges must record model and prompt_version")
        return self


class Edge(_Model):
    type: EdgeType
    source_id: str  # key of the start node
    target_id: str  # key of the end node
    provenance: Provenance
    valid_from: datetime
    valid_to: datetime | None = None  # None while the edge is valid
    review_status: ReviewStatus | None = None
    properties: dict[str, Any] = Field(default_factory=dict)  # e.g. cited section

    @model_validator(mode="after")
    def _validity(self) -> Edge:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to is before valid_from")
        if self.type == EdgeType.DEPENDS and not self.provenance.evidence_span:
            raise ValueError("DEPENDS edges must quote evidence")
        return self
