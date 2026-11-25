from pathlib import Path

import pytest
from pydantic import ValidationError

from kg.config import MissingEnvError, load_config, load_neo4j_credentials

ROOT = Path(__file__).resolve().parents[1]


def test_repo_config_loads():
    cfg = load_config(ROOT / "config.yaml")
    assert cfg.neo4j.database == "neo4j"


def test_unknown_config_key_is_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("neo4j:\n  databse: x\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(p)


def test_missing_env_names_variables_not_values(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "neo4j://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    with pytest.raises(MissingEnvError) as exc:
        load_neo4j_credentials(env_file=None)
    assert "NEO4J_PASSWORD" in str(exc.value)
    assert "localhost" not in str(exc.value)


def test_password_is_hidden_when_printed(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "neo4j://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "not-a-real-password")
    creds = load_neo4j_credentials(env_file=None)
    assert "not-a-real-password" not in repr(creds)
    assert "not-a-real-password" not in str(creds)


def test_env_example_has_no_value_for_password():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    pw = [line for line in lines if line.startswith("NEO4J_PASSWORD=")]
    assert pw == ["NEO4J_PASSWORD="]
