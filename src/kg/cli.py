"""Command-line entry point: ``kg <command>``."""

from __future__ import annotations

from pathlib import Path

import typer
from neo4j.exceptions import AuthError, ServiceUnavailable

from kg.config import DEFAULT_CONFIG_PATH, MissingEnvError, load_config, load_neo4j_credentials
from kg.store import Store

app = typer.Typer(help="Knowledge-graph pipeline (research prototype).", no_args_is_help=True)

ConfigOption = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Path to config.yaml")


def _open_store(config_path: Path) -> Store:
    cfg = load_config(config_path)
    try:
        creds = load_neo4j_credentials()
    except MissingEnvError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(2) from None
    return Store(creds, database=cfg.neo4j.database)


def _connection_error(e: Exception) -> None:
    if isinstance(e, AuthError):
        msg = "Neo4j rejected the user name or password (check NEO4J_USER / NEO4J_PASSWORD)."
    else:
        msg = "Could not reach Neo4j (is the database started? check NEO4J_URI)."
    typer.secho(f"{msg}\n  {type(e).__name__}", fg="red", err=True)
    raise typer.Exit(1)


@app.command()
def ping(config: Path = ConfigOption) -> None:
    """Connect to Neo4j, create a test node, read it back and delete it."""
    try:
        with _open_store(config) as store:
            result = store.ping()
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.echo(f"Connected to {result.server_agent} at {result.server_address}")
    typer.echo(f"  test node created and read back: {result.created_and_read}")
    typer.echo(f"  test node removed:               {result.removed}")
    if not (result.created_and_read and result.removed):
        raise typer.Exit(1)
    typer.secho("OK", fg="green")


@app.command("init-schema")
def init_schema(config: Path = ConfigOption) -> None:
    """Create uniqueness constraints and indexes (safe to rerun)."""
    try:
        with _open_store(config) as store:
            statements = store.ensure_schema()
            existing = store.schema_names()
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.echo(f"Ran {len(statements)} schema statements; database now has {len(existing)} "
               "constraints/indexes.")
    typer.secho("OK", fg="green")


@app.command()
def analyzers(config: Path = ConfigOption) -> None:
    """List Neo4j full-text analyzers and say whether a Thai one exists."""
    try:
        with _open_store(config) as store:
            names = store.fulltext_analyzers()
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    for name in names:
        typer.echo(f"  {name}")
    thai = [n for n in names if "thai" in n.lower()]
    typer.echo(f"Thai analyzer available: {', '.join(thai) if thai else 'no'}")


if __name__ == "__main__":
    app()
