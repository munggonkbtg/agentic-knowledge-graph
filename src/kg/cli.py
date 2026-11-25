"""Command-line entry point: ``kg <command>``."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import typer
from neo4j.exceptions import AuthError, ServiceUnavailable

from kg.config import DEFAULT_CONFIG_PATH, MissingEnvError, load_config, load_neo4j_credentials
from kg.diff import REVIEW_COLUMNS, VERDICT_HELP, MatchStatus, diff_event, review_rows
from kg.layer0_structure import Normalizer, ParseError, parse_corpus, parse_file
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


def _as_of(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@app.command()
def build(
    layer: int = typer.Option(..., "--layer", help="Which layer to build (only 0 so far)."),
    corpus: Path = typer.Option(Path("data/initial_corpus"), "--corpus", help="Folder of .md files"),
    as_of: datetime | None = typer.Option(
        None, "--as-of", help="valid_from for new nodes and edges (default: now, UTC)."
    ),
    config: Path = ConfigOption,
) -> None:
    """Build one layer of the graph for every file in a folder."""
    if layer != 0:
        typer.secho(f"Layer {layer} is not implemented yet.", fg="red", err=True)
        raise typer.Exit(2)
    cfg = load_config(config)
    # Parse everything first, so a bad file stops the run before anything is written.
    try:
        docs = parse_corpus(corpus, cfg.layer0, _as_of(as_of))
    except ParseError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from None
    try:
        with _open_store(config) as store:
            for doc in docs:
                store.write_layer0(doc)  # one transaction per document
                typer.echo(f"  {doc.version.source_file}: {len(doc.sections)} sections, "
                           f"{len(doc.blocks)} blocks")
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.secho(f"Layer 0 written for {len(docs)} files.", fg="green")


@app.command()
def stats(config: Path = ConfigOption) -> None:
    """Show sections, blocks and NEXT edges per document version."""
    try:
        with _open_store(config) as store:
            rows = store.version_stats()
            snap = store.graph_snapshot()
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.echo(f"{'version':58} {'lang':4} {'sections':>8} {'blocks':>6} {'next':>5}")
    for r in rows:
        typer.echo(f"{r['version_id']:58} {r['language']:4} {r['sections']:>8} "
                   f"{r['blocks']:>6} {r['next_edges']:>5}")
    typer.echo(f"Nodes: {snap['labels']}")
    typer.echo(f"Relationships: {snap['relationships']}")


@app.command("show-blocks")
def show_blocks(
    file: Path = typer.Argument(..., help="A Markdown file to parse (nothing is written)."),
    config: Path = ConfigOption,
) -> None:
    """Parse one file and print its blocks: ID, lines, kind, role and the start of the text."""
    cfg = load_config(config)
    doc = parse_file(file, cfg.layer0, _as_of(None))
    for pb in doc.blocks:
        b = pb.block
        preview = b.text.replace("\n", " ")[:50]
        role = "" if b.role.value == "body" else f" [{b.role.value}]"
        typer.echo(f"{b.lines.start:>5}-{b.lines.end:<5} {b.kind.value:9} {b.block_id}{role}\n"
                   f"            {preview}")


@app.command()
def diff(
    event: list[Path] = typer.Option(..., "--event", help="Upload folder (repeat for several)."),
    old_dir: Path = typer.Option(Path("data/initial_corpus"), "--old-dir",
                                 help="Folder holding the previous versions."),
    review_out: Path | None = typer.Option(
        None, "--review-out", help="Write a CSV for a person to check (UTF-8, opens in Excel)."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing review file."),
    config: Path = ConfigOption,
) -> None:
    """Match blocks of uploaded files against their previous versions (nothing is written
    to Neo4j)."""
    cfg = load_config(config)
    norm = Normalizer(cfg.layer0)
    now = _as_of(None)
    olds = {d.document.doc_key: d for d in parse_corpus(old_dir, cfg.layer0, now)}
    statuses = [s.value for s in MatchStatus]
    typer.echo(f"edit_similarity_threshold = {cfg.diff.edit_similarity_threshold}, "
               f"cross_section_edit_threshold = {cfg.diff.cross_section_edit_threshold}, "
               f"move_similarity_threshold = {cfg.diff.move_similarity_threshold}")
    typer.echo(f"{'event':10} {'document':42} " + " ".join(f"{s:>9}" for s in statuses))
    rows: list[dict] = []
    for folder in event:
        results = diff_event(olds, parse_corpus(folder, cfg.layer0, now), cfg.diff, norm)
        for d in results:
            counts = Counter(m.status.value for m in d.matches)
            label = d.doc_key + ("" if d.old else " (new)")
            typer.echo(f"{folder.name:10} {label:42} "
                       + " ".join(f"{counts[s]:>9}" for s in statuses))
        rows += review_rows(folder.name, results, norm)

    if review_out is not None:
        if review_out.exists() and not force:
            typer.secho(f"{review_out} already exists (it may hold a person's labels). "
                        "Use --force to overwrite.", fg="red", err=True)
            raise typer.Exit(1)
        review_out.parent.mkdir(parents=True, exist_ok=True)
        # utf-8-sig adds a marker so Excel shows Thai text correctly.
        with review_out.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        typer.echo(f"Wrote {len(rows)} rows to {review_out}")
        typer.echo(VERDICT_HELP)


@app.command()
def upload(
    event: Path = typer.Option(..., "--event", help="Folder with the files of one upload."),
    layer: int = typer.Option(0, "--layer", help="Layers to run on the new version (0 only)."),
    as_of: datetime | None = typer.Option(
        None, "--as-of", help="When the upload happens (valid_from of the new versions)."),
    config: Path = ConfigOption,
) -> None:
    """Upload new document versions: diff each file against its current version in the
    graph, then write the new version, reusing the node of every unchanged block."""
    if layer != 0:
        typer.secho(f"Layer {layer} is not implemented yet.", fg="red", err=True)
        raise typer.Exit(2)
    cfg = load_config(config)
    norm = Normalizer(cfg.layer0)
    try:
        uploaded = parse_corpus(event, cfg.layer0, _as_of(as_of))
    except ParseError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from None
    try:
        with _open_store(config) as store:
            todo = []
            for doc in uploaded:
                if store.version_exists(doc.version.version_id):
                    typer.echo(f"  {doc.version.source_file}: already uploaded, skipped")
                else:
                    todo.append(doc)
            olds = {}
            for doc in todo:
                old = store.load_current_version(doc.document.doc_key)
                if old is not None:
                    olds[doc.document.doc_key] = old
            for d in diff_event(olds, todo, cfg.diff, norm):
                counts = Counter(m.status.value for m in d.matches)
                written = store.write_upload(d)  # one transaction per document
                label = "new document" if d.old is None else f"supersedes {d.old.version.version_id}"
                typer.echo(f"  {d.new.version.source_file}: {label}")
                typer.echo(f"      diff {dict(counts)}")
                typer.echo(f"      nodes reused {written['reused_nodes']}, "
                           f"new {written['new_nodes']}")
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.secho(f"Uploaded {len(todo)} of {len(uploaded)} files.", fg="green")


@app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", help="Confirm deleting all pipeline data."),
    config: Path = ConfigOption,
) -> None:
    """Delete every Document, Version, Section, Block, Alias and Entity node and their
    relationships. Constraints and indexes stay. Cannot be undone."""
    if not yes:
        typer.secho("This deletes all pipeline data in the database. Rerun with --yes.",
                    fg="yellow", err=True)
        raise typer.Exit(1)
    try:
        with _open_store(config) as store:
            n = store.reset_pipeline_data()
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.secho(f"Deleted {n} nodes.", fg="green")


if __name__ == "__main__":
    app()
