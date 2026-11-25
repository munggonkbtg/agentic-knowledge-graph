from datetime import datetime, timezone
from pathlib import Path

import pytest

from kg.config import load_config

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INITIAL = DATA / "initial_corpus"
UPLOADS = DATA / "uploads"
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def pilot_files() -> list[Path]:
    return sorted(INITIAL.glob("*.md")) + sorted(UPLOADS.glob("*/*.md"))


@pytest.fixture(scope="session")
def layer0_cfg():
    return load_config(ROOT / "config.yaml").layer0


@pytest.fixture(scope="session", autouse=False)
def need_data():
    # The pilot files are not in git (license); skip data tests on a fresh clone.
    if not INITIAL.exists():
        pytest.skip("data/initial_corpus not present (see data/README.md)")


@pytest.fixture(scope="session")
def need_uploads(need_data):
    # The upload files (new versions) are kept out of data/ until an upload is run.
    if not any(UPLOADS.glob("*/*.md")):
        pytest.skip("data/uploads not present (no upload files yet)")
