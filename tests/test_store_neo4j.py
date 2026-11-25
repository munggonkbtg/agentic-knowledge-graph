"""Integration tests against a real local Neo4j. Skipped when not configured."""

from pathlib import Path

import pytest

from kg.config import MissingEnvError, load_config, load_neo4j_credentials
from kg.store import Store

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.neo4j


@pytest.fixture(scope="module")
def store():
    try:
        creds = load_neo4j_credentials(env_file=ROOT / ".env")
    except MissingEnvError:
        pytest.skip("NEO4J_* environment variables not set")
    s = Store(creds, database=load_config(ROOT / "config.yaml").neo4j.database)
    try:
        s.ping()
    except Exception as e:  # noqa: BLE001 - any connection problem means skip
        s.close()
        pytest.skip(f"Neo4j not reachable: {type(e).__name__}")
    yield s
    s.close()


def test_ping_creates_and_removes_test_node(store):
    result = store.ping()
    assert result.created_and_read
    assert result.removed


def test_ensure_schema_is_idempotent(store):
    store.ensure_schema()
    first = store.schema_names()
    store.ensure_schema()
    assert store.schema_names() == first
    assert {"document_doc_key", "block_block_uid", "rel_next_valid_to"} <= first


def test_layer0_build_twice_gives_same_graph(store):
    """M1 'done' check: a rerun of layer 0 on the initial corpus changes nothing."""
    from conftest import INITIAL, T0
    from kg.layer0_structure import parse_corpus

    if not INITIAL.exists():
        pytest.skip("data/initial_corpus not present")
    cfg = load_config(ROOT / "config.yaml").layer0
    for doc in parse_corpus(INITIAL, cfg, T0):
        store.write_layer0(doc)
    first = store.graph_snapshot()
    for doc in parse_corpus(INITIAL, cfg, T0):
        store.write_layer0(doc)
    assert store.graph_snapshot() == first
    assert first["block_uids"], "no blocks were written"
