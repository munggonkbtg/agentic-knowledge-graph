"""Document identification on the committed fixtures (no database needed)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from kg.config import load_config
from kg.identify import (
    add_to_queue,
    candidate_from,
    file_hash,
    identify,
    new_doc_key,
    read_answers,
)
from kg.layer0_structure import Language, Normalizer, detect_language, parse_file

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
CFG = load_config(ROOT / "config.yaml")
NORM = Normalizer(CFG.layer0)
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def body_only(src: Path, dst_dir: Path, name: str | None = None) -> Path:
    """Copy a fixture without its front matter (so it has no doc_key)."""
    body = src.read_text(encoding="utf-8").split("---", 2)[2].lstrip("\n")
    dst = dst_dir / (name or src.name)
    dst.write_text(body, encoding="utf-8")
    return dst


@pytest.fixture(scope="module")
def candidates():
    return [candidate_from(parse_file(FIX / n, CFG.layer0, T0), NORM)
            for n in ("en_policy_old.md", "th_lpa_old.md", "th_inspection_arabic_digits.md")]


def keys(cands):
    return {c.doc_key for c in cands}


# ------------------------------------------------------------- front matter


def test_known_front_matter_key_is_a_registry_match(candidates):
    ident, doc = identify(FIX / "en_policy_new.md", candidates, CFG, T0)
    assert (ident.method, ident.doc_key, ident.needs_person) == \
           ("registry", "fixture-en-leave-policy", False)
    assert doc.document.doc_key == "fixture-en-leave-policy"


def test_new_front_matter_key_is_kept_but_listed_for_confirmation(candidates):
    ident, doc = identify(FIX / "en_severance_new.md", candidates, CFG, T0)
    assert (ident.method, ident.doc_key) == ("front_matter", "fixture-en-severance")
    assert ident.confirm_later and doc is not None
    seeded, _ = identify(FIX / "en_severance_new.md", candidates, CFG, T0,
                         trust_front_matter=True)
    assert not seeded.confirm_later


# ------------------------------------------------------------- no doc_key


@pytest.mark.parametrize("name, expected", [
    ("en_policy_new.md", "fixture-en-leave-policy"),
    ("th_lpa_new.md", "fixture-th-labour-protection-act"),
])
def test_file_without_key_is_matched_by_content(tmp_path, candidates, name, expected):
    ident, doc = identify(body_only(FIX / name, tmp_path), candidates, CFG, T0)
    assert (ident.method, ident.doc_key, ident.needs_person) == ("content", expected, False)
    assert all(pb.block.block_id.startswith(expected + "::") for pb in doc.blocks)
    assert ident.ranked[0].text >= CFG.identify.accept_text_similarity
    props = ident.provenance()
    assert props["method"] == "content" and "id_text_similarity" in props


def test_unrelated_file_becomes_a_new_document_to_confirm(tmp_path, candidates):
    ident, doc = identify(body_only(FIX / "en_severance_new.md", tmp_path), candidates, CFG, T0)
    assert ident.method == "new" and ident.confirm_later and not ident.needs_person
    assert ident.doc_key == new_doc_key(tmp_path / "en_severance_new.md")
    assert ident.doc_key not in keys(candidates)


def test_names_alone_do_not_identify_a_document(tmp_path, candidates):
    # Same file name and title as the old Thai act, unrelated text (like T2 vs T1).
    f = tmp_path / "th_lpa_old.md"
    f.write_text("# พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541 (ฉบับ Update ณ วันที่ 31/08/2560) excerpt\n\n"
                 "Completely different content about budgets, spreadsheets and quarterly "
                 "reports that shares nothing with the act.\n", encoding="utf-8")
    ident, _ = identify(f, candidates, CFG, T0)
    (act,) = [s for s in ident.ranked if s.doc_key == "fixture-th-labour-protection-act"]
    assert act.title > 0.9 and act.file_name == 1.0  # looks like the act by name ...
    assert act.text < CFG.identify.new_document_below  # ... but not by text
    assert ident.method == "new" and ident.doc_key != act.doc_key  # text decides


def test_unsure_file_waits_for_a_person(tmp_path, candidates):
    strict = CFG.model_copy(update={"identify": CFG.identify.model_copy(
        update={"accept_text_similarity": 0.95})})
    ident, doc = identify(body_only(FIX / "en_policy_new.md", tmp_path), candidates, strict, T0)
    assert ident.needs_person and doc is None and ident.doc_key is None


def test_two_equally_good_candidates_need_a_person(tmp_path, candidates):
    twin = candidates[0].__class__(**{**candidates[0].__dict__, "doc_key": "fixture-twin"})
    ident, doc = identify(body_only(FIX / "en_policy_new.md", tmp_path),
                          candidates + [twin], CFG, T0)
    assert ident.needs_person and doc is None  # margin to the second is 0


def test_no_candidates_means_new(tmp_path):
    ident, doc = identify(body_only(FIX / "en_policy_new.md", tmp_path), [], CFG, T0)
    assert ident.method == "new" and not ident.confirm_later and doc is not None


# ------------------------------------------------------------- person answers and queue


def test_person_answer_wins(tmp_path, candidates):
    f = body_only(FIX / "en_policy_new.md", tmp_path)
    ident, doc = identify(f, candidates, CFG, T0, answers={file_hash(f): "fixture-en-leave-policy"})
    assert (ident.method, ident.doc_key) == ("human", "fixture-en-leave-policy")
    ident, _ = identify(f, candidates, CFG, T0, answers={file_hash(f): "new"})
    assert (ident.method, ident.doc_key) == ("human", new_doc_key(f))


def test_queue_adds_once_and_never_overwrites_answers(tmp_path, candidates):
    strict = CFG.model_copy(update={"identify": CFG.identify.model_copy(
        update={"accept_text_similarity": 0.95})})
    f = body_only(FIX / "en_policy_new.md", tmp_path)
    ident, _ = identify(f, candidates, strict, T0)
    queue = tmp_path / "labels" / "queue.csv"
    assert add_to_queue(queue, [ident]) == 1
    assert add_to_queue(queue, [ident]) == 0  # same file hash: not added twice
    # a person answers
    text = queue.read_text(encoding="utf-8-sig").splitlines()
    text[1] = text[1][: text[1].rfind(",")] + ",fixture-en-leave-policy"
    queue.write_text("\n".join(text) + "\n", encoding="utf-8-sig")
    assert read_answers(queue) == {file_hash(f): "fixture-en-leave-policy"}
    assert add_to_queue(queue, [ident]) == 0
    assert read_answers(queue) == {file_hash(f): "fixture-en-leave-policy"}


# ------------------------------------------------------------- layer 0 fallbacks


def test_title_and_language_fall_back_when_front_matter_is_missing(tmp_path):
    th = parse_file(body_only(FIX / "th_lpa_old.md", tmp_path), CFG.layer0, T0, doc_key="k")
    assert th.document.language == Language.TH
    assert th.document.title.startswith("พระราชบัญญัติคุ้มครองแรงงาน")
    en = parse_file(body_only(FIX / "en_policy_old.md", tmp_path), CFG.layer0, T0, doc_key="k")
    assert en.document.language == Language.EN and en.document.title == "Leave Policy"
    assert detect_language("plain English text") == Language.EN
