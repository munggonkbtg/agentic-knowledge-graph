"""M5 step 1: the main experiment, offline (no LLM check, nothing written to Neo4j).

For every change item of the M5 change test set (real events 1-3 and the
synthetic edits), rank the existing body blocks of the store at that time:

* baseline  hybrid search: character-trigram TF-IDF + multilingual-e5-large, RRF
* graph     blocks reached by a graph signal (layers 0-2), strongest first, then
            the rest in hybrid order (src/kg/impact.py graph_first)
* A         RRF of the hybrid ranking and one ranking per graph signal
            (cite_section, value, entity, cite_document; src/kg/impact.py)

All three are compared at the same number of candidates N (5, 10, 20): recall of
the (change, block) pairs labelled needs_review, per kind, language and set;
historical blocks (kg/historical.py) in their own row; also without the diff
artefacts C32 and C38, and for needs_revision pairs. The share of positives each
graph signal reaches shows where the graph helps.

Label source: --labels ai | human (merged sheets, eval/m5_labels.py).
Registry: automatic (manual entries with source documents only).
Writes eval/results/m5_impact_<source>.md.

Run:  uv run --group embed python eval/m5_impact_experiment.py
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from compare_embeddings import E5, change_contexts, rankings
from label_sources import DESCRIPTION
from m5_labels import by_change, positives
from make_change_test_set import ROOT

from kg.config import load_config
from kg.impact import SIGNALS, ChangeItem, GraphView, graph_first, graph_signals, impact_ranking
from kg.layer2_entities import load_manual

KS = (5, 10, 20)
METHODS = ("baseline", "graph", "A")
ARTEFACTS = {"C32", "C38"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="ai", choices=["ai", "human"])
    source = ap.parse_args().labels
    cfg = load_config(ROOT / "config.yaml")
    documents = load_manual(ROOT / cfg.layer2.manual_file, sources=["documents"])
    e5 = E5()
    merged = by_change(positives(source), include_historical=True)
    views: dict[int, GraphView] = {}
    hits: dict[tuple, Counter] = defaultdict(Counter)
    reach: dict[str, Counter] = defaultdict(Counter)
    n_changes = 0
    reached_sizes: list[tuple[str, int, int]] = []  # (change, blocks reached, positives among them)
    for ctx in change_contexts(cfg):
        pos = merged.get(ctx["change_id"])
        if not pos:
            continue
        n_changes += 1
        sid = id(ctx["store"])
        if sid not in views:
            views[sid] = GraphView(list(ctx["store"].values()), cfg.layer1,
                                   cfg.layer2.hub_block_share, documents)
        ch = ctx["change"]
        item = ChangeItem(ctx["change_id"], ch["document"], ch["section"], ch["old_text"],
                          ch["new_text"], ctx["lang"])
        cands = ctx["cands"]
        hybrid = rankings(ch["old_text"] + "\n" + ch["new_text"], cands, e5)["hybrid"]
        sig = graph_signals(views[sid], item, set(cands))
        orders = {"baseline": hybrid, "graph": graph_first(sig, hybrid),
                  "A": impact_ranking(sig, hybrid)}
        where = {m: {u: i for i, u in enumerate(o, start=1)} for m, o in orders.items()}
        reached = set().union(*sig.values())
        reached_sizes.append((ctx["change_id"], len(reached),
                              len(reached & {p.block_uid for p in pos})))
        for p in pos:
            if p.block_uid not in cands:
                continue
            groups = [("historical", p.historical)] if p.historical else [
                ("all",), ("kind", p.kind), ("lang", ctx["lang"]), (ctx["set"],)]
            if not p.historical and ctx["change_id"] not in ARTEFACTS:
                groups.append(("all without C32, C38",))
            if not p.historical and p.needs_revision in ("yes", "unsure"):
                groups.append(("needs_revision yes / unsure",))
            for g in groups:
                hits[g]["pairs"] += 1
                for m in METHODS:
                    r = where[m].get(p.block_uid, 10**9)
                    for k in KS:
                        hits[g][f"{m}@{k}"] += r <= k
            if not p.historical:
                reach[p.kind]["pairs"] += 1
                for s in SIGNALS:
                    reach[p.kind][s] += p.block_uid in sig[s]
                reach[p.kind]["any"] += any(p.block_uid in sig[s] for s in SIGNALS)

    out = ["# M5 step 1: impact retrieval, baseline vs graph (layers 0-2)", "",
           f"**Label source: {source}** ({DESCRIPTION[source]}). Most pairs come from "
           "synthetic edits written by the same AI reviewer that labelled them; real "
           "changes have very few dependents in this pilot.", "",
           f"{n_changes} change items with at least one needs_review pair. Candidates: all "
           "existing body blocks of the store at that time except the changed ones "
           "(about 300-490). Recall@N = share of (change, block) pairs labelled "
           "needs_review in the top N. baseline = hybrid search (char3 + e5, RRF); graph = "
           "blocks reached by a graph signal first, then hybrid order; A = RRF of hybrid "
           "and the graph signal rankings. Registry automatic, hubs above "
           f"{cfg.layer2.hub_block_share}. No LLM check (step 13) yet.", "",
           "## Recall at the same N", "",
           "| group | pairs | " + " | ".join(f"{m} @{k}" for m in METHODS for k in KS) + " |",
           "|---|---|" + "---|" * (len(METHODS) * len(KS))]
    order = sorted(hits, key=lambda g: (g[0] != "all", g[0] == "historical", len(g), g))
    for g in order:
        n = hits[g]["pairs"]
        cells = [f"{hits[g][f'{m}@{k}'] / n:.2f}" for m in METHODS for k in KS]
        out.append(f"| {' '.join(str(x) for x in g)} | {n} | " + " | ".join(cells) + " |")
    out += ["", "## Which graph signal reaches the positives (main pairs, any rank)", "",
            "| kind | pairs | " + " | ".join(SIGNALS) + " | any |",
            "|---|---|" + "---|" * (len(SIGNALS) + 1)]
    for kind in ("states", "cites", "depends"):
        c = reach[kind]
        if c["pairs"]:
            out.append(f"| {kind} | {c['pairs']} | "
                       + " | ".join(str(c[s]) for s in SIGNALS) + f" | {c['any']} |")
    sizes = sorted(n for _, n, _ in reached_sizes)
    out += ["", "## How many blocks the graph reaches per change", "",
            f"Over {len(sizes)} change items: median {sizes[len(sizes) // 2]}, "
            f"max {sizes[-1]}, total {sum(sizes)} blocks reached, of which "
            f"{sum(k for _, _, k in reached_sizes)} are labelled needs_review "
            "(historical included). A short list puts every reached block near the top, "
            "so graph @N is high when lists are short; the precision of the list is what "
            "the LLM check (step 13) has to handle.", "",
            "| change | blocks reached | needs_review among them |", "|---|---|---|"]
    out += [f"| {c} | {n} | {k} |" for c, n, k in sorted(reached_sizes, key=lambda x: -x[1])[:10]]
    out += ["", "**Pooling bias:** the judged candidates were pooled from char3, "
            "section-number search, layer 1 REFERENCES, e5 and random blocks (plus 8 hand "
            "additions). Layer 1 and section search are close to the cite_section signal, "
            "so cites positives the graph reaches were more likely to be judged at all; "
            "positives no pooled method found are absent. Recall here is relative to the "
            "judged pool, not to all true dependents."]
    out += ["", "Not checked: the LLM check of step 13 (precision of the final list), "
            "tokens per file, and any human label; results on Neo4j's stored graph "
            "(step 2) may differ where the graph holds older rule versions."]
    text = "\n".join(out)
    (ROOT / "eval" / "results" / f"m5_impact_{source}.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
