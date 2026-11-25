from typer.testing import CliRunner

from kg.cli import app

runner = CliRunner()


def test_help_lists_m0_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("ping", "init-schema", "analyzers"):
        assert cmd in result.output


def test_ping_without_credentials_fails_cleanly(monkeypatch, tmp_path):
    # Run from an empty folder so no .env is picked up.
    monkeypatch.chdir(tmp_path)
    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "config.yaml").write_text("neo4j:\n  database: neo4j\n", encoding="utf-8")
    result = runner.invoke(app, ["ping"])
    assert result.exit_code == 2
    assert "NEO4J_PASSWORD" in result.output
