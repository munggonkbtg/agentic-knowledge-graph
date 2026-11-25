"""All Neo4j reads and writes go through this module (coding rule 4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import TracebackType

from neo4j import Driver, GraphDatabase, ManagedTransaction

from kg.config import Neo4jCredentials
from kg.layer0_structure import ParsedDocument
from kg.models import EdgeType, Method

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

    def write_layer0(self, doc: ParsedDocument) -> None:
        """Write one parsed document in a single transaction.

        Every write is a MERGE ("create only if missing"), and properties that
        record *when* something was created are set ON CREATE only, so running the
        build again leaves the graph exactly as it was.
        """
        with self._driver.session(database=self._database) as session:
            session.execute_write(_write_layer0_tx, _layer0_payload(doc))

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
#   (Section)-[:CONTAINS {line_start, line_end, order, version_id}]->(Block)
#   (Block)-[:NEXT {version_id}]->(Block)          document order within a version
#
# Line range and order live on the Section->Block CONTAINS edge because one Block
# node can be shared by several versions (same position, same text).


def _edge_props(method: Method, valid_from) -> dict[str, object]:
    # valid_to is left unset: in Neo4j a missing property reads as null ("still valid").
    return {"method": method.value, "confidence": 1.0, "valid_from": valid_from}


def _layer0_payload(doc: ParsedDocument) -> dict[str, object]:
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
    }


def _write_layer0_tx(tx: ManagedTransaction, p: dict[str, object]) -> None:
    tx.run(
        """
        MERGE (d:Document {doc_key: $doc.doc_key})
          ON CREATE SET d += $doc
        MERGE (v:Version {version_id: $version.version_id})
          ON CREATE SET v += $version
        MERGE (d)-[r:HAS_VERSION]->(v)
          ON CREATE SET r += $meta_edge
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
