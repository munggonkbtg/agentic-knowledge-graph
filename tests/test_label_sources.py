import csv
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from label_sources import kappa, source_agreement, sources_to_score  # noqa: E402

from kg.backup import backup_labels  # noqa: E402

COLS = ["answer", "note"]


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["row_id", "answer", "note"])
        w.writeheader()
        w.writerows(rows)


def test_both_reports_only_sources_with_answers(tmp_path):
    _write(tmp_path / "s_ai.csv", [{"row_id": "r1", "answer": "same", "note": ""}])
    _write(tmp_path / "s_human.csv", [{"row_id": "r1", "answer": "", "note": "a note only"}])
    assert sources_to_score("both", "s", COLS, tmp_path) == ["ai"]
    assert sources_to_score("ai", "s", COLS, tmp_path) == ["ai"]


def test_named_source_without_answers_or_sheet_stops(tmp_path):
    _write(tmp_path / "s_human.csv", [{"row_id": "r1", "answer": "", "note": ""}])
    with pytest.raises(SystemExit, match="no human labels yet"):
        sources_to_score("human", "s", COLS, tmp_path)
    with pytest.raises(SystemExit, match="does not exist"):
        sources_to_score("ai", "s", COLS, tmp_path)


def test_agreement_ignores_case_and_item_order():
    human = [{"row_id": "r1", "answer": "a; B"}, {"row_id": "r2", "answer": "x"},
             {"row_id": "r3", "answer": ""}]
    ai = [{"row_id": "r1", "answer": "b;a"}, {"row_id": "r2", "answer": "y"},
          {"row_id": "r3", "answer": "z"}]
    table = source_agreement(human, ai, ["answer"])
    assert "| answer | 2 | 0.50 |" in table  # r3 not answered by both


def test_kappa():
    assert kappa([("yes", "yes"), ("no", "no")]) == pytest.approx(1.0)
    assert kappa([("yes", "no"), ("no", "yes")]) == pytest.approx(-1.0)
    assert kappa([("yes", "yes")]) is None  # one answer only: chance agreement is 1
    assert kappa([]) is None


def test_backup_copies_to_a_dated_folder_and_never_overwrites(tmp_path):
    labels = tmp_path / "labels"
    labels.mkdir()
    (labels / "sheet.csv").write_text("row_id\nr1\n", encoding="utf-8")
    now = datetime(2026, 11, 25, 9, 30, 0)
    first = backup_labels(labels, tmp_path / "backups", now)
    second = backup_labels(labels, tmp_path / "backups", now)
    assert first.name == "labels-20261125-093000"
    assert second.name == "labels-20261125-093000-2"
    assert (first / "sheet.csv").read_text(encoding="utf-8") == "row_id\nr1\n"


def test_backup_of_empty_folder_and_inside_folder(tmp_path):
    labels = tmp_path / "labels"
    labels.mkdir()
    assert backup_labels(labels, tmp_path / "backups") is None
    (labels / "x.csv").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        backup_labels(labels, labels / "inside")
