"""M4 step 3: values (number + unit) on MENTIONS, measured before writing them.

Rules: src/kg/values.py (normalization table agreed 2026-11-25). Each value is
attached to the nearest non-hub entity in its block; the attribute is the
PROVISIONAL rule (entity, unit family). Values in blocks with no entity are kept
with the block (entity None).

Reported:
1. Values on the initial corpus: per language, blocks with values, blocks that
   have values but no entity, and the most frequent values (noise).
2. Per change item: the changed values (comparable values in the old text that
   are gone from the new text) and how many candidate blocks contain one.
3. Review pairs (merged labels, eval/m5_labels.py; historical apart): linked by a
   shared non-hub entity (E), by a changed value (V), by E or V, and the brief's
   count: same entity and attribute in the dependent block with the old value,
   while the new text has a different value for that entity and attribute.
4. Ranking among all candidate blocks of the change, same number of candidates:
   entity overlap alone vs entity + changed value vs changed value alone;
   expected recall@k with ties broken at random (no other signal mixed in).

Label source: --labels ai | human. Hub cut-off: config layer2.hub_block_share.
Registry: automatic (manual entries with source documents only; test_pairs out).
Writes eval/results/m4_values_<source>.md.

Run:  uv run --group embed python eval/m4_values.py
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from statistics import median

from compare_embeddings import change_contexts
from label_sources import DESCRIPTION
from m4_registry_coverage import T0, analyse, negatives_by_event
from m5_labels import by_change, positives
from make_change_test_set import ROOT

from kg.config import load_config
from kg.layer0_structure import parse_corpus
from kg.layer2_entities import load_manual
from kg.values import attach_values, extract_values

KS = (5, 10, 20)


def view(text: str, lang: str, matcher, hubs: set[str]):
    spans = matcher.find_spans(text, lang)
    ents = {s[0] for s in spans} - hubs
    att = attach_values(extract_values(text, lang), spans, hubs)
    return ents, att


def expected_hit(score: float, others: list[float], k: int) -> float:
    """Chance the target is in the top k when ties are ordered at random."""
    better = sum(o > score for o in others)
    equal = sum(o == score for o in others) + 1
    return min(max((k - better) / equal, 0.0), 1.0)


def fmt(a: float, n: int) -> str:
    return f"{a / n:.2f}" if n else "-"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="ai", choices=["ai", "human"])
    source = ap.parse_args().labels
    cfg = load_config(ROOT / "config.yaml")
    cut = cfg.layer2.hub_block_share
    documents = load_manual(ROOT / cfg.layer2.manual_file, sources=["documents"])

    # ---------------------------------------------- 1. the initial corpus
    docs = parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, T0)
    reg, matcher, share = analyse(docs, documents)
    hubs0 = {e for e, s in share.items() if cut is not None and s > cut}
    stats = Counter()
    freq: dict[str, Counter] = defaultdict(Counter)
    for d in docs:
        lang = d.document.language.value
        for pb in d.blocks:
            if pb.block.role.value != "body":
                continue
            ents, att = view(pb.block.text, lang, matcher, hubs0)
            stats[(lang, "blocks")] += 1
            stats[(lang, "values")] += len(att)
            stats[(lang, "with_values")] += bool(att)
            stats[(lang, "values_no_entity_block")] += bool(att) and not ents
            stats[(lang, "values_unattached")] += sum(a.entity_id is None for a in att)
            for c in {a.value.comparable() for a in att}:
                freq[lang][c] += 1
    out = ["# M4 step 3: values on MENTIONS (rules, no LLM)", "",
           "Normalization: `src/kg/values.py` (table agreed 2026-11-25). Attribute = "
           "(nearest non-hub entity, unit family), a provisional rule. Registry: "
           f"automatic; hubs above {cut} excluded.", "",
           "## 1. Values in the initial corpus (body blocks)", "",
           "| language | blocks | values | blocks with a value | ... of which no entity "
           "| values with no entity in the block |", "|---|---|---|---|---|---|"]
    for lang in ("th", "en"):
        out.append(f"| {lang} | {stats[(lang, 'blocks')]} | {stats[(lang, 'values')]} "
                   f"| {stats[(lang, 'with_values')]} | {stats[(lang, 'values_no_entity_block')]} "
                   f"| {stats[(lang, 'values_unattached')]} |")
    out += ["", "Most frequent values (blocks that contain the value; the noise a plain "
            "\"same value\" signal would pull in):", "",
            "| language | value (family, comparable) | blocks |", "|---|---|---|"]
    for lang in ("th", "en"):
        for (fam, v), n in freq[lang].most_common(10):
            out.append(f"| {lang} | {fam} {v:g} | {n} |")

    # ---------------------------------------------- 2-4. change items and pairs
    merged = by_change(positives(source), include_historical=True)
    negatives = negatives_by_event(source)
    cache: dict[int, tuple] = {}
    per_change, pairs, negs, ranks = [], [], [], []
    for ctx in change_contexts(cfg):
        sid = id(ctx["store"])
        if sid not in cache:
            r, m, sh = analyse(list(ctx["store"].values()), documents)
            cache[sid] = (m, {e for e, s in sh.items() if cut is not None and s > cut})
        m, hubs = cache[sid]
        ch, lang = ctx["change"], ctx["lang"]
        old_e, old_v = view(ch["old_text"], lang, m, hubs)
        new_e, new_v = view(ch["new_text"], lang, m, hubs)
        a_ents = old_e | new_e
        new_comp = Counter(a.value.comparable() for a in new_v)
        changed = {a.value.comparable() for a in old_v} - set(new_comp)
        # (attribute, old comparable) whose attribute has a different value in the new text
        new_by_attr = defaultdict(set)
        for a in new_v:
            new_by_attr[a.attribute].add(a.value.comparable())
        changed_attr = {(a.attribute, a.value.comparable()) for a in old_v
                        if a.entity_id and new_by_attr.get(a.attribute)
                        and a.value.comparable() not in new_by_attr[a.attribute]}
        cand_view = {u: view(t, lang, m, hubs) for u, t in ctx["cands"].items()}
        noisy = sum(1 for _, att in cand_view.values()
                    if {x.value.comparable() for x in att} & changed)
        per_change.append((ctx["change_id"], lang, len(changed), noisy, len(ctx["cands"])))

        def signals(uid):
            ents, att = cand_view[uid]
            comps = {x.value.comparable() for x in att}
            return {"E": bool(ents & a_ents), "V": bool(comps & changed),
                    "EV": bool({(x.attribute, x.value.comparable()) for x in att} & changed_attr),
                    "e": len(ents & a_ents), "v": len(comps & changed)}

        for p in merged.get(ctx["change_id"], []):
            if p.block_uid in cand_view:
                s = signals(p.block_uid)
                group = "historical" if p.historical else p.kind
                pairs.append((group, lang, s))
                scores = {u: signals(u) for u in cand_view}
                for name, fn in (("entity", lambda x: x["e"]), ("value", lambda x: x["v"]),
                                 ("entity + value", lambda x: x["e"] + x["v"])):
                    tgt = fn(scores[p.block_uid])
                    others = [fn(x) for u, x in scores.items() if u != p.block_uid]
                    ranks.append((group, name, {k: expected_hit(tgt, others, k) for k in KS}))
        for uid in negatives.get(ch["event"], []):
            if uid in cand_view:
                negs.append(signals(uid))

    with_changed = [c for c in per_change if c[2]]
    out += ["", "## 2. Changed values per change item", "",
            f"{len(with_changed)} of {len(per_change)} change items change at least one "
            "value (a comparable value in the old text that is not in the new text).",
            "Candidate blocks that contain one of the changed values (noise of the plain "
            "value signal): median "
            f"{median(c[3] for c in with_changed) if with_changed else 0:g}, max "
            f"{max((c[3] for c in with_changed), default=0)} (of "
            f"{median(c[4] for c in with_changed) if with_changed else 0:g} candidates).", "",
            "| change | language | changed values | candidate blocks with one |",
            "|---|---|---|---|"]
    out += [f"| {c[0]} | {c[1]} | {c[2]} | {c[3]} |" for c in with_changed]

    out += ["", "## 3. Review pairs", "",
            f"**Label source: {source}** ({DESCRIPTION[source]}). E = shared non-hub "
            "entity; V = the review block contains a changed value; EV = same entity and "
            "attribute with the old value, while the new text gives that entity and "
            "attribute a different value (the brief's step 3 count).", "",
            "| group | pairs | E | V | E or V | EV |", "|---|---|---|---|---|---|"]
    order = ["states", "depends", "cites", "historical"]
    for g in order:
        ps = [s for gg, _, s in pairs if gg == g]
        out.append(f"| {g} | {len(ps)} | {sum(s['E'] for s in ps)} | {sum(s['V'] for s in ps)} "
                   f"| {sum(s['E'] or s['V'] for s in ps)} | {sum(s['EV'] for s in ps)} |")
    for lang in ("th", "en"):
        ps = [s for g, l, s in pairs if l == lang and g in ("states", "depends")]
        out.append(f"| states + depends, {lang} | {len(ps)} | {sum(s['E'] for s in ps)} "
                   f"| {sum(s['V'] for s in ps)} | {sum(s['E'] or s['V'] for s in ps)} "
                   f"| {sum(s['EV'] for s in ps)} |")
    n = len(negs)
    out.append(f"| negatives | {n} | {sum(s['E'] for s in negs)} ({fmt(sum(s['E'] for s in negs), n)}) "
               f"| {sum(s['V'] for s in negs)} ({fmt(sum(s['V'] for s in negs), n)}) "
               f"| {sum(s['E'] or s['V'] for s in negs)} ({fmt(sum(s['E'] or s['V'] for s in negs), n)}) "
               f"| {sum(s['EV'] for s in negs)} |")

    out += ["", "## 4. Ranking all candidate blocks, same number of candidates", "",
            "Expected recall@k when each change's candidate blocks are ranked by the "
            "score alone (ties in random order). entity = number of shared non-hub "
            "entities; value = number of changed values in the block.", "",
            "| group | pairs | score | " + " | ".join(f"@{k}" for k in KS) + " |",
            "|---|---|---|" + "---|" * len(KS)]
    for g in ["states + depends", *order]:
        members = ("states", "depends") if g == "states + depends" else (g,)
        for name in ("entity", "entity + value", "value"):
            rs = [r for gg, nn, r in ranks if gg in members and nn == name]
            if rs:
                out.append(f"| {g} | {len(rs)} | {name} | "
                           + " | ".join(f"{sum(r[k] for r in rs) / len(rs):.2f}" for k in KS)
                           + " |")
    out += ["", "Not checked: whether each extracted value and its attachment is right "
            "(no labels for values yet); the attribute rule is provisional."]
    text = "\n".join(out)
    (ROOT / "eval" / "results" / f"m4_values_{source}.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
