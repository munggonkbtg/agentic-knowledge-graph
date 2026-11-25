"""Layer 0 parser tests. Most use the real pilot files as fixtures."""

from pathlib import Path

import pytest

from conftest import INITIAL, T0, UPLOADS, pilot_files
from kg.config import Layer0Settings
from kg.layer0_structure import Normalizer, ParseError, parse_corpus, parse_file
from kg.models import BlockKind

pytestmark = pytest.mark.usefixtures("need_data")

T1_OLD = INITIAL / "T1_labour_protection_act_2541__2017-08-31.md"
T1_NEW = UPLOADS / "event3" / "T1_labour_protection_act_2541.md"
T4 = INITIAL / "T4_regulation_workplace_inspection_2542.md"
E1_OLD = INITIAL / "E1_benefits_and_perks__2024-01-05_before_sabbatical_change.md"
E3_OLD = INITIAL / "E3_making_a_career__2024-05-14_before_severance_move.md"


def _blocks_under(doc, path_suffix: str):
    return [pb.block for pb in doc.blocks if pb.block.block_id.split("::")[1].endswith(path_suffix)]


# ------------------------------------------------------------- whole corpus


def test_all_eight_initial_files_parse(layer0_cfg):
    docs = parse_corpus(INITIAL, layer0_cfg, T0)
    assert len(docs) == 8
    assert all(d.blocks for d in docs)
    assert len({d.document.doc_key for d in docs}) == 8


@pytest.mark.parametrize("path", pilot_files(), ids=lambda p: p.name[:20])
def test_line_ranges_read_back_exact_text(path, layer0_cfg):
    doc = parse_file(path, layer0_cfg, T0)
    lines = path.read_text(encoding="utf-8").splitlines()
    for pb in doc.blocks:
        b = pb.block
        assert "\n".join(lines[b.lines.start - 1 : b.lines.end]) == b.text
        assert b.text.strip()
        assert not b.text.lstrip().startswith("#"), "a heading leaked into a block"


@pytest.mark.parametrize("path", pilot_files(), ids=lambda p: p.name[:20])
def test_ids_are_unique_within_a_file(path, layer0_cfg):
    doc = parse_file(path, layer0_cfg, T0)
    ids = [pb.block.block_id for pb in doc.blocks]
    sids = [ps.section.section_id for ps in doc.sections]
    assert len(ids) == len(set(ids))
    assert len(sids) == len(set(sids))
    # every block belongs to a section of this version
    assert {pb.section_id for pb in doc.blocks} <= set(sids)


def test_rerun_gives_identical_ids_and_hashes(layer0_cfg):
    def snapshot():
        return [
            (pb.block.block_uid, pb.block.lines.start, pb.block.lines.end, pb.section_id)
            for d in parse_corpus(INITIAL, layer0_cfg, T0)
            for pb in d.blocks
        ]

    assert snapshot() == snapshot()


def test_front_matter_lines_are_counted(layer0_cfg):
    doc = parse_file(E1_OLD, layer0_cfg, T0)
    first = doc.blocks[0].block
    # front matter is lines 1-9 and the title heading is line 10
    assert first.lines.start > 10


# ------------------------------------------------------------- headings


def test_single_title_heading_is_not_in_paths(layer0_cfg):
    doc = parse_file(E3_OLD, layer0_cfg, T0)
    root = doc.sections[0].section
    assert root.heading_path == () and root.title == "Making a Career"
    assert not any("Making a Career" in pb.block.block_id for pb in doc.blocks)


def test_title_heading_can_be_kept_in_paths(layer0_cfg):
    cfg = layer0_cfg.model_copy(update={"title_heading_in_path": True})
    doc = parse_file(E3_OLD, cfg, T0)
    assert all("Making a Career" in pb.block.block_id for pb in doc.blocks)


def test_thai_heading_path_and_digits(layer0_cfg):
    doc = parse_file(T1_OLD, layer0_cfg, T0)
    blocks = _blocks_under(doc, "มาตรา 34")
    assert len(blocks) == 1
    path = blocks[0].block_id.split("::")[1]
    assert path.startswith("หมวด 2 ")  # Thai digits became Arabic
    assert "ลาเพื่อกิจธุระ" in blocks[0].text


def test_section_numbers_with_slash_survive(layer0_cfg):
    doc = parse_file(T1_OLD, layer0_cfg, T0)
    assert _blocks_under(doc, "มาตรา 11/1")


def test_arabic_digit_file_gets_same_style_path(layer0_cfg):
    doc = parse_file(T4, layer0_cfg, T0)
    assert _blocks_under(doc, "ข้อ 1")


@pytest.mark.usefixtures("need_uploads")
def test_footnote_marker_removed_from_heading_path(layer0_cfg):
    doc = parse_file(T1_NEW, layer0_cfg, T0)
    paths = {ps.section.heading_path for ps in doc.sections}
    sec8 = [p for p in paths if p and p[0].startswith("หมวด 8 ")]
    assert sec8 and not any("[" in p[0] for p in sec8)


def test_duplicate_headings_get_suffix(tmp_path, layer0_cfg):
    f = tmp_path / "dup.md"
    f.write_text(
        "---\ndoc_key: test-dup\ntitle: Dup\nlanguage: en\n---\n# Dup\n\n"
        "## Notes\n\nfirst\n\n## Notes\n\nsecond\n",
        encoding="utf-8",
    )
    doc = parse_file(f, layer0_cfg, T0)
    assert [pb.block.block_id for pb in doc.blocks] == [
        "test-dup::Notes::b0",
        "test-dup::Notes ~2::b0",
    ]


# ------------------------------------------------------------- hashing


@pytest.mark.usefixtures("need_uploads")
def test_footnote_marker_does_not_change_hash(layer0_cfg):
    doc = parse_file(T1_NEW, layer0_cfg, T0)
    (b34,) = _blocks_under(doc, "มาตรา 34")
    assert b34.footnotes == ("[๑๖]",)
    n = Normalizer(layer0_cfg)
    assert b34.content_hash == n.content_hash(b34.text.replace("[๑๖]", ""))


@pytest.mark.usefixtures("need_uploads")
def test_amended_section_hash_differs_between_versions(layer0_cfg):
    old = _blocks_under(parse_file(T1_OLD, layer0_cfg, T0), "มาตรา 34")[0]
    new = _blocks_under(parse_file(T1_NEW, layer0_cfg, T0), "มาตรา 34")[0]
    assert old.block_id == new.block_id
    assert old.content_hash != new.content_hash


def test_normalizer_rules():
    n = Normalizer(Layer0Settings())
    assert n.normalize("มาตรา ๑๑๘ [๑๒]  ค่าชดเชย\n") == "มาตรา 118 ค่าชดเชย"
    assert n.normalize("a\n\n  b") == "a b"
    off = Normalizer(Layer0Settings(strip_footnote_markers=False, thai_digits_to_arabic=False))
    assert off.normalize("[๑] ๒") == "[๑] ๒"


def test_list_is_one_block(layer0_cfg):
    doc = parse_file(E3_OLD, layer0_cfg, T0)
    lists = [pb.block for pb in doc.blocks if pb.block.kind == BlockKind.LIST]
    assert len(lists) == 1 and lists[0].text.count("\n") >= 4


# ------------------------------------------------------------- errors


def test_missing_doc_key_is_an_error(tmp_path, layer0_cfg):
    f = tmp_path / "x.md"
    f.write_text("---\ntitle: X\nlanguage: en\n---\ntext\n", encoding="utf-8")
    with pytest.raises(ParseError, match="doc_key"):
        parse_file(f, layer0_cfg, T0)


def test_empty_folder_is_an_error(tmp_path, layer0_cfg):
    with pytest.raises(ParseError):
        parse_corpus(Path(tmp_path), layer0_cfg, T0)


# ------------------------------------------------------------- role and list splitting

T5 = INITIAL / "T5_regulation_criminal_proceedings_2558.md"


def test_footnote_list_blocks_get_footnote_role(layer0_cfg):
    from kg.models import BlockRole

    doc = parse_file(T1_OLD, layer0_cfg, T0)
    roles = {}
    for pb in doc.blocks:
        in_fn = "เชิงอรรถ" in pb.block.block_id.split("::")[1].split(" > ")
        assert (pb.block.role == BlockRole.FOOTNOTE) == in_fn
        roles[pb.block.role] = roles.get(pb.block.role, 0) + 1
    assert roles[BlockRole.FOOTNOTE] == 74


def test_long_lists_are_split_into_items(layer0_cfg):
    doc = parse_file(T5, layer0_cfg, T0)
    items = [pb.block for pb in doc.blocks if pb.block.kind == BlockKind.LIST_ITEM]
    assert items
    assert not any(pb.block.kind == BlockKind.LIST and len(pb.block.text) > 1500
                   for pb in doc.blocks)
    # every item starts with a list marker and holds no other top-level item
    for b in items:
        first = b.text.lstrip()
        assert first.startswith(("-", "*", "+")) or first[:1].isdigit()


def test_splitting_can_be_switched_off(layer0_cfg):
    off = layer0_cfg.model_copy(update={"split_list_over_chars": None})
    doc = parse_file(T5, off, T0)
    assert not any(pb.block.kind == BlockKind.LIST_ITEM for pb in doc.blocks)


def test_nested_list_stays_inside_its_item(tmp_path, layer0_cfg):
    long = "x" * 40
    body = "".join(f"- item {i} {long}\n  - nested {i} {long}\n" for i in range(3))
    f = tmp_path / "n.md"
    f.write_text(f"---\ndoc_key: test-nested\ntitle: N\nlanguage: en\n---\n# N\n\n{body}",
                 encoding="utf-8")
    cfg = layer0_cfg.model_copy(update={"split_list_over_chars": 50})
    doc = parse_file(f, cfg, T0)
    assert [pb.block.kind for pb in doc.blocks] == [BlockKind.LIST_ITEM] * 3
    assert all("nested" in pb.block.text for pb in doc.blocks)
    assert [pb.block.lines.start for pb in doc.blocks] == [8, 10, 12]  # front matter 1-5, title 6, blank 7
