"""Layer 4 DEPENDS with a fake judge (no model)."""

from types import SimpleNamespace

from kg.layer4_depends import DepBlock, candidate_pairs, find_depends, select_blocks


def B(uid, text, ents=(), refs=0, doc="d"):
    return DepBlock(uid, text, doc, f"{doc} > s", set(ents), refs)


BLOCKS = {
    "sick": B("sick", "Sick leave of three working days needs a medical certificate.",
              {"sick_leave"}),
    "faq": B("faq", "After a short illness you do not need to bring a certificate.",
             {"sick_leave"}),
    "pay": B("pay", "Salary is paid on the 25th.", {"salary"}, refs=1),
    "x": B("x", "Unrelated block.", set()),
}


def test_selection_by_centrality_or_given_blocks():
    # degree: sick and faq share an entity (1 each), pay has one reference (1), x none
    assert select_blocks(BLOCKS, 0.5) == ["faq", "pay"]
    assert select_blocks(BLOCKS, 1.0) == ["faq", "pay", "sick", "x"]
    assert select_blocks(BLOCKS, 0.2, only={"x", "gone"}) == ["x"]


def test_pairs_shared_entity_first_then_nearest_capped_and_once():
    nearest = {"sick": ["pay", "x"], "faq": ["sick"]}
    pairs = candidate_pairs(BLOCKS, ["sick", "faq"], lambda u: nearest.get(u, []), 5, 2)
    assert pairs == [("faq", "sick"), ("pay", "sick")]  # faq->sick already seen


def _judge(direction, dep_quote, src_quote):
    def judge(a, b):
        return SimpleNamespace(cached=False, data=SimpleNamespace(
            direction=direction, fact="certificate after three days",
            evidence_dependent=dep_quote, evidence_source=src_quote))
    return judge


def test_edge_kept_only_with_both_quotes_found():
    pairs = [("faq", "sick")]
    ok = find_depends(BLOCKS, pairs, _judge("a_on_b", "you do not need to bring a certificate",
                                            "three working days needs a medical certificate"))
    assert [(e.dependent, e.source) for e in ok.edges] == [("faq", "sick")]
    bad = find_depends(BLOCKS, pairs, _judge("a_on_b", "you never need a certificate",
                                             "three working days"))
    assert bad.edges == [] and bad.stats["evidence_not_found"] == 1
    none = find_depends(BLOCKS, pairs, _judge("none", "", ""))
    assert none.edges == [] and none.stats["none"] == 1
    rev = find_depends(BLOCKS, pairs, _judge("b_on_a", "three working days needs",
                                             "do not need to bring a certificate"))
    assert [(e.dependent, e.source) for e in rev.edges] == [("sick", "faq")]
