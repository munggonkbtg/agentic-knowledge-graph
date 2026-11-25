"""All Neo4j reads and writes go through this module (coding rule 4)."""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath
from dataclasses import dataclass
from types import TracebackType

from neo4j import Driver, GraphDatabase, ManagedTransaction

from kg.config import Neo4jCredentials
from kg.diff import DocumentDiff, MatchStatus
from kg.identify import Candidate, candidate_from
from kg.layer0_structure import Normalizer, ParsedBlock, ParsedDocument, ParsedSection
from kg.layer1_references import Extraction, RegistryEntry
from kg.models import (
    Block,
    BlockKind,
    BlockRole,
    Document,
    Edge,
    EdgeType,
    Language,
    LineRange,
    Method,
    Provenance,
    Section,
    Version,
)

PIPELINE_LABELS = ("Document", "Version", "Section", "Block", "Alias", "Entity")

SMOKE_LABEL = "KgSmokeTest"

# Uniqueness constraints: Neo4j refuses a second node with the same key, and each
# constraint also creates an index on that key, so MERGE on it is fast.
_CONSTRAINTS: dict[str, tuple[str, str]] = {
    "document_doc_key": ("Document", "doc_key"),
    "version_version_id": ("Version", "version_id"),
    "section_section_id": ("Section", "section_id"),
    "block_block_uid": ("Block", "block_uid"),
    "alias_alias_id": ("Alias", "alias_id"),
    "entity_entity_id": ("Entity", "entity_id"),
}

# Plain index on Block.block_id, used by the diff to find blocks by position.
_NODE_INDEXES: dict[str, tuple[str, str]] = {
    "block_block_id": ("Block", "block_id"),
}


@dataclass(frozen=True)
class PingResult:
    server_agent: str
    server_address: str
    created_and_read: bool
    removed: bool


class Store:
    def __init__(self, creds: Neo4jCredentials, database: str) -> None:
        self._database = database
        self._driver: Driver = GraphDatabase.driver(
            creds.uri, auth=(creds.user, creds.password.get_secret_value())
        )

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _run(self, query: str, **params: object):
        return self._driver.execute_query(query, params, database_=self._database)

    # -- M0 --------------------------------------------------------------

    def ping(self) -> PingResult:
        """Create a test node, read it back, delete it, and confirm it is gone."""
        self._driver.verify_connectivity()
        info = self._driver.get_server_info()
        token = uuid.uuid4().hex

        self._run(f"CREATE (:{SMOKE_LABEL} {{token: $token}})", token=token)
        found = self._run(
            f"MATCH (n:{SMOKE_LABEL} {{token: $token}}) RETURN count(n) AS c", token=token
        ).records[0]["c"]
        self._run(f"MATCH (n:{SMOKE_LABEL} {{token: $token}}) DELETE n", token=token)
        left = self._run(
            f"MATCH (n:{SMOKE_LABEL} {{token: $token}}) RETURN count(n) AS c", token=token
        ).records[0]["c"]

        return PingResult(
            server_agent=info.agent,
            server_address=str(info.address),
            created_and_read=found == 1,
            removed=left == 0,
        )

    def ensure_schema(self) -> list[str]:
        """Create constraints and indexes if they do not exist. Safe to rerun."""
        statements: list[str] = []
        for name, (label, prop) in _CONSTRAINTS.items():
            statements.append(
                f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )
        for name, (label, prop) in _NODE_INDEXES.items():
            statements.append(
                f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
            )
        # One index per relationship type on valid_to, as the brief asks.
        # Caveat: Neo4j range indexes do not store null values, so this helps
        # "closed before date X" queries but NOT "valid_to IS NULL" (still valid).
        # See the open question in the M0 report.
        for edge_type in EdgeType:
            statements.append(
                f"CREATE INDEX rel_{edge_type.value.lower()}_valid_to IF NOT EXISTS "
                f"FOR ()-[r:{edge_type.value}]-() ON (r.valid_to)"
            )
        for statement in statements:
            self._run(statement)
        return statements

    def schema_names(self) -> set[str]:
        constraints = {r["name"] for r in self._run("SHOW CONSTRAINTS YIELD name").records}
        indexes = {r["name"] for r in self._run("SHOW INDEXES YIELD name").records}
        return constraints | indexes

    # -- M1: layer 0 writes ---------------------------------------------

    def write_layer0(self, doc: ParsedDocument,
                     identification: dict[str, object] | None = None) -> None:
        """Write one parsed document in a single transaction.

        Every write is a MERGE ("create only if missing"), and properties that
        record *when* something was created are set ON CREATE only, so running the
        build again leaves the graph exactly as it was. ``identification`` (from
        ``Identification.provenance()``) is stored on HAS_VERSION.
        """
        with self._driver.session(database=self._database) as session:
            session.execute_write(_write_layer0_tx, _layer0_payload(doc, identification))

    def identification_candidates(self, norm: Normalizer) -> list[Candidate]:
        """Current version of every document, as identification candidates."""
        keys = [r["k"] for r in self._run(
            "MATCH (d:Document) RETURN d.doc_key AS k ORDER BY k").records]
        out = []
        for key in keys:
            doc = self.load_current_version(key)
            if doc is not None:
                out.append(candidate_from(doc, norm))
        return out

    def graph_snapshot(self) -> dict[str, object]:
        """Counts and keys used to check that two builds produced the same graph."""
        labels = {
            r["label"]: r["n"]
            for r in self._run(
                "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n"
            ).records
        }
        rels = {
            r["t"]: r["n"]
            for r in self._run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n").records
        }
        uids = [
            r["uid"]
            for r in self._run("MATCH (b:Block) RETURN b.block_uid AS uid ORDER BY uid").records
        ]
        return {"labels": labels, "relationships": rels, "block_uids": uids}

    def version_stats(self) -> list[dict[str, object]]:
        return [
            dict(r)
            for r in self._run(
                """
                MATCH (d:Document)-[:HAS_VERSION]->(v:Version)
                CALL (v) {
                  MATCH (v)-[:CONTAINS*1..]->(s:Section) RETURN count(DISTINCT s) AS sections
                }
                CALL (v) {
                  MATCH (v)-[:CONTAINS*1..]->(:Section)-[:CONTAINS]->(b:Block)
                  RETURN count(DISTINCT b) AS blocks
                }
                CALL (v) {
                  MATCH (:Block)-[n:NEXT {version_id: v.version_id}]->(:Block)
                  RETURN count(n) AS next_edges
                }
                RETURN d.doc_key AS doc_key, d.language AS language,
                       v.version_id AS version_id, sections, blocks, next_edges
                ORDER BY doc_key, version_id
                """
            ).records
        ]

    # -- uploads (pipeline steps 8-9, layer 0 only) ----------------------

    def version_exists(self, version_id: str) -> bool:
        rec = self._run("MATCH (v:Version {version_id: $vid}) RETURN count(v) AS n",
                        vid=version_id).records[0]
        return rec["n"] > 0

    def load_current_version(self, doc_key: str) -> ParsedDocument | None:
        """Rebuild the current version of a document (valid_to is null) from the graph,
        so the diff can compare an upload with what is stored. None if unknown."""
        heads = self._run(
            """
            MATCH (d:Document {doc_key: $k})-[:HAS_VERSION]->(v:Version)
            WHERE v.valid_to IS NULL
            RETURN d {.*} AS d, v {.*} AS v
            """,
            k=doc_key,
        ).records
        if not heads:
            return None
        if len(heads) > 1:
            raise RuntimeError(f"{doc_key} has {len(heads)} current versions; expected 1")
        d, v = heads[0]["d"], heads[0]["v"]
        version = Version(
            doc_key=doc_key, file_hash=v["file_hash"], version_label=v["version_label"],
            source_file=v["source_file"], source_url=v.get("source_url"),
            license=v.get("license"), valid_from=_native(v["valid_from"]),
        )
        vid = v["version_id"]
        sections = []
        for r in self._run(
            """
            MATCH (v:Version {version_id: $vid})-[:CONTAINS*1..]->(s:Section)
            MATCH (parent)-[:CONTAINS]->(s)
            RETURN s {.*} AS s,
                   CASE WHEN parent:Section THEN parent.section_id END AS parent_id
            ORDER BY s.level = 0 DESC, s.line_start, s.level
            """,
            vid=vid,
        ).records:
            s = r["s"]
            section = Section(version_id=vid, heading_path=tuple(s["heading_path"]),
                              level=s["level"], title=s["title"],
                              lines=LineRange(start=s["line_start"], end=s["line_end"]))
            sections.append(ParsedSection(section, r["parent_id"]))
        blocks = []
        for r in self._run(
            """
            MATCH (v:Version {version_id: $vid})-[:CONTAINS*1..]->(s:Section)
                  -[c:CONTAINS]->(b:Block)
            RETURN b {.*} AS b, s.section_id AS sid, c.line_start AS ls, c.line_end AS le,
                   c.order AS ord, coalesce(c.block_id, b.block_id) AS bid
            ORDER BY ls
            """,
            vid=vid,
        ).records:
            b = r["b"]
            block = Block(
                doc_key=doc_key, block_id=r["bid"], block_uid=b["block_uid"],
                kind=BlockKind(b["kind"]), role=BlockRole(b.get("role", "body")),
                text=b["text"], content_hash=b["content_hash"],
                lines=LineRange(start=r["ls"], end=r["le"]), order=r["ord"],
                footnotes=tuple(b.get("footnotes") or ()),
            )
            blocks.append(ParsedBlock(block, r["sid"]))
        document = Document(doc_key=doc_key, title=d["title"], language=Language(d["language"]))
        return ParsedDocument(document, version, tuple(sections), tuple(blocks))

    def write_upload(self, diff: DocumentDiff,
                     identification: dict[str, object] | None = None) -> dict[str, int]:
        """Write the new version of one document in a single transaction.

        * Blocks the diff marks unchanged keep the node they matched, so edges on
          that node (layers 1-4) stay attached and need no re-extraction.
        * Edited, added and moved blocks get new nodes.
        * new Version -[:SUPERSEDES]-> previous Version; the previous Version gets
          valid_to = the new version's valid_from; Document.title takes the new title.
        """
        reuse = {m.new.block.block_uid: m.old.block.block_uid for m in diff.matches
                 if m.status == MatchStatus.UNCHANGED}
        new_blocks = tuple(
            ParsedBlock(pb.block.model_copy(update={"block_uid": reuse.get(
                pb.block.block_uid, pb.block.block_uid)}), pb.section_id)
            for pb in diff.new.blocks
        )
        uids = [pb.block.block_uid for pb in new_blocks]
        if len(uids) != len(set(uids)):
            raise RuntimeError(f"{diff.doc_key}: two blocks would share one node")
        doc = ParsedDocument(diff.new.document, diff.new.version, diff.new.sections, new_blocks)
        payload = _layer0_payload(doc, identification)
        payload["old_vid"] = diff.old.version.version_id if diff.old else None
        with self._driver.session(database=self._database) as session:
            session.execute_write(_write_upload_tx, payload)
        return {"blocks": len(new_blocks), "reused_nodes": len(reuse),
                "new_nodes": len(new_blocks) - len(reuse)}

    def delete_documents(self, doc_key_prefix: str) -> int:
        """Delete documents whose doc_key starts with the prefix, with their versions,
        sections and blocks (used by tests to clean up after themselves)."""
        if not doc_key_prefix:
            raise ValueError("refusing to delete with an empty prefix")
        rec = self._run(
            """
            MATCH (d:Document) WHERE d.doc_key STARTS WITH $p
            OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:Version)
            OPTIONAL MATCH (v)-[:CONTAINS*1..]->(x)
            WITH collect(DISTINCT d) + collect(DISTINCT v) + collect(DISTINCT x) AS nodes
            UNWIND nodes AS n
            WITH DISTINCT n
            DETACH DELETE n
            RETURN count(n) AS n
            """,
            p=doc_key_prefix,
        ).records
        return rec[0]["n"] if rec else 0

    # -- layer 1: REFERENCES --------------------------------------------

    def registry_entries(self) -> list[RegistryEntry]:
        """Documents in the store (not external stubs) and the file names they
        are known by (from source_url and source_file of every version)."""
        out = []
        for r in self._run(
            """
            MATCH (d:Document) WHERE coalesce(d.in_store, true)
            OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:Version)
            RETURN d.doc_key AS k, d.title AS t, d.language AS l,
                   collect(DISTINCT v.source_url) AS urls,
                   collect(DISTINCT v.source_file) AS files
            ORDER BY k
            """
        ).records:
            names = {PurePosixPath(u).name for u in r["urls"] if u} | set(r["files"])
            out.append(RegistryEntry(r["k"], r["t"], r["l"], tuple(sorted(names))))
        return out

    def write_references(self, doc: ParsedDocument, extraction: Extraction) -> int:
        """Write external stub documents and REFERENCES edges for one document in a
        single transaction. MERGE on (block, document, cited_section), properties
        set ON CREATE only, so a rerun changes nothing."""
        edges = []
        for r in extraction.references:
            edge = Edge(  # validates provenance and validity like every other edge
                type=EdgeType.REFERENCES, source_id=r.block_uid, target_id=r.target,
                valid_from=doc.version.valid_from,
                provenance=Provenance(method=Method.REGEX, evidence_block=r.block_uid,
                                      evidence_span=r.evidence_span, confidence=r.confidence),
                properties={"cited_section": r.cited_section, "resolution": r.resolution,
                            "self_reference": r.self_reference},
            )
            edges.append({
                "source": edge.source_id, "target": edge.target_id,
                "cited_section": r.cited_section,
                "props": {"method": edge.provenance.method.value,
                          "evidence_block": edge.provenance.evidence_block,
                          "evidence_span": edge.provenance.evidence_span,
                          "confidence": edge.provenance.confidence,
                          "valid_from": edge.valid_from, **edge.properties},
            })
        stubs = [{**s, "in_store": False} for s in extraction.stubs.values()]
        with self._driver.session(database=self._database) as session:
            session.execute_write(_write_references_tx, {"stubs": stubs, "edges": edges})
        return len(edges)

    def reference_stats(self) -> list[dict[str, object]]:
        return [dict(r) for r in self._run(
            """
            MATCH (b:Block)-[r:REFERENCES]->(d:Document)
            RETURN b.doc_key AS from_doc,
                   CASE WHEN r.self_reference THEN 'self'
                        WHEN coalesce(d.in_store, true) THEN d.doc_key
                        ELSE 'external (not in store)' END AS to_doc,
                   r.resolution AS resolution, count(*) AS edges
            ORDER BY from_doc, edges DESC
            """
        ).records]

    def reset_pipeline_data(self) -> int:
        """Delete every node the pipeline created (constraints and indexes stay)."""
        labels = " OR ".join(f"n:{label}" for label in PIPELINE_LABELS)
        rec = self._run(f"MATCH (n) WHERE {labels} DETACH DELETE n RETURN count(n) AS n")
        return rec.records[0]["n"]

    def fulltext_analyzers(self) -> list[str]:
        records = self._run(
            "CALL db.index.fulltext.listAvailableAnalyzers() YIELD analyzer "
            "RETURN analyzer ORDER BY analyzer"
        ).records
        return [r["analyzer"] for r in records]


# ---------------------------------------------------------------- layer 0 writes
#
# Layout written by layer 0:
#   (Document)-[:HAS_VERSION]->(Version)-[:CONTAINS]->(root Section)
#   (Section)-[:CONTAINS]->(child Section)        one per heading
#   (Section)-[:CONTAINS {block_id, line_start, line_end, order, version_id}]->(Block)
#   (Block)-[:NEXT {version_id}]->(Block)          document order within a version
#
# Position (block_id, line range, order) lives on the Section->Block CONTAINS edge
# because one Block node can be shared by several versions: an upload reuses the
# node of every block the diff finds unchanged, wherever it now sits.


def _edge_props(method: Method, valid_from) -> dict[str, object]:
    # valid_to is left unset: in Neo4j a missing property reads as null ("still valid").
    return {"method": method.value, "confidence": 1.0, "valid_from": valid_from}


def _layer0_payload(doc: ParsedDocument,
                   identification: dict[str, object] | None = None) -> dict[str, object]:
    v = doc.version
    vid = v.version_id
    sections = [
        {
            "section_id": ps.section.section_id,
            "parent_id": ps.parent_id,
            "props": {
                "section_id": ps.section.section_id,
                "version_id": vid,
                "heading_path": list(ps.section.heading_path),
                "level": ps.section.level,
                "title": ps.section.title,
                "line_start": ps.section.lines.start,
                "line_end": ps.section.lines.end,
            },
        }
        for ps in doc.sections
    ]
    blocks = [
        {
            "block_uid": pb.block.block_uid,
            "block_id": pb.block.block_id,
            "section_id": pb.section_id,
            "line_start": pb.block.lines.start,
            "line_end": pb.block.lines.end,
            "order": pb.block.order,
            "props": {
                "block_uid": pb.block.block_uid,
                "block_id": pb.block.block_id,
                "doc_key": pb.block.doc_key,
                "kind": pb.block.kind.value,
                "role": pb.block.role.value,
                "text": pb.block.text,
                "content_hash": pb.block.content_hash,
                "footnotes": list(pb.block.footnotes),
            },
        }
        for pb in doc.blocks
    ]
    uids = [b["block_uid"] for b in blocks]
    return {
        "doc": {
            "doc_key": doc.document.doc_key,
            "title": doc.document.title,
            "language": doc.document.language.value,
            "access": list(doc.document.access),
        },
        "version": {
            "version_id": vid,
            "doc_key": v.doc_key,
            "file_hash": v.file_hash,
            "version_label": v.version_label,
            "source_file": v.source_file,
            "source_url": v.source_url,
            "license": v.license,
            "valid_from": v.valid_from,
        },
        "vid": vid,
        "root": [s for s in sections if s["parent_id"] is None],
        "children": [s for s in sections if s["parent_id"] is not None],
        "blocks": blocks,
        "next_pairs": [{"a": a, "b": b} for a, b in zip(uids, uids[1:])],
        "meta_edge": _edge_props(Method.METADATA, v.valid_from),
        "parser_edge": _edge_props(Method.PARSER, v.valid_from),
        # How the document was identified (method, confidence, scores).
        "has_version_edge": {**_edge_props(Method.METADATA, v.valid_from),
                             **(identification or {})},
    }


def _write_layer0_tx(tx: ManagedTransaction, p: dict[str, object]) -> None:
    tx.run(
        """
        MERGE (d:Document {doc_key: $doc.doc_key})
          ON CREATE SET d += $doc
        MERGE (v:Version {version_id: $version.version_id})
          ON CREATE SET v += $version
        MERGE (d)-[r:HAS_VERSION]->(v)
          ON CREATE SET r += $has_version_edge
        """,
        p,
    ).consume()
    # Create all section nodes first, then connect them, so a child never looks
    # for a parent that has not been written yet.
    tx.run(
        """
        UNWIND $root + $children AS s
        MERGE (n:Section {section_id: s.section_id})
          ON CREATE SET n += s.props
        """,
        p,
    ).consume()
    tx.run(
        """
        UNWIND $root AS s
        MATCH (v:Version {version_id: $vid}), (n:Section {section_id: s.section_id})
        MERGE (v)-[r:CONTAINS]->(n)
          ON CREATE SET r += $parser_edge
        """,
        p,
    ).consume()
    tx.run(
        """
        UNWIND $children AS s
        MATCH (parent:Section {section_id: s.parent_id}), (n:Section {section_id: s.section_id})
        MERGE (parent)-[r:CONTAINS]->(n)
          ON CREATE SET r += $parser_edge
        """,
        p,
    ).consume()
    tx.run(
        """
        UNWIND $blocks AS b
        MERGE (n:Block {block_uid: b.block_uid})
          ON CREATE SET n += b.props
        WITH n, b
        MATCH (s:Section {section_id: b.section_id})
        MERGE (s)-[r:CONTAINS]->(n)
          ON CREATE SET r += $parser_edge,
                        r.version_id = $vid,
                        r.block_id = b.block_id,
                        r.line_start = b.line_start,
                        r.line_end = b.line_end,
                        r.order = b.order
        """,
        p,
    ).consume()
    tx.run(
        """
        UNWIND $next_pairs AS pair
        MATCH (a:Block {block_uid: pair.a}), (b:Block {block_uid: pair.b})
        MERGE (a)-[r:NEXT {version_id: $vid}]->(b)
          ON CREATE SET r += $parser_edge
        """,
        p,
    ).consume()


def _native(value):
    """neo4j DateTime -> Python datetime (other values pass through)."""
    return value.to_native() if hasattr(value, "to_native") else value


def _write_upload_tx(tx: ManagedTransaction, p: dict[str, object]) -> None:
    _write_layer0_tx(tx, p)
    tx.run(
        "MATCH (d:Document {doc_key: $doc.doc_key}) SET d.title = $doc.title",
        p,
    ).consume()
    if p["old_vid"] is not None:
        tx.run(
            """
            MATCH (new:Version {version_id: $vid}), (old:Version {version_id: $old_vid})
            MERGE (new)-[r:SUPERSEDES]->(old)
              ON CREATE SET r += $meta_edge
            SET old.valid_to = coalesce(old.valid_to, $version.valid_from)
            """,
            p,
        ).consume()


def _write_references_tx(tx: ManagedTransaction, p: dict[str, object]) -> None:
    tx.run(
        """
        UNWIND $stubs AS s
        MERGE (d:Document {doc_key: s.doc_key})
          ON CREATE SET d += s
        """,
        p,
    ).consume()
    tx.run(
        """
        UNWIND $edges AS e
        MATCH (b:Block {block_uid: e.source}), (d:Document {doc_key: e.target})
        MERGE (b)-[r:REFERENCES {cited_section: e.cited_section}]->(d)
          ON CREATE SET r += e.props
        """,
        p,
    ).consume()
