"""All Neo4j reads and writes go through this module (coding rule 4)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import PurePosixPath
from dataclasses import dataclass
from types import TracebackType

from neo4j import Driver, GraphDatabase, ManagedTransaction

from kg.config import Neo4jCredentials
from kg.diff import DocumentDiff, MatchStatus
from kg.identify import Candidate, candidate_from
from kg.layer0_structure import Normalizer, ParsedBlock, ParsedDocument, ParsedSection
from kg.layer1_references import Extraction, RegistryEntry, slug
from kg.layer2_entities import EntityEntry, EntityRegistry, Mention
from kg.values import AttachedValue
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
VECTOR_INDEX = "block_embedding"

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

    def ensure_schema(self, vector_dimensions: int = 1024) -> list[str]:
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
        # Vector index on Block.embedding for hybrid search (M5; e5 vectors are
        # normalized, so cosine similarity).
        statements.append(
            f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS FOR (b:Block) ON (b.embedding) "
            "OPTIONS {indexConfig: {`vector.dimensions`: "
            f"{vector_dimensions}, `vector.similarity_function`: 'cosine'}}}}"
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

    # -- layer 3: entity merge ----------------------------------------------

    def entities_for_merge(self, examples: int = 2) -> list[dict[str, object]]:
        """Entities of the registry with their open mentions on current blocks and
        up to `examples` short passages (for the LLM)."""
        return [dict(r) for r in self._run(
            """
            MATCH (e:Entity)
            OPTIONAL MATCH (b:Block)-[m:MENTIONS]->(e) WHERE m.valid_to IS NULL
            WITH e, collect(b.text) AS texts
            RETURN e.entity_id AS entity_id, e.canonical_name AS name,
                   e.entity_type AS entity_type, e.language AS language,
                   coalesce(e.hub, false) AS hub, coalesce(e.sources, []) AS sources,
                   size(texts) AS mentions,
                   [t IN texts[0..$n] | substring(t, 0, 240)] AS examples
            ORDER BY entity_id
            """, n=examples).records]

    def write_merges(self, canonical: dict[str, str], reasons: dict[str, str],
                     rule_version: str, model: str, prompt_version: str, confidence: float,
                     run_at: datetime) -> dict[str, int]:
        """Layer 3 result, reversible: each merged entity gets merged_into and its
        aliases get ALIAS_OF to the canonical entity (method llm, model,
        prompt_version, evidence_span = the LLM's reason). Merges of this rule
        version that are no longer in `canonical` are undone: merged_into removed,
        their ALIAS_OF closed (valid_to)."""
        rows = [{"merged": m, "canonical": c, "reason": reasons.get(m, "")}
                for m, c in sorted(canonical.items())]
        p = {"rows": rows, "rv": rule_version, "model": model, "pv": prompt_version,
             "conf": confidence, "t": run_at, "merged": sorted(canonical)}
        with self._driver.session(database=self._database) as session:
            return session.execute_write(_write_merges_tx, p)

    def entity_merges(self) -> dict[str, str]:
        return {r["e"]: r["c"] for r in self._run(
            "MATCH (e:Entity) WHERE e.merged_into IS NOT NULL "
            "RETURN e.entity_id AS e, e.merged_into AS c").records}

    # -- layer 4: DEPENDS ----------------------------------------------------

    def nearest_blocks(self, block_uid: str, k: int, current: set[str]) -> list[str]:
        """Nearest blocks by the stored e5 vector, restricted to `current`."""
        rows = self._run(
            f"""
            MATCH (b:Block {{block_uid: $u}}) WHERE b.embedding IS NOT NULL
            CALL db.index.vector.queryNodes('{VECTOR_INDEX}', $n, b.embedding)
            YIELD node, score
            RETURN node.block_uid AS uid ORDER BY score DESC
            """, u=block_uid, n=k + 40).records
        return [r["uid"] for r in rows if r["uid"] != block_uid and r["uid"] in current][:k]

    def write_depends(self, edges: list, processed: list[str], rule_version: str, model: str,
                      prompt_version: str, confidence: float, run_at: datetime) -> dict[str, int]:
        """(dependent)-[:DEPENDS]->(source) per edge, MERGE on rule_version,
        properties on create only. DEPENDS of the processed blocks from an older
        rule version are closed (valid_to)."""
        rows = []
        for e in edges:
            edge = Edge(type=EdgeType.DEPENDS, source_id=e.dependent, target_id=e.source,
                        valid_from=run_at,
                        provenance=Provenance(method=Method.LLM, evidence_block=e.dependent,
                                              evidence_span=e.evidence_dependent, model=model,
                                              prompt_version=prompt_version,
                                              confidence=confidence),
                        properties={"fact": e.fact, "evidence_target": e.evidence_source})
            rows.append({"a": edge.source_id, "b": edge.target_id, "props": {
                "method": "llm", "model": model, "prompt_version": prompt_version,
                "confidence": confidence, "valid_from": run_at,
                "evidence_block": e.dependent, "evidence_span": e.evidence_dependent,
                **edge.properties}})
        p = {"rows": rows, "rv": rule_version, "t": run_at, "uids": processed}
        with self._driver.session(database=self._database) as session:
            return session.execute_write(_write_depends_tx, p)

    # -- step 15: full update ----------------------------------------------

    def close_edges_of_old_blocks(self, run_at: datetime,
                                  doc_key_prefix: str = "") -> dict[str, int]:
        """Close (valid_to, closed_reason) the open REFERENCES, MENTIONS and DEPENDS
        edges of blocks that are in no current version: replaced by an edit,
        removed, or moved away. Blocks reused by a current version keep theirs.
        Nothing is deleted. `doc_key_prefix` limits it to blocks of matching
        documents (tests). Returns the number of edges closed per type."""
        recs = self._run(
            """
            MATCH (v:Version) WHERE v.valid_to IS NULL
            MATCH (:Section)-[:CONTAINS {version_id: v.version_id}]->(b:Block)
            WITH collect(DISTINCT b.block_uid) AS current
            MATCH (b:Block)-[r:REFERENCES|MENTIONS|DEPENDS]-()
            WHERE r.valid_to IS NULL AND NOT b.block_uid IN current
              AND b.doc_key STARTS WITH $p
              AND (type(r) = 'DEPENDS' OR startNode(r) = b)
            WITH DISTINCT r
            SET r.valid_to = $t, r.closed_reason = 'block no longer current'
            RETURN type(r) AS type, count(r) AS n
            """, t=run_at, p=doc_key_prefix).records
        return {r["type"]: r["n"] for r in recs}

    def citation_edges(self, block_uid: str, target_doc: str) -> list[dict[str, object]]:
        """Open REFERENCES from a block to a document, with their element ids."""
        return [dict(r) for r in self._run(
            """
            MATCH (:Block {block_uid: $u})-[r:REFERENCES]->(:Document {doc_key: $d})
            WHERE r.valid_to IS NULL
            RETURN elementId(r) AS id, r.cited_section AS cited_section
            """, u=block_uid, d=target_doc).records]

    def depends_between(self, a: str, b: str) -> list[str]:
        """Open DEPENDS edges between two blocks, either direction."""
        return [r["id"] for r in self._run(
            """
            MATCH (:Block {block_uid: $a})-[r:DEPENDS]-(:Block {block_uid: $b})
            WHERE r.valid_to IS NULL RETURN DISTINCT elementId(r) AS id
            """, a=a, b=b).records]

    def block_position(self, block_uid: str) -> dict[str, object] | None:
        rec = self._run(
            """
            MATCH (:Section)-[c:CONTAINS]->(b:Block {block_uid: $u})
            RETURN b.doc_key AS doc_key, c.block_id AS block_id ORDER BY c.version_id LIMIT 1
            """, u=block_uid).records
        return dict(rec[0]) if rec else None

    def set_review_status(self, edge_ids: list[str], status: str, factor: float,
                          run_at: datetime) -> int:
        """Record a person's review on edges (step 15). rejected: confidence =
        original x factor; approved: confidence back to the original. The original
        is kept in confidence_before_review, so applying twice changes nothing."""
        if not edge_ids:
            return 0
        rec = self._run(
            """
            MATCH ()-[r]->() WHERE elementId(r) IN $ids
            SET r.confidence_before_review = coalesce(r.confidence_before_review, r.confidence),
                r.review_status = $s, r.reviewed_at = $t
            SET r.confidence = CASE $s WHEN 'rejected' THEN r.confidence_before_review * $f
                                       ELSE r.confidence_before_review END
            RETURN count(r) AS n
            """, ids=edge_ids, s=status, f=factor, t=run_at)
        return rec.records[0]["n"]

    def confirm_identification(self, file_hash: str, doc_key: str, answer: str,
                               confirmed_at: datetime) -> int:
        """Record a person's answer for a file that was uploaded but listed for
        confirmation: on the HAS_VERSION edge of the version with this file hash,
        identification_confirmed = 'person', the answer and the time. Returns the
        number of edges updated (0 when the file is not in the graph)."""
        rec = self._run(
            """
            MATCH (d:Document {doc_key: $k})-[r:HAS_VERSION]->(v:Version {file_hash: $h})
            SET r.identification_confirmed = 'person', r.identification_answer = $a,
                r.identification_confirmed_at = $t
            RETURN count(r) AS n
            """, k=doc_key, h=file_hash, a=answer, t=confirmed_at)
        return rec.records[0]["n"]

    # -- M5: embeddings, current blocks, vector search ----------------------

    def current_body_blocks(self) -> list[dict[str, object]]:
        """Body blocks of the current version (valid_to null) of every document in
        the store, with their position in that version."""
        return [dict(r) for r in self._run(
            """
            MATCH (d:Document)-[:HAS_VERSION]->(v:Version) WHERE v.valid_to IS NULL
            MATCH (v)-[:CONTAINS]->(:Section)-[:CONTAINS*0..]->(:Section)
                  -[c:CONTAINS {version_id: v.version_id}]->(b:Block)
            WHERE b.role = 'body'
            RETURN DISTINCT b.block_uid AS uid, b.text AS text, d.doc_key AS doc_key,
                   d.language AS language, v.version_id AS version_id,
                   v.source_file AS file, c.block_id AS block_id,
                   c.line_start AS line_start, c.line_end AS line_end,
                   b.embedding_model AS embedding_model
            ORDER BY uid
            """
        ).records]

    def impact_edges(self) -> dict[str, list[dict[str, object]]]:
        """What the impact search traverses (valid edges only): REFERENCES from
        current blocks, MENTIONS from current blocks with their values, values
        kept on blocks without an entity, and the hub entities."""
        current = ("MATCH (d:Document)-[:HAS_VERSION]->(v:Version) WHERE v.valid_to IS NULL "
                   "MATCH (v)-[:CONTAINS]->(:Section)-[:CONTAINS*0..]->(:Section)"
                   "-[:CONTAINS {version_id: v.version_id}]->(b:Block) WHERE b.role = 'body' ")
        refs = [dict(r) for r in self._run(
            current + """
            MATCH (b)-[r:REFERENCES]->(t:Document) WHERE r.valid_to IS NULL
            RETURN DISTINCT b.block_uid AS uid, t.doc_key AS target,
                   r.cited_section AS cited_section, r.confidence AS confidence
            """).records]
        mentions = [dict(r) for r in self._run(
            current + """
            MATCH (b)-[m:MENTIONS]->(e:Entity) WHERE m.valid_to IS NULL
            RETURN DISTINCT b.block_uid AS uid, e.entity_id AS entity, e.hub AS hub,
                   m.value AS value, m.unit AS unit, m.family AS family,
                   m.base_value AS base_value, m.base_unit AS base_unit,
                   m.value_text AS value_text, m.attribute AS attribute
            """).records]
        loose = [dict(r) for r in self._run(
            current + """
            WITH DISTINCT b WHERE b.unattached_value IS NOT NULL
            RETURN b.block_uid AS uid, b.unattached_value AS value,
                   b.unattached_unit AS unit, b.unattached_family AS family,
                   b.unattached_base_value AS base_value,
                   b.unattached_base_unit AS base_unit,
                   b.unattached_value_text AS value_text,
                   b.unattached_attribute AS attribute
            """).records]
        hubs = [r["e"] for r in self._run(
            "MATCH (e:Entity) WHERE e.hub = true RETURN e.entity_id AS e").records]
        depends = [(r["a"], r["b"]) for r in self._run(
            """
            MATCH (a:Block)-[r:DEPENDS]->(b:Block) WHERE r.valid_to IS NULL
            RETURN a.block_uid AS a, b.block_uid AS b
            """).records]
        return {"refs": refs, "mentions": mentions, "loose": loose, "hubs": hubs,
                "merges": self.entity_merges(), "depends": depends}

    def version_changes(self, doc_key: str) -> dict[str, object] | None:
        """The diff stored for the current version of a document against the
        version it supersedes: changed blocks (edited / moved / added, with the
        previous block) and removed blocks, with texts."""
        rec = self._run(
            """
            MATCH (d:Document {doc_key: $k})-[:HAS_VERSION]->(v:Version)
            WHERE v.valid_to IS NULL
            OPTIONAL MATCH (v)-[:SUPERSEDES]->(old:Version)
            RETURN v.version_id AS vid, old.version_id AS old_vid,
                   coalesce(v.removed_block_uids, []) AS removed
            """, k=doc_key).records
        if not rec:
            return None
        vid, old_vid, removed = rec[0]["vid"], rec[0]["old_vid"], rec[0]["removed"]
        changed = [dict(r) for r in self._run(
            """
            MATCH (:Section)-[c:CONTAINS {version_id: $vid}]->(b:Block)
            WHERE c.diff_status IN ['edited', 'moved', 'added'] AND b.role = 'body'
            OPTIONAL MATCH (p:Block {block_uid: c.previous_block_uid})
            OPTIONAL MATCH (:Section)-[pc:CONTAINS]->(p)
            WITH b, c, p, pc ORDER BY pc.version_id
            WITH b, c, p, collect(pc)[0] AS pc
            RETURN b.block_uid AS uid, b.text AS new_text, c.block_id AS block_id,
                   c.diff_status AS status, p.block_uid AS prev_uid, p.text AS old_text,
                   p.doc_key AS prev_doc, pc.block_id AS prev_block_id
            ORDER BY c.order, uid
            """, vid=vid).records]
        gone = [dict(r) for r in self._run(
            """
            UNWIND $uids AS u
            MATCH (b:Block {block_uid: u}) WHERE b.role = 'body'
            OPTIONAL MATCH (:Section)-[c:CONTAINS {version_id: $old}]->(b)
            RETURN b.block_uid AS uid, b.text AS old_text, c.block_id AS block_id
            """, uids=removed, old=old_vid).records]
        return {"version_id": vid, "old_version_id": old_vid, "changed": changed,
                "removed": gone}

    def write_embeddings(self, rows: list[tuple[str, list[float]]], model: str) -> int:
        if not rows:
            return 0
        self._run(
            """
            UNWIND $rows AS x
            MATCH (b:Block {block_uid: x.uid})
            SET b.embedding = x.vec, b.embedding_model = $model
            """,
            rows=[{"uid": u, "vec": v} for u, v in rows], model=model,
        )
        return len(rows)

    def vector_search(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        """Nearest blocks by cosine similarity (any version; the caller filters)."""
        return [(r["uid"], r["score"]) for r in self._run(
            f"""
            CALL db.index.vector.queryNodes('{VECTOR_INDEX}', $k, $v) YIELD node, score
            RETURN node.block_uid AS uid, score
            """, k=k, v=vector).records]

    def write_diff_results(self, diffs: list[DocumentDiff]) -> dict[str, int]:
        """Store what the diff found for one upload event (workflow step 9), after
        the new versions are written:

        * on the CONTAINS edge from a section of the new version to each block:
          diff_status (unchanged / edited / moved / added), previous_block_uid
          (the old block, for edited / moved / unchanged) and diff_similarity;
        * on the new Version: removed_block_uids (old blocks with no partner).

        A moved block's new node usually sits in another document of the event
        (E3 -> E2), so the whole event is written together. Where one new block is
        claimed twice (added in its own document, moved in from another), moved
        wins."""
        new_vid = {d.new.document.doc_key: d.new.version.version_id for d in diffs if d.new}
        rank = {"added": 0, "unchanged": 1, "edited": 2, "moved": 3}
        rows: dict[tuple[str, str], dict] = {}
        removed: dict[str, list[str]] = defaultdict(list)
        for d in diffs:
            for m in d.matches:
                if m.status == MatchStatus.REMOVED:
                    if d.new is not None:
                        removed[d.new.version.version_id].append(m.old.block.block_uid)
                    continue
                for pb in m.new_blocks:
                    uid = (m.old.block.block_uid if m.status == MatchStatus.UNCHANGED
                           else pb.block.block_uid)
                    vid = new_vid.get(pb.block.doc_key)
                    if vid is None:
                        continue
                    row = {"vid": vid, "uid": uid, "status": m.status.value,
                           "prev": m.old.block.block_uid if m.old else None,
                           "sim": m.similarity}
                    old = rows.get((vid, uid))
                    if old is None or rank[row["status"]] > rank[old["status"]]:
                        rows[(vid, uid)] = row
        p = {"rows": list(rows.values()),
             "removed": [{"vid": v, "uids": sorted(u)} for v, u in removed.items()],
             "versions": sorted(new_vid.values())}
        with self._driver.session(database=self._database) as session:
            session.execute_write(_write_diff_tx, p)
        return {"blocks": len(rows), "removed": sum(len(u) for u in removed.values())}

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

    def write_references(self, doc: ParsedDocument, extraction: Extraction,
                         rule_version: str, run_at: datetime) -> dict[str, int]:
        """Write external stub documents and REFERENCES edges for one document in a
        single transaction.

        MERGE on (block, document, cited_section, rule_version), properties set ON
        CREATE only, so a rerun with the same rules changes nothing. Edges from
        this document's blocks made by an *older* rule version are closed
        (valid_to = run_at), not deleted, so the change stays traceable."""
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
                          "valid_from": edge.valid_from, "rule_version": rule_version,
                          **edge.properties},
            })
        stubs = [{**s, "in_store": False} for s in extraction.stubs.values()]
        payload = {"stubs": stubs, "edges": edges, "rule_version": rule_version,
                   "run_at": run_at, "uids": [pb.block.block_uid for pb in doc.blocks]}
        with self._driver.session(database=self._database) as session:
            closed = session.execute_write(_write_references_tx, payload)
        return {"written": len(edges), "closed": closed}

    def reference_stats(self) -> list[dict[str, object]]:
        return [dict(r) for r in self._run(
            """
            MATCH (b:Block)-[r:REFERENCES]->(d:Document) WHERE r.valid_to IS NULL
            RETURN b.doc_key AS from_doc,
                   CASE WHEN r.self_reference THEN 'self'
                        WHEN coalesce(d.in_store, true) THEN d.doc_key
                        ELSE 'external (not in store)' END AS to_doc,
                   r.resolution AS resolution, count(*) AS edges
            ORDER BY from_doc, edges DESC
            """
        ).records]

    # -- layer 2 (entities) ---------------------------------------------

    def write_entity_registry(self, entries: list[EntityEntry], share: dict[str, float],
                              rule_version: str, run_at: datetime) -> dict[str, int]:
        """Entity and Alias nodes and ALIAS_OF edges, in one transaction.

        Entity properties (type, name, hub, block_share, sources) are set on every
        run, because the hub flag follows the current corpus. ALIAS_OF is merged on
        (alias, entity, rule_version) with properties set on create only; edges of
        these aliases from an older rule version are closed (valid_to)."""
        entities, aliases = [], []
        for e in entries:
            entities.append({"entity_id": e.entity_id, "props": {
                "entity_type": e.entity_type, "canonical_name": e.name,
                "language": e.language, "hub": e.hub,
                "block_share": round(share.get(e.entity_id, 0.0), 4),
                "sources": sorted(e.sources), "rule_version": rule_version}})
            method = alias_method(e.sources)
            for a in sorted(e.aliases):
                edge = Edge(type=EdgeType.ALIAS_OF, source_id=alias_id(e.language, a),
                            target_id=e.entity_id, valid_from=run_at,
                            provenance=Provenance(method=method, evidence_span=a))
                aliases.append({"alias_id": edge.source_id, "entity_id": edge.target_id,
                                "props": {"surface": a, "language": e.language},
                                "edge": {"method": method.value, "confidence": 1.0,
                                         "valid_from": run_at}})
        p = {"entities": entities, "aliases": aliases, "rule_version": rule_version,
             "run_at": run_at}
        with self._driver.session(database=self._database) as session:
            closed = session.execute_write(_write_entity_registry_tx, p)
        return {"entities": len(entities), "aliases": len(aliases), "closed": closed}

    def write_mentions(self, doc: ParsedDocument, mentions: list[Mention],
                       rule_version: str, confidence: float, run_at: datetime,
                       unattached: dict[str, list[AttachedValue]] | None = None
                       ) -> dict[str, int]:
        """MENTIONS edges from one document's blocks, in one transaction. MERGE on
        (block, entity, rule_version), properties on create only; MENTIONS from these
        blocks made by an older rule version are closed (valid_to = run_at).

        Values (M4 step 3) attached to a mention are stored on its edge as parallel
        lists (value, unit, family, base_value, base_unit, value_text, attribute);
        a mention without values has none of these properties. Values in a block
        with no non-hub entity go on the Block node as unattached_* lists, set on
        every run with the rule version that wrote them."""
        unattached = unattached or {}
        edges = []
        for m in mentions:
            edge = Edge(type=EdgeType.MENTIONS, source_id=m.block_uid, target_id=m.entity_id,
                        valid_from=doc.version.valid_from,
                        provenance=Provenance(method=Method.REGEX, evidence_block=m.block_uid,
                                              evidence_span=m.surface, confidence=confidence))
            edges.append({"source": edge.source_id, "target": edge.target_id, "props": {
                "method": edge.provenance.method.value,
                "evidence_block": edge.provenance.evidence_block,
                "evidence_span": edge.provenance.evidence_span,
                "confidence": edge.provenance.confidence, "valid_from": edge.valid_from,
                **value_lists(m.values)}})
        blocks = [{"uid": pb.block.block_uid, "props": {
                      f"unattached_{k}": v
                      for k, v in value_lists(unattached.get(pb.block.block_uid, ())).items()}}
                  for pb in doc.blocks if pb.block.role.value == "body"]
        p = {"edges": edges, "rule_version": rule_version, "run_at": run_at,
             "uids": [pb.block.block_uid for pb in doc.blocks], "blocks": blocks}
        with self._driver.session(database=self._database) as session:
            closed = session.execute_write(_write_mentions_tx, p)
        return {"written": len(edges), "closed": closed,
                "values": sum(len(m.values) for m in mentions),
                "unattached": sum(len(v) for v in unattached.values())}

    def entity_stats(self) -> list[dict[str, object]]:
        return [dict(r) for r in self._run(
            """
            MATCH (e:Entity)
            OPTIONAL MATCH (b:Block)-[m:MENTIONS]->(e) WHERE m.valid_to IS NULL
            WITH e, count(m) AS mentions
            RETURN e.language AS language, e.entity_type AS type, e.hub AS hub,
                   count(e) AS entities, sum(mentions) AS mentions
            ORDER BY language, type, hub
            """
        ).records]

    def delete_entities(self, entity_id_prefix: str) -> int:
        """Delete Entity nodes whose id starts with the prefix, their aliases and
        edges (used by tests to clean up)."""
        rec = self._run(
            """
            MATCH (e:Entity) WHERE e.entity_id STARTS WITH $p
            OPTIONAL MATCH (a:Alias)-[:ALIAS_OF]->(e)
            DETACH DELETE a, e RETURN count(DISTINCT e) AS n
            """, p=entity_id_prefix)
        return rec.records[0]["n"]

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


def _write_depends_tx(tx: ManagedTransaction, p: dict[str, object]) -> dict[str, int]:
    tx.run(
        """
        UNWIND $rows AS x
        MATCH (a:Block {block_uid: x.a}), (b:Block {block_uid: x.b})
        MERGE (a)-[r:DEPENDS {rule_version: $rv}]->(b)
          ON CREATE SET r += x.props
        """, p).consume()
    closed = tx.run(
        """
        MATCH (a:Block)-[r:DEPENDS]-() WHERE a.block_uid IN $uids AND r.valid_to IS NULL
          AND r.rule_version <> $rv
        WITH DISTINCT r
        SET r.valid_to = $t, r.closed_reason = 'replaced by rule_version ' + $rv
        RETURN count(r) AS n
        """, p).single()["n"]
    return {"written": len(p["rows"]), "closed": closed}


def _write_merges_tx(tx: ManagedTransaction, p: dict[str, object]) -> dict[str, int]:
    undone = tx.run(
        """
        MATCH (e:Entity) WHERE e.merge_rule_version = $rv AND NOT e.entity_id IN $merged
        OPTIONAL MATCH (:Alias)-[r:ALIAS_OF {rule_version: $rv}]->(:Entity)
        WHERE r.merged_entity = e.entity_id AND r.valid_to IS NULL
        SET r.valid_to = $t, r.closed_reason = 'merge undone by a later run'
        REMOVE e.merged_into, e.merge_rule_version
        RETURN count(DISTINCT e) AS n
        """, p).single()["n"]
    tx.run(
        """
        UNWIND $rows AS x
        MATCH (m:Entity {entity_id: x.merged}), (c:Entity {entity_id: x.canonical})
        SET m.merged_into = x.canonical, m.merge_rule_version = $rv
        WITH m, c, x
        MATCH (a:Alias)-[base:ALIAS_OF]->(m) WHERE base.valid_to IS NULL
        MERGE (a)-[r:ALIAS_OF {rule_version: $rv}]->(c)
          ON CREATE SET r.method = 'llm', r.model = $model, r.prompt_version = $pv,
                        r.confidence = $conf, r.valid_from = $t, r.evidence_span = x.reason,
                        r.merged_entity = x.merged
        """, p).consume()
    return {"merged": len(p["rows"]), "undone": undone}


def _write_diff_tx(tx: ManagedTransaction, p: dict[str, object]) -> None:
    tx.run(
        """
        UNWIND $rows AS x
        MATCH (:Section)-[r:CONTAINS {version_id: x.vid}]->(:Block {block_uid: x.uid})
        SET r.diff_status = x.status, r.previous_block_uid = x.prev,
            r.diff_similarity = x.sim
        """,
        p,
    ).consume()
    tx.run(
        """
        UNWIND $versions AS vid
        MATCH (v:Version {version_id: vid})
        SET v.removed_block_uids = []
        """,
        p,
    ).consume()
    tx.run(
        """
        UNWIND $removed AS x
        MATCH (v:Version {version_id: x.vid})
        SET v.removed_block_uids = x.uids
        """,
        p,
    ).consume()


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


def alias_id(language: str, surface: str) -> str:
    """One Alias node per name as matched (Thai: compact form; English: lower case)."""
    return f"{language}:{slug(EntityRegistry.key(language, surface))}"


def alias_method(sources: set[str]) -> Method:
    kinds = {s.split(":")[0] for s in sources}
    if "definition" in kinds:
        return Method.REGEX
    if kinds & {"heading", "title"}:
        return Method.PARSER
    return Method.HUMAN  # only the hand-kept file


def _write_entity_registry_tx(tx: ManagedTransaction, p: dict[str, object]) -> int:
    tx.run(
        """
        UNWIND $entities AS e
        MERGE (n:Entity {entity_id: e.entity_id})
        SET n += e.props, n.updated_at = $run_at
        """,
        p,
    ).consume()
    tx.run(
        """
        UNWIND $aliases AS a
        MERGE (al:Alias {alias_id: a.alias_id})
          ON CREATE SET al += a.props
        WITH al, a
        MATCH (e:Entity {entity_id: a.entity_id})
        MERGE (al)-[r:ALIAS_OF {rule_version: $rule_version}]->(e)
          ON CREATE SET r += a.edge
        """,
        p,
    ).consume()
    rec = tx.run(
        """
        UNWIND $aliases AS a
        MATCH (:Alias {alias_id: a.alias_id})-[r:ALIAS_OF]->()
        WHERE r.valid_to IS NULL AND r.rule_version <> $rule_version
        SET r.valid_to = $run_at, r.closed_reason = 'replaced by rule_version ' + $rule_version
        RETURN count(r) AS n
        """,
        p,
    ).single()
    return rec["n"] if rec else 0


VALUE_FIELDS = ("value", "unit", "family", "base_value", "base_unit", "value_text",
                "attribute")


def value_lists(values) -> dict[str, list]:
    """Parallel lists for Neo4j (no maps as properties); {} when there are none."""
    if not values:
        return {}
    return {"value": [a.value.value for a in values], "unit": [a.value.unit for a in values],
            "family": [a.value.family for a in values],
            "base_value": [a.value.base_value for a in values],
            "base_unit": [a.value.base_unit for a in values],
            "value_text": [a.value.value_text for a in values],
            "attribute": [a.attribute for a in values]}


def _write_mentions_tx(tx: ManagedTransaction, p: dict[str, object]) -> int:
    # unattached values on the blocks: cleared, then set for this rule version
    tx.run(
        """
        UNWIND $blocks AS x
        MATCH (b:Block {block_uid: x.uid})
        SET b.unattached_value = null, b.unattached_unit = null, b.unattached_family = null,
            b.unattached_base_value = null, b.unattached_base_unit = null,
            b.unattached_value_text = null, b.unattached_attribute = null
        SET b += x.props, b.values_rule_version = $rule_version
        """,
        p,
    ).consume()
    tx.run(
        """
        UNWIND $edges AS m
        MATCH (b:Block {block_uid: m.source}), (e:Entity {entity_id: m.target})
        MERGE (b)-[r:MENTIONS {rule_version: $rule_version}]->(e)
          ON CREATE SET r += m.props
        """,
        p,
    ).consume()
    rec = tx.run(
        """
        MATCH (b:Block)-[r:MENTIONS]->()
        WHERE b.block_uid IN $uids AND r.valid_to IS NULL AND r.rule_version <> $rule_version
        SET r.valid_to = $run_at, r.closed_reason = 'replaced by rule_version ' + $rule_version
        RETURN count(r) AS n
        """,
        p,
    ).single()
    return rec["n"] if rec else 0


def _write_references_tx(tx: ManagedTransaction, p: dict[str, object]) -> int:
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
        MERGE (b)-[r:REFERENCES {cited_section: e.cited_section,
                                 rule_version: $rule_version}]->(d)
          ON CREATE SET r += e.props
        """,
        p,
    ).consume()
    # Edges written before rule versions existed count as "L1-v1".
    rec = tx.run(
        """
        MATCH (b:Block)-[r:REFERENCES]->()
        WHERE b.block_uid IN $uids AND r.valid_to IS NULL
          AND coalesce(r.rule_version, 'L1-v1') <> $rule_version
        SET r.valid_to = $run_at, r.closed_reason = 'replaced by rule_version ' + $rule_version
        RETURN count(r) AS n
        """,
        p,
    ).single()
    return rec["n"] if rec else 0
