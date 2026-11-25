from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from kg.models import (
    Block,
    BlockKind,
    Edge,
    EdgeType,
    LineRange,
    Method,
    Provenance,
    Version,
)

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
HASH = "a" * 64


def test_line_range_must_be_ordered():
    assert LineRange(start=3, end=3).end == 3
    with pytest.raises(ValidationError):
        LineRange(start=5, end=4)
    with pytest.raises(ValidationError):
        LineRange(start=0, end=1)  # lines are 1-based


def test_version_id_uses_doc_key_and_short_hash():
    v = Version(
        doc_key="en-benefits-and-perks",
        file_hash="0123456789abcdef" + "0" * 48,
        version_label="git c953606 (2026-05-01)",
        source_file="E1.md",
        valid_from=T0,
    )
    assert v.version_id == "en-benefits-and-perks@0123456789ab"


def test_block_uid_changes_with_content_but_block_id_does_not():
    common = dict(
        doc_key="d", block_id="d/Paid Time Off/Sabbatical/p0", kind=BlockKind.PARAGRAPH,
        lines=LineRange(start=10, end=12), order=0,
    )
    old = Block(text="30 days", content_hash="1" * 64, **common)
    new = Block(text="6 weeks", content_hash="2" * 64, **common)
    assert old.block_id == new.block_id
    assert old.block_uid != new.block_uid


def test_block_text_cannot_be_empty():
    with pytest.raises(ValidationError):
        Block(doc_key="d", block_id="d/p0", kind=BlockKind.PARAGRAPH, text="",
              content_hash=HASH, lines=LineRange(start=1, end=1), order=0)


def test_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        LineRange(start=1, end=2, typo=True)


def test_llm_edge_needs_model_and_prompt_version():
    with pytest.raises(ValidationError):
        Provenance(method=Method.LLM)
    Provenance(method=Method.LLM, model="m", prompt_version="v1")


def test_depends_edge_needs_evidence():
    with pytest.raises(ValidationError):
        Edge(type=EdgeType.DEPENDS, source_id="a", target_id="b", valid_from=T0,
             provenance=Provenance(method=Method.LLM, model="m", prompt_version="v1"))


def test_edge_validity_order():
    with pytest.raises(ValidationError):
        Edge(type=EdgeType.NEXT, source_id="a", target_id="b", valid_from=T0,
             valid_to=datetime(2023, 1, 1, tzinfo=timezone.utc),
             provenance=Provenance(method=Method.PARSER))


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        Provenance(method=Method.REGEX, confidence=1.5)


def test_block_uid_defaults_to_position_and_hash_but_can_be_given():
    common = dict(doc_key="d", block_id="d::S::b0", kind=BlockKind.PARAGRAPH, text="x",
                  content_hash="ab" * 32, lines=LineRange(start=1, end=1), order=0)
    assert Block(**common).block_uid == "d::S::b0#" + "ab" * 6
    assert Block(**common, block_uid="d::Old::b3#keep").block_uid == "d::Old::b3#keep"
