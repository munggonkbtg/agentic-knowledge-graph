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
from kg.identify import add_to_queue, candidate_from, identify, read_answers
from kg.layer1_references import ReferenceExtractor, Registry, load_extra_aliases
from kg.layer2_entities import (
    EntityMatcher,
    block_share,
    body_block_counts,
    build_registry,
    flag_hubs,
    load_manual,
)
from kg.llm import LLMUnavailable
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


def _llm_unavailable(e: Exception) -> None:
    typer.secho(f"The LLM cannot answer, stopping: {e}", fg="red", err=True)
    raise typer.Exit(1)


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
    """Create uniqueness constraints and indexes, including the vector index on
    Block.embedding (safe to rerun)."""
    cfg = load_config(config)
    try:
        with _open_store(config) as store:
            statements = store.ensure_schema(cfg.embedding.dimensions)
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
    layer: int = typer.Option(..., "--layer", help="Which layer to build (0, 1 or 2)."),
    corpus: Path = typer.Option(Path("data/initial_corpus"), "--corpus", help="Folder of .md files"),
    as_of: datetime | None = typer.Option(
        None, "--as-of", help="valid_from for new nodes and edges (default: now, UTC)."
    ),
    config: Path = ConfigOption,
) -> None:
    """Build one layer of the graph.

    Layer 0: every file in --corpus. Each file is first identified
    (docs/plan.md): front-matter keys seed the registry; a file without one is
    compared with the documents already known.
    Layer 1: REFERENCES for the current version of every document in the graph
    (--corpus is not used).
    Layer 2: entity registry, hub flags and MENTIONS for the current version of
    every document in the graph (--corpus is not used)."""
    if layer == 1:
        _build_layer1(config)
        return
    if layer == 2:
        _build_layer2(config)
        return
    if layer == 3:
        build_layer3(config)
        return
    if layer == 4:
        build_layer4(config)
        return
    if layer != 0:
        typer.secho(f"Layer {layer} is not implemented yet.", fg="red", err=True)
        raise typer.Exit(2)
    cfg = load_config(config)
    norm = Normalizer(cfg.layer0)
    files = sorted(corpus.glob("*.md"))
    if not files:
        typer.secho(f"No .md files in {corpus}", fg="red", err=True)
        raise typer.Exit(1)
    try:
        with _open_store(config) as store:
            candidates = store.identification_candidates(norm)
            answers = read_answers(cfg.identify.queue_file)
            # Identify and parse everything first, so a bad file stops the run
            # before anything is written.
            decided, waiting = [], []
            try:
                for path in files:
                    ident, doc = identify(path, candidates, cfg, _as_of(as_of), answers,
                                          trust_front_matter=True)
                    if doc is None:
                        waiting.append(ident)
                        continue
                    decided.append((ident, doc))
                    if ident.doc_key not in {c.doc_key for c in candidates}:
                        candidates.append(candidate_from(doc, norm))
            except ParseError as e:
                typer.secho(str(e), fg="red", err=True)
                raise typer.Exit(1) from None
            for ident, doc in decided:
                store.write_layer0(doc, ident.provenance())  # one transaction per document
                typer.echo(f"  {doc.version.source_file}: {doc.document.doc_key} "
                           f"({ident.method}), {len(doc.sections)} sections, "
                           f"{len(doc.blocks)} blocks")
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    _report_queue(cfg, waiting + [i for i, _ in decided])
    typer.secho(f"Layer 0 written for {len(decided)} of {len(files)} files.", fg="green")


def _registry(store: Store, cfg) -> Registry:
    return Registry(store.registry_entries(), load_extra_aliases(cfg.layer1.aliases_file))


def _build_layer1(config: Path) -> None:
    cfg = load_config(config)
    total = closed = 0
    run_at = datetime.now(timezone.utc)
    try:
        with _open_store(config) as store:
            registry = _registry(store, cfg)
            extractor = ReferenceExtractor(registry, cfg.layer1)
            for key in sorted(registry.entries):
                doc = store.load_current_version(key)
                if doc is None:
                    continue
                out = extractor.extract(doc)
                # one transaction per document
                res = store.write_references(doc, out, cfg.layer1.rule_version, run_at)
                total += res["written"]
                closed += res["closed"]
                by = Counter(r.resolution for r in out.references)
                typer.echo(f"  {key}: {res['written']} references {dict(by)}, "
                           f"{len(out.stubs)} external documents, "
                           f"{len(out.unresolved)} unresolved, "
                           f"{res['closed']} older edges closed")
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.secho(f"Layer 1 ({cfg.layer1.rule_version}) written: {total} references; "
                f"{closed} edges from older rule versions closed (valid_to set).", fg="green")


def build_layer3(config: Path) -> dict[str, int]:
    """Layer 3 (M6): merge duplicate entities (Thai-English included). Candidate
    pairs by name containment and e5 name similarity, confirmed by the local LLM,
    written reversibly (ALIAS_OF to the canonical entity, merged_into). A CSV of
    every pair and verdict goes to `impact.report_dir`. Needs the `embed` group."""
    import csv as _csv

    from kg.embedding import Embedder
    from kg.layer3_merge import MergeEntity, candidate_pairs, merge_entities
    from kg.llm import LLMClient

    cfg = load_config(config)
    s = cfg.layer3
    run_at = datetime.now(timezone.utc)
    try:
        with _open_store(config) as store:
            rows = store.entities_for_merge()
            ents = [MergeEntity(r["entity_id"], r["name"], r["entity_type"], r["language"],
                                r["mentions"], r["hub"], tuple(r["sources"]),
                                list(r["examples"])) for r in rows]
            emb = Embedder(cfg.embedding)
            pairs = candidate_pairs(ents, lambda names: emb.embed(names, "query"),
                                    s.min_similarity, s.top_k, s.min_containment_chars)
            typer.echo(f"  {len(ents)} entities, {len(pairs)} candidate pairs")
            client = LLMClient.for_task(cfg.llm, "merge")

            def confirm(a, b):
                return client.confirm_merge(
                    {"name": a.name, "type": a.entity_type, "language": a.language,
                     "examples": a.examples},
                    {"name": b.name, "type": b.entity_type, "language": b.language,
                     "examples": b.examples})

            res = merge_entities(ents, pairs, confirm)
            reasons = {}
            for (a, b), why in res.reasons.items():
                for m in (a, b):
                    if m in res.canonical:
                        reasons.setdefault(m, why)
            written = store.write_merges(res.canonical, reasons, s.rule_version,
                                         client.s.model, client.prompt_key, s.confidence, run_at)
            client.close()
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return {}
    except LLMUnavailable as e:
        _llm_unavailable(e)
    name = {e.entity_id: e.name for e in ents}
    cfg.impact.report_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.impact.report_dir / f"merges_{datetime.now():%Y%m%d-%H%M%S}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["entity_a", "name_a", "entity_b", "name_b", "candidate_by", "verdict",
                    "reason", "merged_into"])
        for p in res.pairs:
            v = res.verdicts.get((p.a, p.b), "")
            w.writerow([p.a, name[p.a], p.b, name[p.b], p.reason, v,
                        res.reasons.get((p.a, p.b), ""),
                        res.canonical.get(p.a) or res.canonical.get(p.b) or ""])
    from collections import Counter as _C
    typer.secho(f"Layer 3 ({s.rule_version}): {len(pairs)} pairs checked "
                f"({dict(_C(res.verdicts.values()))}), {written['merged']} entities merged, "
                f"{written['undone']} earlier merges undone; {res.calls} new LLM calls -> {out}",
                fg="green")
    return {"pairs": len(pairs), "merged": written["merged"]}


def build_layer4(config: Path, only: set[str] | None = None) -> dict[str, int]:
    """Layer 4 (M7): DEPENDS edges. The most central current blocks (config
    layer4.central_share) or the given blocks (`only`, e.g. new / edited blocks)
    are paired with blocks sharing a non-hub canonical entity and their nearest
    blocks by e5 (capped); the local LLM judges each pair; an edge is written only
    when its two quotes are found in the blocks. A CSV of the edges goes to
    `impact.report_dir`. Needs the vector index (`kg embed`)."""
    import csv as _csv

    from kg.layer4_depends import DepBlock, candidate_pairs, find_depends, select_blocks
    from kg.llm import LLMClient

    cfg = load_config(config)
    s = cfg.layer4
    run_at = datetime.now(timezone.utc)
    t0 = datetime.now()
    try:
        with _open_store(config) as store:
            current = store.current_body_blocks()
            edges = store.impact_edges()
            canon = store.entity_merges()
            blocks = {b["uid"]: DepBlock(b["uid"], b["text"], b["doc_key"],
                                         f"{b['doc_key']} > {(b['block_id'] or '::_').split('::')[1]}")
                      for b in current}
            for m in edges["mentions"]:
                if m["uid"] in blocks and not m["hub"]:
                    blocks[m["uid"]].entities.add(canon.get(m["entity"], m["entity"]))
            for r in edges["refs"]:
                if r["uid"] in blocks:
                    blocks[r["uid"]].refs_out += 1
            processed = select_blocks(blocks, s.central_share, only)
            cur = set(blocks)
            pairs = candidate_pairs(blocks, processed,
                                    lambda u: store.nearest_blocks(u, s.nearest_k, cur),
                                    s.nearest_k, s.max_pairs_per_block)
            typer.echo(f"  {len(blocks)} current blocks, {len(processed)} processed, "
                       f"{len(pairs)} candidate pairs")
            client = LLMClient.for_task(cfg.llm, "depends")
            res = find_depends(blocks, pairs, lambda a, b: client.judge_dependency(
                a.text, b.text, a.context, b.context))
            written = store.write_depends(res.edges, processed, s.rule_version, client.s.model,
                                          client.prompt_key, s.confidence, run_at)
            tokens = sum(c.tokens_in + c.tokens_out for c in client.log if not c.cached)
            client.close()
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return {}
    except LLMUnavailable as e:
        _llm_unavailable(e)
    cfg.impact.report_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.impact.report_dir / f"depends_{datetime.now():%Y%m%d-%H%M%S}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["dependent", "source", "fact", "evidence_dependent", "evidence_source"])
        for e in res.edges:
            w.writerow([e.dependent, e.source, e.fact, e.evidence_dependent, e.evidence_source])
    minutes = (datetime.now() - t0).total_seconds() / 60
    typer.secho(f"Layer 4 ({s.rule_version}): {len(pairs)} pairs, {dict(res.stats)}, "
                f"{written['written']} DEPENDS written, {written['closed']} older closed; "
                f"{tokens} tokens, {minutes:.0f} min -> {out}", fg="green")
    return {"pairs": len(pairs), "edges": written["written"]}


def _build_layer2(config: Path) -> None:
    """Entity registry from the current version of every document in the graph
    (plus the hand-kept file), hub flags from block shares, then MENTIONS with the
    values (number + unit) attached to them."""
    cfg = load_config(config)
    s = cfg.layer2
    run_at = datetime.now(timezone.utc)
    try:
        with _open_store(config) as store:
            keys = sorted(e.doc_key for e in store.registry_entries())
            docs = [d for key in keys if (d := store.load_current_version(key)) is not None]
            reg = build_registry(docs, load_manual(s.manual_file))
            matcher = EntityMatcher(reg)
            mentions = {d.document.doc_key: matcher.mentions(d) for d in docs}
            share = block_share([m for ms in mentions.values() for m in ms],
                                body_block_counts(docs), reg)
            flag_hubs(reg, share, s.hub_block_share)
            res = store.write_entity_registry(list(reg.entries.values()), share,
                                              s.rule_version, run_at)
            typer.echo(f"  registry: {res['entities']} entities, {res['aliases']} aliases, "
                       f"{res['closed']} older ALIAS_OF closed")
            hubs = sorted(e.name for e in reg.entries.values() if e.hub)
            typer.echo(f"  hubs (block share > {s.hub_block_share}): {', '.join(hubs) or 'none'}")
            hub_ids = {e.entity_id for e in reg.entries.values() if e.hub}
            total = closed = n_values = n_loose = 0
            for d in docs:  # one transaction per document
                # values attach to the nearest non-hub entity (M4 step 3)
                ms, loose = matcher.mentions_with_values(d, hub_ids)
                r = store.write_mentions(d, ms, s.rule_version, s.mention_confidence, run_at,
                                         loose)
                total += r["written"]
                closed += r["closed"]
                n_values += r["values"]
                n_loose += r["unattached"]
                typer.echo(f"  {d.document.doc_key}: {r['written']} mentions, "
                           f"{r['values']} values on them, {r['unattached']} values with no "
                           f"entity, {r['closed']} older edges closed")
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.secho(f"Layer 2 ({s.rule_version}) written: {len(reg.entries)} entities, "
                f"{total} mentions carrying {n_values} values, {n_loose} values kept on "
                f"blocks without an entity; {closed} edges from older rule versions closed.",
                fg="green")


@app.command("confirm-queue")
def confirm_queue(config: Path = ConfigOption) -> None:
    """Record a person's answers for files that were uploaded and listed for
    confirmation (queue status "confirm: uploaded as <key>"). The answer must be
    `new` or the same doc_key; anything else is reported and not applied (to move
    a version to another document, delete and re-upload it)."""
    import csv as _csv

    cfg = load_config(config)
    queue = cfg.identify.queue_file
    if not queue.exists():
        typer.echo("No queue file.")
        return
    with queue.open(encoding="utf-8-sig", newline="") as f:
        rows = list(_csv.DictReader(f))
    done = 0
    try:
        with _open_store(config) as store:
            for r in rows:
                status, answer = r["status"], r["answer"].strip()
                if not status.startswith("confirm: uploaded as ") or not answer:
                    continue
                key = status.removeprefix("confirm: uploaded as ").split(" ")[0]
                if answer not in ("new", key):
                    typer.secho(f"  {r['file']}: answer {answer!r} differs from {key}; "
                                "not applied", fg="yellow")
                    continue
                n = store.confirm_identification(r["file_hash"], key, answer,
                                                 datetime.now(timezone.utc))
                typer.echo(f"  {r['file']}: {key} confirmed ({answer}), {n} edge(s)")
                done += n
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.secho(f"{done} identification(s) confirmed.", fg="green")


@app.command()
def embed(config: Path = ConfigOption) -> None:
    """Write e5 embeddings on the body blocks of every document's current version
    that have none, or one from another model (needs the `embed` dependency
    group: uv run --group embed kg embed)."""
    cfg = load_config(config)
    try:
        with _open_store(config) as store:
            blocks = store.current_body_blocks()
            todo = [b for b in blocks if b["embedding_model"] != cfg.embedding.model]
            typer.echo(f"  {len(blocks)} current body blocks, {len(todo)} need an embedding")
            if todo:
                from kg.embedding import Embedder

                emb = Embedder(cfg.embedding)
                vecs = emb.embed([b["text"] for b in todo], "passage")
                n = store.write_embeddings([(b["uid"], v) for b, v in zip(todo, vecs)],
                                           cfg.embedding.model)
                typer.echo(f"  wrote {n} embeddings ({emb.encoded} newly encoded, "
                           f"{emb.encode_seconds:.0f} s)")
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.secho("Embeddings up to date.", fg="green")


@app.command()
def impact(
    doc: list[str] = typer.Option(..., "--doc", help="doc_key of an uploaded document "
                                  "(repeat for every document of the upload event)"),
    check: bool = typer.Option(False, "--check", help="LLM check (step 13) of the top "
                               "impact.check_top_n candidates per change: verdict, reason and "
                               "evidence as columns; nothing is removed"),
    review: bool = typer.Option(False, "--review", help="Also write a review sheet (step 14) "
                                "for the changes the rule or the LLM flagged; needs --check"),
    config: Path = ConfigOption,
) -> None:
    """Impact analysis for the current version of each --doc (workflow steps 11-13):
    candidate blocks from the graph (valid REFERENCES, MENTIONS and values), then
    hybrid search (character trigrams + e5 vector index), ranked as set in
    config `impact.ranking`. With --check, the local LLM labels the top
    `impact.check_top_n` candidates (needs_update / not_affected / unsure, reason,
    evidence); needs_update moves first inside that top, except historical blocks;
    no candidate is dropped. Writes a CSV report under `impact.report_dir`.
    Needs the `embed` dependency group: uv run --group embed kg impact --doc ..."""
    import csv as _csv

    from kg.embedding import Embedder
    from kg.historical import historical_reason
    from kg.impact import (SIGNALS, Char3Index, GraphView, changes_from_stored_diff,
                           evidence_in, graph_first, graph_signals, impact_ranking,
                           order_after_check, rrf)
    from kg.llm import LLMClient

    cfg = load_config(config)
    if review and not check:
        typer.secho("--review needs --check (the sheet shows the LLM verdicts).", fg="red",
                    err=True)
        raise typer.Exit(2)
    try:
        with _open_store(config) as store:
            blocks = store.current_body_blocks()
            if any(b["embedding_model"] != cfg.embedding.model for b in blocks):
                typer.secho("Some current blocks have no embedding: run `kg embed` first.",
                            fg="red", err=True)
                raise typer.Exit(1)
            keys = sorted(e.doc_key for e in store.registry_entries())
            docs = [d for k in keys if (d := store.load_current_version(k)) is not None]
            view = GraphView.from_graph(blocks, store.impact_edges(), docs,
                                        load_manual(cfg.layer2.manual_file))
            info = {b["uid"]: b for b in blocks}
            lang = {d.document.doc_key: d.document.language.value for d in docs}
            items, changed_uids = [], set()
            for k in doc:
                diff = store.version_changes(k)
                if diff is None or diff["old_version_id"] is None and not diff["changed"]:
                    typer.secho(f"  {k}: no stored diff (upload it with `kg upload`)",
                                fg="yellow")
                    continue
                for c in diff["changed"]:
                    changed_uids |= {c["uid"], c["prev_uid"]}
                changed_uids |= {r["uid"] for r in diff["removed"]}
                items += [(k, it) for it in changes_from_stored_diff(k, diff, lang.get(k, "en"))]
            cands = {u: b["text"] for u, b in info.items() if u not in changed_uids}
            char3 = Char3Index(cands)
            emb = Embedder(cfg.embedding)
            title = {d.document.doc_key: d.document.title for d in docs}
            historical = {u for u, b in info.items()
                          if historical_reason(title.get(b["doc_key"], ""), b["text"])}
            checker = LLMClient.for_check(cfg.llm) if check else None
            rows, review_changes = [], []
            for k, it in items:
                query = it.old_text + "\n" + it.new_text
                q = emb.embed([query], "query")[0]
                e5 = [u for u, _ in store.vector_search(q, len(info)) if u in cands]
                hybrid = rrf(char3.ranking(query), e5)
                sig = graph_signals(view, it, set(cands))
                order = (graph_first(sig, hybrid) if cfg.impact.ranking == "graph_first"
                         else impact_ranking(sig, hybrid))
                verdicts: dict[str, object] = {}
                if checker is not None:
                    context = f"{it.doc_key} > {it.section_path}"
                    for u in order[: cfg.impact.check_top_n]:
                        res = checker.check_impact(it.old_text, it.new_text, info[u]["text"],
                                                   context)
                        verdicts[u] = res.data
                    order = order_after_check(
                        order, {u: v.verdict for u, v in verdicts.items() if v}, historical,
                        cfg.impact.check_top_n)
                # a rule hit (broken reference) always comes first, before LLM verdicts
                broken = [u for u in order if u in sig["broken_reference"]]
                order = broken + [u for u in order if u not in set(broken)]
                change_rows = []
                for rank, u in enumerate(order[: cfg.impact.top_n], start=1):
                    b = info[u]
                    v = verdicts.get(u)
                    checked = {}
                    if checker is not None:
                        ev = (v.evidence if v else "") or ""
                        checked = {
                            "verdict": (v.verdict if v else
                                        ("failed" if u in verdicts else "not checked")),
                            "reason": v.reason if v else "",
                            "evidence": ev,
                            "evidence_in_block": evidence_in(ev, b["text"]),
                            "historical": u in historical}
                    change_rows.append({
                        "document": k, "change": it.change_id, "changed_section": it.section_path,
                        "changed_block_uid": it.block_uid,
                        "rank": rank, "file": b["file"], "block_id": b["block_id"],
                        "block_uid": u,
                        "lines": f"{b['line_start']}-{b['line_end']}",
                        "signals": ";".join(s for s in SIGNALS if u in sig[s]) or "hybrid",
                        "rule": ("broken reference: the cited section or heading no longer "
                                 "exists" if u in sig["broken_reference"] else ""),
                        **checked,
                        "text": b["text"][:200].replace("\n", " ")})
                rows += change_rows
                if review:
                    review_changes.append({
                        "document": k, "change": it.change_id,
                        "changed_section": it.section_path, "old_text": it.old_text,
                        "new_text": it.new_text, "changed_block_uid": it.block_uid,
                        "candidates": [{**r, "text": info[r["block_uid"]]["text"]}
                                       for r in change_rows]})
                typer.echo(f"  {k} {it.change_id} ({it.section_path}): "
                           f"{sum(1 for s in SIGNALS for _ in sig[s])} graph hits, "
                           f"top {cfg.impact.top_n} reported")
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    except LLMUnavailable as e:
        _llm_unavailable(e)
    if checker is not None:
        calls = [c for c in checker.log if not c.cached]
        typer.echo(f"  LLM check: {len(checker.log)} checks ({len(calls)} new), "
                   f"{sum(c.tokens_in + c.tokens_out for c in calls)} tokens, "
                   f"{sum(c.seconds for c in calls) / 60:.1f} min")
        checker.close()
    cfg.impact.report_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.impact.report_dir / f"impact_{'_'.join(doc)}_{datetime.now():%Y%m%d-%H%M%S}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["document"])
        w.writeheader()
        w.writerows(rows)
    typer.secho(f"{len(items)} changes, {len(rows)} candidate rows -> {out}", fg="green")
    if review:
        from kg.backup import backup_labels
        from kg.review import review_rows, write_sheet

        sheet_rows = review_rows(review_changes, cfg.impact.check_top_n)
        n_changes = len({(r["document"], r["change"]) for r in sheet_rows})
        if not sheet_rows:
            typer.echo("  review: no change was flagged; no sheet written")
            return
        backup_labels(Path("data/labels"))
        sheet = cfg.impact.review_dir / f"review_{'_'.join(doc)}_{datetime.now():%Y%m%d-%H%M%S}.csv"
        write_sheet(sheet, sheet_rows)
        typer.secho(f"Review sheet: {n_changes} flagged changes, {len(sheet_rows)} rows -> "
                    f"{sheet}\n  Fill `decision` ({' / '.join(['needs_update', 'review_only', 'not_affected'])}) "
                    "and `note`, then run `kg review-import <sheet>`.", fg="green")


@app.command("full-update")
def full_update(config: Path = ConfigOption) -> None:
    """Workflow step 15: close the open REFERENCES, MENTIONS and DEPENDS edges of
    blocks that are in no current version (valid_to, not deleted), then apply the
    review history to the edges behind reviewed items (see `kg review-apply`)."""
    cfg = load_config(config)
    now = datetime.now(timezone.utc)
    try:
        with _open_store(config) as store:
            closed = store.close_edges_of_old_blocks(now)
            typer.echo(f"  closed edges of old blocks: {closed or 'none'}")
            _apply_reviews(store, cfg, now)
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.secho("Full update done.", fg="green")


def _apply_reviews(store, cfg, now) -> None:
    from kg.review import apply_reviews

    res = apply_reviews(store, cfg.impact.review_dir / "review_history.csv",
                        cfg.impact.review_reject_factor, now)
    typer.echo(f"  reviews: {res['decisions']} decisions, {res['rejected_edges']} edges "
               f"rejected, {res['approved_edges']} approved, {res['without_edges']} decisions "
               "with no edge behind them (reached by entity, value or hybrid search)")


@app.command("review-apply")
def review_apply(config: Path = ConfigOption) -> None:
    """Apply the review history to the graph: edges behind a not_affected decision
    get review_status = rejected and a lower confidence (x impact.review_reject_factor);
    behind needs_update / review_only, approved. Idempotent."""
    cfg = load_config(config)
    try:
        with _open_store(config) as store:
            _apply_reviews(store, cfg, datetime.now(timezone.utc))
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return


@app.command("review-import")
def review_import(
    sheet: Path = typer.Argument(..., help="A filled review sheet from `kg impact --review`"),
    config: Path = ConfigOption,
) -> None:
    """Append the decisions of a review sheet to the review history
    (`impact.review_dir`/review_history.csv). Label source: human_review (a person,
    system judgement shown). Unknown decision values stop the import."""
    from kg.review import import_decisions

    cfg = load_config(config)
    history = cfg.impact.review_dir / "review_history.csv"
    try:
        res = import_decisions(sheet, history, datetime.now(timezone.utc))
    except ValueError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from None
    typer.secho(f"{res['decided']} decisions in the sheet: {res['new']} new, {res['changed']} "
                f"changed, {res['unchanged']} already in {history}", fg="green")


@app.command()
def registry(config: Path = ConfigOption) -> None:
    """Show the document registry: the names and file names each document can be
    cited by. Add reviewed extra names in registry/aliases.yaml."""
    cfg = load_config(config)
    try:
        with _open_store(config) as store:
            reg = _registry(store, cfg)
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    names: dict[str, list[str]] = {}
    for name, key in reg.by_name.items():
        names.setdefault(key, []).append(name)
    for key, entry in sorted(reg.entries.items()):
        typer.echo(f"{key}")
        for n in names.get(key, []):
            typer.echo(f"    name: {n}")
        bases = [b for b, keys in reg.by_base.items() if key in keys]
        for b in bases:
            typer.echo(f"    name without year: {b}")
        for f in entry.file_names:
            typer.echo(f"    file: {f}")


def _report_queue(cfg, idents) -> None:
    """Add files that need a person to the queue file and say so."""
    added = add_to_queue(cfg.identify.queue_file, idents)
    for ident in idents:
        if ident.needs_person:
            typer.secho(f"  {ident.file}: not written, a person must decide ({ident.reason})",
                        fg="yellow")
        elif ident.confirm_later:
            typer.secho(f"  {ident.file}: written as {ident.doc_key}, please confirm "
                        f"({ident.reason})", fg="yellow")
    if added:
        typer.echo(f"Added {added} row(s) to {cfg.identify.queue_file}: fill in `answer` "
                   "with a doc_key or `new`, then rerun.")


@app.command()
def stats(config: Path = ConfigOption) -> None:
    """Show sections, blocks and NEXT edges per document version."""
    try:
        with _open_store(config) as store:
            rows = store.version_stats()
            snap = store.graph_snapshot()
            ents = store.entity_stats()
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return
    typer.echo(f"{'version':58} {'lang':4} {'sections':>8} {'blocks':>6} {'next':>5}")
    for r in rows:
        typer.echo(f"{r['version_id']:58} {r['language']:4} {r['sections']:>8} "
                   f"{r['blocks']:>6} {r['next_edges']:>5}")
    if ents:
        typer.echo(f"\n{'entities':8} {'lang':4} {'type':9} {'hub':5} {'count':>5} "
                   f"{'open MENTIONS':>13}")
        for r in ents:
            typer.echo(f"{'':8} {r['language']:4} {r['type']:9} {str(r['hub']):5} "
                       f"{r['entities']:>5} {r['mentions']:>13}")
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
) -> list[str]:
    """Upload new document versions: diff each file against its current version in the
    graph, then write the new version, reusing the node of every unchanged block.
    Returns the doc_keys written (used by `kg ingest`)."""
    if layer != 0:
        typer.secho(f"Layer {layer} is not implemented yet.", fg="red", err=True)
        raise typer.Exit(2)
    cfg = load_config(config)
    norm = Normalizer(cfg.layer0)
    files = sorted(event.glob("*.md"))
    if not files:
        typer.secho(f"No .md files in {event}", fg="red", err=True)
        raise typer.Exit(1)
    idents = []
    try:
        with _open_store(config) as store:
            candidates = store.identification_candidates(norm)
            answers = read_answers(cfg.identify.queue_file)
            todo, provenance = [], {}
            try:
                for path in files:
                    ident, doc = identify(path, candidates, cfg, _as_of(as_of), answers)
                    idents.append(ident)
                    if doc is None:
                        continue  # waits for a person
                    if store.version_exists(doc.version.version_id):
                        typer.echo(f"  {path.name}: already uploaded, skipped")
                        continue
                    typer.echo(f"  {path.name}: {doc.document.doc_key} ({ident.method}, "
                               f"{ident.reason})")
                    todo.append(doc)
                    provenance[doc.document.doc_key] = ident.provenance()
            except ParseError as e:
                typer.secho(str(e), fg="red", err=True)
                raise typer.Exit(1) from None
            olds = {}
            for doc in todo:
                old = store.load_current_version(doc.document.doc_key)
                if old is not None:
                    olds[doc.document.doc_key] = old
            diffs = diff_event(olds, todo, cfg.diff, norm)
            for d in diffs:
                counts = Counter(m.status.value for m in d.matches)
                # one transaction per document
                written = store.write_upload(d, provenance[d.doc_key])
                label = "new document" if d.old is None else f"supersedes {d.old.version.version_id}"
                typer.echo(f"  {d.new.version.source_file}: {label}")
                typer.echo(f"      diff {dict(counts)}")
                typer.echo(f"      nodes reused {written['reused_nodes']}, "
                           f"new {written['new_nodes']}")
            if diffs:
                # after every document of the event is written: moves cross documents
                res = store.write_diff_results(list(diffs))
                typer.echo(f"  diff stored on {res['blocks']} blocks, "
                           f"{res['removed']} removed blocks listed")
    except (AuthError, ServiceUnavailable) as e:
        _connection_error(e)
        return []
    _report_queue(cfg, idents)
    typer.secho(f"Uploaded {len(todo)} of {len(files)} files.", fg="green")
    return [d.document.doc_key for d in todo]


@app.command()
def doctor(config: Path = ConfigOption) -> None:
    """Check that everything a run needs is in place: config, Neo4j credentials
    (names only) and connection, schema and vector index, prompt files, writable
    data folders, the embedding model, and the local LLM in Ollama."""
    import json as _json
    import urllib.request

    ok = True

    def report(name: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= good
        typer.secho(f"  [{'ok' if good else 'FAIL'}] {name}" + (f": {detail}" if detail else ""),
                    fg="green" if good else "red")

    try:
        cfg = load_config(config)
        report("config.yaml", True)
    except Exception as e:  # noqa: BLE001
        report("config.yaml", False, type(e).__name__)
        raise typer.Exit(1) from None
    try:
        creds = load_neo4j_credentials()
        report("Neo4j credentials", True, "NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD set")
        with Store(creds, cfg.neo4j.database) as store:
            store.ping()
            report("Neo4j connection", True)
            names = store.schema_names()
            report("schema", "block_block_uid" in names, "run `kg init-schema`"
                   if "block_block_uid" not in names else "")
            report("vector index", "block_embedding" in names, "run `kg init-schema`"
                   if "block_embedding" not in names else "")
    except MissingEnvError as e:
        report("Neo4j credentials", False, str(e))
    except Exception as e:  # noqa: BLE001
        report("Neo4j connection", False, f"{type(e).__name__} (is the database started?)")
    for name in ("prompt_file", "check_prompt_file", "merge_prompt_file", "depends_prompt_file"):
        f = getattr(cfg.llm, name)
        report(f"prompt {f}", Path(f).exists())
    for folder in (cfg.impact.report_dir, cfg.impact.review_dir, cfg.llm.cache_file.parent,
                   Path("data/labels")):
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            probe = Path(folder) / ".kg_write_test"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            report(f"writable {folder}", True)
        except OSError as e:
            report(f"writable {folder}", False, type(e).__name__)
    try:
        import sentence_transformers  # noqa: F401
        report("embedding dependencies", True, "run with `uv run --group embed`")
    except ImportError:
        report("embedding dependencies", False, "use `uv run --group embed kg ...`")
    if cfg.llm.runtime == "openrouter":
        import os

        from dotenv import load_dotenv

        if Path(".env").exists():
            load_dotenv(Path(".env"), override=False)
        key = os.environ.get(cfg.llm.api_key_env)
        report(f"LLM key {cfg.llm.api_key_env}", bool(key), "" if key else "put it in .env")
        try:
            base = cfg.llm.endpoint.rstrip("/")
            with urllib.request.urlopen(base + "/models", timeout=15) as r:
                ids = {m["id"] for m in _json.loads(r.read().decode())["data"]}
            report(f"LLM model {cfg.llm.model}", cfg.llm.model in ids,
                   "on OpenRouter" if cfg.llm.model in ids else "not listed by OpenRouter")
            if key:  # key check: no document text is sent
                req = urllib.request.Request(base + "/key",
                                             headers={"Authorization": f"Bearer {key}"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    _json.loads(r.read().decode())
                report("OpenRouter key accepted", True,
                       "document text will be sent to OpenRouter and the model provider")
                req = urllib.request.Request(base + "/credits",
                                             headers={"Authorization": f"Bearer {key}"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    c = _json.loads(r.read().decode())["data"]
                left = float(c.get("total_credits") or 0) - float(c.get("total_usage") or 0)
                report("OpenRouter credits", left > 0,
                       f"{left:.2f} USD left" if left > 0 else
                       "none left: buy credits at openrouter.ai (the API answers HTTP 402)")
        except Exception as e:  # noqa: BLE001
            report("OpenRouter", False, type(e).__name__)
    else:
        try:
            with urllib.request.urlopen(cfg.llm.endpoint.rstrip("/") + "/api/tags",
                                        timeout=10) as r:
                models = {m["name"] for m in _json.loads(r.read().decode())["models"]}
            report("Ollama", True, cfg.llm.endpoint)
            report(f"LLM model {cfg.llm.model}", cfg.llm.model in models,
                   "" if cfg.llm.model in models else f"run `ollama pull {cfg.llm.model}`")
        except Exception as e:  # noqa: BLE001
            report("Ollama", False, f"{type(e).__name__} (is Ollama running?)")
    if not ok:
        raise typer.Exit(1)
    typer.secho("All checks passed.", fg="green")


@app.command()
def ingest(
    corpus: Path | None = typer.Option(None, "--corpus", help="First build: a folder of .md "
                                       "files that make up the store"),
    event: Path | None = typer.Option(None, "--event", help="An upload: a folder with new "
                                      "versions or new documents"),
    check: bool = typer.Option(False, "--check", help="LLM check of the impact candidates"),
    review: bool = typer.Option(False, "--review", help="Write a review sheet (needs --check)"),
    config: Path = ConfigOption,
) -> None:
    """Run the whole workflow in order (diagram v5).

    --corpus DIR: init-schema, layer 0 with identification, layers 1-2,
    embeddings, layer 3 (entity merge) and layer 4 (DEPENDS).

    --event DIR: upload + diff (steps 8-9), light update: layers 1-2 and
    embeddings (step 10), impact with optional LLM check and review sheet (steps
    11-14), full update: close edges of old blocks, apply reviews, layer 3, layer
    4 for the new and edited blocks (step 15).

    Needs the `embed` dependency group: uv run --group embed kg ingest ..."""
    if (corpus is None) == (event is None):
        typer.secho("Give exactly one of --corpus or --event.", fg="red", err=True)
        raise typer.Exit(2)
    if review and not check:
        typer.secho("--review needs --check.", fg="red", err=True)
        raise typer.Exit(2)
    t0 = datetime.now()

    def stage(name: str) -> None:
        typer.secho(f"\n== {name}", bold=True)

    if corpus is not None:
        stage("schema")
        init_schema(config=config)
        stage("layer 0: identify and parse")
        build(layer=0, corpus=corpus, as_of=None, config=config)
        stage("layer 1: references")
        _build_layer1(config)
        stage("layer 2: entities and values")
        _build_layer2(config)
        stage("embeddings")
        embed(config=config)
        stage("layer 3: entity merge")
        build_layer3(config)
        stage("layer 4: DEPENDS")
        build_layer4(config)
    else:
        stage("steps 8-9: identify, upload, diff")
        keys = upload(event=event, layer=0, as_of=None, config=config)
        if not keys:
            typer.secho("Nothing uploaded; stopping.", fg="yellow")
            return
        stage("step 10: light update (layers 1-2, embeddings)")
        _build_layer1(config)
        _build_layer2(config)
        embed(config=config)
        stage("steps 11-14: impact" + (" + LLM check" if check else "")
              + (" + review sheet" if review else ""))
        impact(doc=keys, check=check, review=review, config=config)
        stage("step 15: full update")
        full_update(config=config)
        build_layer3(config)
        with _open_store(config) as store:
            new_blocks = {c["uid"] for k in keys if (d := store.version_changes(k))
                          for c in d["changed"]}
        typer.echo(f"  layer 4 for {len(new_blocks)} new / edited blocks")
        build_layer4(config, only=new_blocks)
    minutes = (datetime.now() - t0).total_seconds() / 60
    typer.secho(f"\nIngest done in {minutes:.0f} min.", fg="green")


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


@app.command("backup-labels")
def backup_labels_cmd(
    labels: Path = typer.Option(Path("data/labels"), "--labels", help="Folder to back up"),
) -> None:
    """Copy data/labels/ to a dated folder outside the repository
    (KG_LABEL_BACKUP_DIR, default ~/kg_label_backups). Run before regenerating sheets."""
    from kg.backup import backup_labels

    dest = backup_labels(labels)
    if dest is None:
        typer.secho(f"Nothing to back up in {labels}.", fg="yellow")
        return
    n = sum(1 for p in dest.rglob("*") if p.is_file())
    typer.secho(f"Copied {n} files to {dest}", fg="green")


if __name__ == "__main__":
    app()
