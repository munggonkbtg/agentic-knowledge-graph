"""Layer 3 entity merge, with a fake confirmer (no model)."""

from types import SimpleNamespace

import pytest

from kg.layer3_merge import MergeEntity, candidate_pairs, merge_entities


def E(eid, name, typ="Concept", lang="en", mentions=1, hub=False, sources=()):
    return MergeEntity(eid, name, typ, lang, mentions, hub, tuple(sources))


def test_containment_pairs_same_language_and_type_only():
    ents = [E("a", "Short Term Disability"), E("b", "short-term disability claim"),
            E("c", "Short Term Disability", typ="Artifact"), E("d", "ค่าชดเชย", lang="th"),
            E("e", "ค่าชดเชยพิเศษ", lang="th"), E("h", "Disability", hub=True)]
    pairs = {(p.a, p.b) for p in candidate_pairs(ents, None, 0.85, 3, 4)}
    assert ("d", "e") in pairs           # Thai containment
    assert ("a", "c") not in pairs       # types differ
    assert all("h" not in p for p in pairs)  # hubs left out
    # hyphen and space alike, as in the layer 2 matcher
    assert ("a", "b") in pairs


def test_similarity_pairs_cross_language_with_top_k():
    np = pytest.importorskip("numpy")  # embed dependency group
    ents = [E("en", "Severance pay"), E("th", "ค่าชดเชย", lang="th"), E("x", "Pet insurance")]
    vec = {"Severance pay": [1, 0], "ค่าชดเชย": [0.95, 0.31], "Pet insurance": [0, 1]}

    def embed(names):
        v = np.array([vec[n] for n in names], dtype=float)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    pairs = candidate_pairs(ents, embed, 0.9, 3, 4)
    assert [(p.a, p.b) for p in pairs] == [("en", "th")]
    assert pairs[0].reason.startswith("similarity")


def _confirm(answers):
    def confirm(a, b):
        v = answers.get(tuple(sorted((a.entity_id, b.entity_id))), "different")
        return SimpleNamespace(cached=False, data=SimpleNamespace(verdict=v, reason="r"))
    return confirm


def test_only_same_merges_transitively_into_the_most_mentioned_entity():
    ents = [E("a", "A", mentions=3), E("b", "B", mentions=10), E("c", "C", mentions=1),
            E("d", "D", mentions=5)]
    pairs = candidate_pairs(ents, None, 0.9, 3, 4)  # none by containment
    from kg.layer3_merge import Pair
    pairs = [Pair("a", "b", "t"), Pair("b", "c", "t"), Pair("c", "d", "t")]
    res = merge_entities(ents, pairs, _confirm({("a", "b"): "same", ("b", "c"): "same",
                                                ("c", "d"): "unsure"}))
    assert res.canonical == {"a": "b", "c": "b"}  # d stays apart (unsure)
    assert res.verdicts[("c", "d")] == "unsure" and res.calls == 3


def test_failed_llm_call_never_merges():
    ents = [E("a", "A"), E("b", "B")]
    from kg.layer3_merge import Pair

    def confirm(a, b):
        return SimpleNamespace(cached=False, data=None)

    res = merge_entities(ents, [Pair("a", "b", "t")], confirm)
    assert res.canonical == {} and res.verdicts[("a", "b")] == "failed"


def test_containment_merge_only_when_the_extra_words_are_generic():
    from kg.layer3_merge import Pair, containment_allows_merge

    assert containment_allows_merge(E("a", "Short Term Disability"),
                                    E("b", "short-term disability claim"))
    assert containment_allows_merge(E("a", "ลาเพื่อกิจธุระอันจำเป็น", lang="th"),
                                    E("b", "สิทธิลาเพื่อกิจธุระอันจำเป็น", lang="th"))
    assert not containment_allows_merge(E("a", "วันทำงาน", lang="th"),
                                        E("b", "ค่าจ้างในวันทำงาน", lang="th"))
    assert not containment_allows_merge(E("a", "Sick Time"), E("b", "Paid Sick Time"))
    ents = [E("a", "วันทำงาน", lang="th"), E("b", "ค่าจ้างในวันทำงาน", lang="th")]
    res = merge_entities(ents, [Pair("a", "b", "containment")], _confirm({("a", "b"): "same"}))
    assert res.canonical == {} and res.verdicts[("a", "b")].startswith("same, blocked")
