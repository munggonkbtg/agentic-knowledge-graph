"""Upload (layer 0) against a real Neo4j. Skipped when Neo4j is not configured.

Each test uses synthetic documents whose doc_key starts with a unique
``kgtest-`` prefix, and deletes them afterwards, so the pilot data in the
database is never touched.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kg.config import MissingEnvError, load_config, load_neo4j_credentials
from kg.diff import MatchStatus, diff_event
from kg.layer0_structure import Normalizer, parse_file
from kg.store import Store

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config.yaml")
NORM = Normalizer(CFG.layer0)
T1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
T2 = datetime(2024, 6, 1, tzinfo=timezone.utc)
pytestmark = pytest.mark.neo4j

P1 = "Employees get twenty days of paid leave every year, booked in the shared calendar."
P2 = "Managers approve leave requests within two working days of receiving them."
P3 = "Unused leave cannot be carried over into the next calendar year."
NEW = "A brand new paragraph that was inserted at the top of the section."


@pytest.fixture(scope="module")
def store():
    try:
        creds = load_neo4j_credentials(env_file=ROOT / ".env")
    except MissingEnvError:
        pytest.skip("NEO4J_* environment variables not set")
    s = Store(creds, database=CFG.neo4j.database)
    try:
        s.ping()
    except Exception as e:  # noqa: BLE001 - any connection problem means skip
        s.close()
        pytest.skip(f"Neo4j not reachable: {type(e).__name__}")
    yield s
    s.close()


@pytest.fixture
def prefix(store):
    p = f"kgtest-{uuid.uuid4().hex[:8]}-"
    yield p
    store.delete_documents(p)


def _file(tmp_path, name, doc_key, title, body):
    f = tmp_path / name
    f.write_text(f"---\ndoc_key: {doc_key}\ntitle: {title}\nlanguage: en\n---\n# {title}\n\n{body}",
                 encoding="utf-8")
    return f


def _versions(store, doc_key):
    return store._run(
        """
        MATCH (d:Document {doc_key: $k})-[:HAS_VERSION]->(v:Version)
        OPTIONAL MATCH (v)-[s:SUPERSEDES]->(old:Version)
        RETURN d.title AS title, v.version_id AS vid, v.valid_to AS valid_to,
               old.version_id AS supersedes
        ORDER BY v.valid_from
        """,
        k=doc_key,
    ).records


def _upload(store, files, valid_from):
    docs = [parse_file(f, CFG.layer0, valid_from) for f in files]
    olds = {d.document.doc_key: o for d in docs
            if (o := store.load_current_version(d.document.doc_key)) is not None}
    results = diff_event(olds, docs, CFG.diff, NORM)
    return results, [store.write_upload(d) for d in results]


def test_load_current_version_round_trips(store, prefix, tmp_path):
    key = prefix + "doc"
    f = _file(tmp_path, "v1.md", key, "Leave", f"## Rules\n\n{P1}\n\n{P2}\n\n## More\n\n{P3}\n")
    parsed = parse_file(f, CFG.layer0, T1)
    store.write_layer0(parsed)
    loaded = store.load_current_version(key)
    assert loaded.version.version_id == parsed.version.version_id
    assert [ps.section.section_id for ps in loaded.sections] == \
           [ps.section.section_id for ps in parsed.sections]
    assert [ps.parent_id for ps in loaded.sections] == [ps.parent_id for ps in parsed.sections]
    assert [(pb.block, pb.section_id) for pb in loaded.blocks] == \
           [(pb.block, pb.section_id) for pb in parsed.blocks]


def test_upload_reuses_nodes_of_unchanged_blocks_even_when_they_shift(store, prefix, tmp_path):
    key = prefix + "doc"
    v1 = parse_file(_file(tmp_path, "v1.md", key, "Leave", f"## Rules\n\n{P1}\n\n{P2}\n"),
                    CFG.layer0, T1)
    store.write_layer0(v1)
    old_uids = [pb.block.block_uid for pb in v1.blocks]

    # v2: a paragraph inserted above, so both old paragraphs shift position.
    f2 = _file(tmp_path, "v2.md", key, "Leave policy", f"## Rules\n\n{NEW}\n\n{P1}\n\n{P2}\n")
    (d,), (written,) = _upload(store, [f2], T2)
    assert {m.status for m in d.matches} == {MatchStatus.UNCHANGED, MatchStatus.ADDED}
    assert written == {"blocks": 3, "reused_nodes": 2, "new_nodes": 1}

    new_version = store.load_current_version(key)
    assert new_version.version.version_id == d.new.version.version_id
    by_text = {pb.block.text: pb.block for pb in new_version.blocks}
    # same nodes as before, though block_id (position) moved from b0/b1 to b1/b2
    assert [by_text[P1].block_uid, by_text[P2].block_uid] == old_uids
    assert by_text[P1].block_id.endswith("::b1") and by_text[P2].block_id.endswith("::b2")
    # line ranges come from this version, not the first one
    assert by_text[P1].lines.start > v1.blocks[0].block.lines.start

    rows = _versions(store, key)
    assert [r["vid"] for r in rows] == [v1.version.version_id, d.new.version.version_id]
    assert rows[0]["valid_to"] is not None and rows[1]["valid_to"] is None
    assert rows[1]["supersedes"] == v1.version.version_id
    assert rows[0]["title"] == "Leave policy"  # title follows the newest version


def test_edited_block_gets_a_new_node_and_old_version_keeps_the_old_one(store, prefix, tmp_path):
    key = prefix + "doc"
    v1 = parse_file(_file(tmp_path, "v1.md", key, "Leave", f"## Rules\n\n{P1}\n"), CFG.layer0, T1)
    store.write_layer0(v1)
    edited = P1.replace("twenty", "twenty-five")
    (d,), (written,) = _upload(
        store, [_file(tmp_path, "v2.md", key, "Leave", f"## Rules\n\n{edited}\n")], T2)
    assert [m.status for m in d.matches] == [MatchStatus.EDITED]
    assert written["reused_nodes"] == 0
    old_text = store._run(
        """
        MATCH (:Version {version_id: $vid})-[:CONTAINS*1..]->(:Section)-[:CONTAINS]->(b:Block)
        RETURN b.text AS t
        """,
        vid=v1.version.version_id,
    ).records
    assert [r["t"] for r in old_text] == [P1]


def test_new_document_has_no_supersedes(store, prefix, tmp_path):
    key = prefix + "fresh"
    (d,), (written,) = _upload(store, [_file(tmp_path, "n.md", key, "Fresh", f"{P3}\n")], T2)
    assert d.old is None and written["new_nodes"] == 1
    (row,) = _versions(store, key)
    assert row["supersedes"] is None and row["valid_to"] is None


def test_writing_the_same_upload_twice_changes_nothing(store, prefix, tmp_path):
    key = prefix + "doc"
    store.write_layer0(parse_file(_file(tmp_path, "v1.md", key, "Leave", f"{P1}\n\n{P2}\n"),
                                  CFG.layer0, T1))
    f2 = _file(tmp_path, "v2.md", key, "Leave", f"{NEW}\n\n{P1}\n\n{P2}\n")
    (d,), _ = _upload(store, [f2], T2)

    def snap():
        return store._run(
            """
            MATCH (d:Document {doc_key: $k})-[:HAS_VERSION]->(v)-[:CONTAINS*1..]->(x)
            OPTIONAL MATCH (x)-[r]->()
            RETURN count(DISTINCT x) AS nodes, count(r) AS rels,
                   collect(DISTINCT v.valid_to) AS valid_to
            """,
            k=key,
        ).records[0].data()

    before = snap()
    store.write_upload(d)  # same diff written again
    assert snap() == before


def test_identification_by_content_is_recorded_on_has_version(store, prefix, tmp_path):
    """A file without doc_key is matched to its document by text, and the decision
    (method and scores) is stored on HAS_VERSION."""
    from kg.identify import identify

    key = prefix + "doc"
    store.write_layer0(parse_file(_file(tmp_path, "v1.md", key, "Leave", f"## Rules\n\n{P1}\n\n{P2}\n\n{P3}\n"),
                                  CFG.layer0, T1))
    f2 = tmp_path / "leave_policy_update.md"  # no front matter at all
    f2.write_text(f"# Leave\n\n## Rules\n\n{NEW}\n\n{P1}\n\n{P2}\n\n{P3}\n", encoding="utf-8")
    cands = [c for c in store.identification_candidates(NORM) if c.doc_key.startswith(prefix)]
    ident, doc = identify(f2, cands, CFG, T2)
    assert (ident.method, ident.doc_key) == ("content", key)
    old = store.load_current_version(key)
    (d,) = diff_event({key: old}, [doc], CFG.diff, NORM)
    store.write_upload(d, ident.provenance())
    rec = store._run(
        """
        MATCH (:Document {doc_key: $k})-[r:HAS_VERSION]->(v:Version {version_id: $vid})
        RETURN r.method AS method, r.id_text_similarity AS sim
        """, k=key, vid=doc.version.version_id).records[0]
    assert rec["method"] == "content" and rec["sim"] >= CFG.identify.accept_text_similarity


def test_layer1_references_are_written_once_with_stubs(store, prefix, tmp_path):
    from kg.layer1_references import Registry, RegistryEntry, ReferenceExtractor

    act_key, reg_key = prefix + "act", prefix + "reg"
    act = _file(tmp_path, "act.md", act_key, "พระราชบัญญัติทดสอบ พ.ศ. 2541",
                "## หมวด 1\n\nนายจ้างต้องปฏิบัติตามมาตรา ๑๑๘\n")
    reg = _file(tmp_path, "reg.md", reg_key, "ระเบียบทดสอบ ออกตามความในพระราชบัญญัติทดสอบ พ.ศ. 2541",
                "## ข้อ 1\n\nตามมาตรา ๖ แห่งพระราชบัญญัติทดสอบ พ.ศ. ๒๕๔๑ และมาตรา ๗๑ แห่ง"
                "พระราชบัญญัติอื่นที่ไม่มีในคลัง พ.ศ. ๒๕๕๔\n")
    docs = [parse_file(f, CFG.layer0, T1) for f in (act, reg)]
    for d in docs:
        store.write_layer0(d)
    registry = Registry([RegistryEntry(d.document.doc_key, d.document.title, "th") for d in docs])
    extractor = ReferenceExtractor(registry, CFG.layer1)

    def edges():
        return sorted(tuple(r.values()) for r in store._run(
            """
            MATCH (b:Block)-[r:REFERENCES]->(d:Document) WHERE b.doc_key STARTS WITH $p
            RETURN b.doc_key AS f, d.doc_key AS t, r.cited_section AS c, r.resolution AS res,
                   r.self_reference AS self, coalesce(d.in_store, true) AS in_store
            """, p=prefix).records)

    stubs = sorted({k for d in docs for k in extractor.extract(d).stubs})
    try:
        for run in range(2):  # the second run must change nothing
            for d in docs:
                store.write_references(d, extractor.extract(d), "test-v1", T2)
            if run == 0:
                first = edges()
        assert edges() == first
        assert (act_key, act_key, "มาตรา 118", "self_document", True, True) in first
        assert (reg_key, act_key, "มาตรา 6", "explicit", False, True) in first
        ext = [e for e in first if e[5] is False]
        assert len(ext) == 1 and ext[0][2] == "มาตรา 71"
    finally:  # the stub is not under the prefix, so delete it here
        store._run("MATCH (d:Document) WHERE d.doc_key IN $k AND d.in_store = false "
                   "DETACH DELETE d", k=stubs)


def test_new_rule_version_closes_old_edges_instead_of_deleting(store, prefix, tmp_path):
    from kg.layer1_references import Registry, RegistryEntry, ReferenceExtractor

    key = prefix + "act"
    doc = parse_file(_file(tmp_path, "act.md", key, "พระราชบัญญัติทดสอบ พ.ศ. 2541",
                           "## หมวด 1\n\nตามมาตรา ๑๑๘ และมาตรา ๑๑๙\n"), CFG.layer0, T1)
    store.write_layer0(doc)
    out = ReferenceExtractor(Registry([RegistryEntry(key, doc.document.title, "th")]),
                             CFG.layer1).extract(doc)
    assert store.write_references(doc, out, "test-A", T1) == {"written": 2, "closed": 0}
    res = store.write_references(doc, out, "test-B", T2)
    assert res == {"written": 2, "closed": 2}
    assert store.write_references(doc, out, "test-B", T2)["closed"] == 0  # rerun: no change

    rows = store._run(
        """
        MATCH (b:Block)-[r:REFERENCES]->() WHERE b.doc_key = $k
        RETURN r.rule_version AS v, r.valid_to IS NULL AS open, r.closed_reason AS why
        ORDER BY v
        """, k=key).records
    assert [(r["v"], r["open"]) for r in rows] == [("test-A", False)] * 2 + [("test-B", True)] * 2
    assert all(r["why"] == "replaced by rule_version test-B" for r in rows if not r["open"])


def test_layer2_entities_and_mentions_written_once_then_closed_by_new_rules(store, prefix,
                                                                           tmp_path):
    from kg.layer2_entities import EntityEntry, Mention

    key = prefix + "policy"
    doc = parse_file(_file(tmp_path, "p.md", key, "Policy", f"## Leave\n\n{P1}\n\n{P2}\n"),
                     CFG.layer0, T1)
    store.write_layer0(doc)
    uids = [pb.block.block_uid for pb in doc.blocks]
    leave = EntityEntry(prefix + "concept", "Paid Leave", "Concept", "en",
                        {prefix + "paid leave", prefix + "leave"}, {"heading:x"})
    boss = EntityEntry(prefix + "role", "Manager", "Role", "en", {prefix + "manager"},
                       {"manual"}, hub=True)
    mentions = [Mention(uids[0], leave.entity_id, "paid leave"),
                Mention(uids[1], leave.entity_id, "leave"),
                Mention(uids[1], boss.entity_id, "Managers")]
    share = {leave.entity_id: 1.0, boss.entity_id: 0.5}
    try:
        res = store.write_entity_registry([leave, boss], share, "test-A", T2)
        assert res == {"entities": 2, "aliases": 3, "closed": 0}
        assert store.write_mentions(doc, mentions, "test-A", 0.8, T2) == {"written": 3, "closed": 0}
        # rerun with the same rules: nothing new, nothing closed
        assert store.write_entity_registry([leave, boss], share, "test-A", T2)["closed"] == 0
        assert store.write_mentions(doc, mentions, "test-A", 0.8, T2)["closed"] == 0
        rows = store._run(
            """
            MATCH (b:Block)-[m:MENTIONS]->(e:Entity) WHERE b.doc_key = $k
            OPTIONAL MATCH (a:Alias)-[al:ALIAS_OF]->(e)
            RETURN e.entity_id AS e, e.hub AS hub, e.block_share AS share, count(DISTINCT m) AS m,
                   count(DISTINCT a) AS aliases, collect(DISTINCT al.method) AS method,
                   collect(DISTINCT m.confidence) AS conf
            ORDER BY e
            """, k=key).records
        assert [(r["e"], r["hub"], r["share"], r["m"], r["aliases"], r["method"], r["conf"])
                for r in rows] == [
            (leave.entity_id, False, 1.0, 2, 2, ["parser"], [0.8]),
            (boss.entity_id, True, 0.5, 1, 1, ["human"], [0.8])]
        # new rule version: old edges are closed, not deleted
        assert store.write_mentions(doc, mentions, "test-B", 0.8, T2) == {"written": 3, "closed": 3}
        assert store.write_entity_registry([leave, boss], share, "test-B", T2)["closed"] == 3
        n = store._run("MATCH (b:Block)-[m:MENTIONS]->() WHERE b.doc_key = $k "
                       "RETURN count(m) AS all, sum(CASE WHEN m.valid_to IS NULL THEN 1 ELSE 0 END)"
                       " AS open", k=key).records[0]
        assert (n["all"], n["open"]) == (6, 3)
    finally:
        assert store.delete_entities(prefix) == 2
