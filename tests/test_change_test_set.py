"""Pooling helpers of the M5 change test set (no files, no database)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from make_change_test_set import Char3Index, anchor_of, cited_section, cites_section  # noqa: E402


def test_char3_ranks_the_similar_block_first_and_works_for_thai():
    idx = Char3Index({
        "a": "ให้ลูกจ้างมีสิทธิลาเพื่อกิจธุระอันจำเป็นได้ปีละไม่น้อยกว่าสามวันทำงาน",
        "b": "นายจ้างต้องจ่ายค่าชดเชยให้แก่ลูกจ้างที่ถูกเลิกจ้าง",
        "c": "Employees get twenty days of paid vacation each year.",
    })
    assert idx.top("ลูกจ้างมีสิทธิลากิจธุระอันจำเป็น", 1, exclude=set()) == ["a"]
    assert idx.top("paid vacation days", 1, exclude=set()) == ["c"]
    assert "a" not in idx.top("ลากิจธุระ", 3, exclude={"a"})


def test_cited_section_and_anchor_from_block_ids():
    assert cited_section("th-act::หมวด 2 การใช้แรงงานทั่วไป > มาตรา 34::b0") == "มาตรา34"
    assert cited_section("th-act::มาตรา 11/1::b0") == "มาตรา11/1"
    assert cited_section("en-x::Paid Time Off > Sabbatical::b0") is None
    assert anchor_of("en-x::Your First 90 Days::b1") == "#your-first-90-days"
    assert anchor_of("en-x::Mastery & Titles::b0") == "#mastery--titles"
    assert anchor_of("en-x::_::b0") is None


def test_cites_section_respects_number_boundaries():
    assert cites_section("ตามมาตรา ๓๔ แห่ง", "มาตรา34")
    assert not cites_section("ตามมาตรา ๓๔๑", "มาตรา34")
    assert not cites_section("ตามมาตรา 34/1", "มาตรา34")


def test_apply_edit_replaces_exactly_the_block_lines(tmp_path):
    from make_synthetic_events import apply_edit

    src = tmp_path / "a.md"
    src.write_text("---\ndoc_key: k\n---\n# T\n\nfirst line\n\nold fact\nstill old\n\nlast\n",
                   encoding="utf-8")
    dst = tmp_path / "out" / "a.md"
    apply_edit(src, 8, 9, "new fact", dst)
    assert dst.read_text(encoding="utf-8").splitlines() == \
        ["---", "doc_key: k", "---", "# T", "", "first line", "", "new fact", "", "last"]


def test_synthetic_build_end_to_end_in_a_scratch_folder(tmp_path, monkeypatch):
    import csv
    import json

    import make_change_test_set as mct
    import make_synthetic_events as mse

    if not (mct.ROOT / "data" / "uploads").exists():
        import pytest
        pytest.skip("data/uploads not present")
    monkeypatch.setattr(mse, "LABELS", tmp_path)
    monkeypatch.setattr(mse, "OUT_DIR", tmp_path / "uploads_synthetic")
    mse.template()
    rows = list(csv.DictReader(open(tmp_path / "m5s_store_blocks.csv", encoding="utf-8-sig")))
    (row,) = [r for r in rows if r["section"].endswith("มาตรา 34")]
    edits = list(csv.DictReader(open(tmp_path / "m5s_edits.csv", encoding="utf-8-sig")))
    edits[0].update(store_ref=row["ref"],
                    new_text=row["block_text"].replace("สามวันทำงาน", "ห้าวันทำงาน"),
                    what_changed="personal leave: 3 -> 5 working days")
    with open(tmp_path / "m5s_edits.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(edits[0]))
        w.writeheader()
        w.writerows(edits)
    mse.build()
    key = json.loads((tmp_path / "m5s_key.json").read_text(encoding="utf-8"))
    assert list(key["changes"]) == ["XS01"]
    assert (tmp_path / "uploads_synthetic" / "S01").exists()
    cands = list(csv.DictReader(open(tmp_path / "m5s_candidates.csv", encoding="utf-8-sig")))
    assert cands and "needs_review" in cands[0] and "sources" not in cands[0]


def test_rrf_fuses_rankings_and_rewards_agreement():
    import importlib.util

    if importlib.util.find_spec("numpy") is None:
        import pytest
        pytest.skip("numpy (embed group) not installed")
    from compare_embeddings import rrf

    fused = rrf(["a", "b", "c"], ["b", "a", "d"])
    assert fused[:2] == ["a", "b"] or fused[:2] == ["b", "a"]
    assert fused.index("c") > 1 and fused.index("d") > 1
    assert rrf(["x", "y"], ["x", "y"]) == ["x", "y"]
