"""All Neo4j reads and writes go through this module (coding rule 4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import TracebackType

from neo4j import Driver, GraphDatabase

from kg.config import Neo4jCredentials
from kg.models import EdgeType

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

    def fulltext_analyzers(self) -> list[str]:
        records = self._run(
            "CALL db.index.fulltext.listAvailableAnalyzers() YIELD analyzer "
            "RETURN analyzer ORDER BY analyzer"
        ).records
        return [r["analyzer"] for r in records]
