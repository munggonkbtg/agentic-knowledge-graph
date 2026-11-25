"""M4 step 2: what the entity registry alone (no LLM) links, before going further.

1. Registry size per language and type, and where each entity came from.
2. Hub distribution: share of the body blocks of each language that mention an
   entity, and how many entities a cut-off would flag (for the user's choice of
   `layer2.hub_block_share`).
3. Coverage of review pairs: for every (change, block) pair labelled
   needs_review with kind `states` or `depends` in the M5 sheets, does the
   changed block (old + new text) share a non-hub entity with the block?
   The same test on judged negatives (needs_review = no, same event) shows how
   much the link alone would pull in. Reported without hubs at several cut-offs.

Label source: --labels ai | human (M5 candidate sheets, eval/label_sources.py).
The continuation brief's 19-pair file (data/labels/m4_entity_type_coverage.csv)
is not used yet: it is not in data/labels/.

Committed report (counts, Thai entity names only, which come from CC0 text):
  eval/results/m4_registry_coverage_<source>.md
Full detail incl. English names and per-pair links (not in git):
  data/labels/m4_registry_detail_<source>.md

Run:  uv run --group embed python eval/m4_registry_coverage.py
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

from compare_embeddings import change_contexts, read
from label_sources import DESCRIPTION, sheet
from make_change_test_set import LABELS, ROOT

from kg.config import load_config
from kg.layer0_structure import parse_corpus
from kg.layer2_entities import (
    EntityMatcher,
    block_share,
    body_block_counts,
    build_registry,
    load_manual,
)

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
CUTOFFS = (None, 0.3, 0.2, 0.15, 0.1, 0.05)


def negatives_by_event(source: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for prefix in ("m5", "m5s", "m5e"):
        path = sheet(f"{prefix}_candidates", source)
        if not path.exists():
            continue
        key = json.loads((LABELS / f"{prefix}_key.json").read_text(encoding="utf-8"))
        for r in read(path):
            if r["needs_review"].strip().lower() == "no":
                out[r["event"]].append(key["candidates"][r["row_id"]]["block_uid"])
    return out


def analyse(docs, manual):
    reg = build_registry(docs, manual)
    matcher = EntityMatcher(reg)
    mentions = [m for d in docs for m in matcher.mentions(d)]
    return reg, matcher, block_share(mentions, body_block_counts(docs), reg)


def coverage_pairs(contexts, manual, merged, negatives):
    """Review pairs and negatives, each with the entities on both sides and the hub
    set per cut-off, from a registry built on the store at the time of the change."""
    cache: dict[int, tuple] = {}
    pairs, negs = [], []
    for ctx in contexts:
        sid = id(ctx["store"])
        if sid not in cache:
            reg, matcher, share = analyse(list(ctx["store"].values()), manual)
            hubs = {c: (set() if c is None else {e for e, s in share.items() if s > c})
                    for c in CUTOFFS}
            cache[sid] = (reg, matcher, hubs)
        reg, matcher, hubs = cache[sid]
        ch, lang = ctx["change"], ctx["lang"]
        a = {e for e, _ in matcher.find(ch["old_text"] + "\n" + ch["new_text"], lang)}
        for pos in merged.get(ctx["change_id"], []):
            if pos.kind in ("states", "depends") and pos.block_uid in ctx["cands"]:
                b = {e for e, _ in matcher.find(ctx["cands"][pos.block_uid], lang)}
                pairs.append({"change": ctx["change_id"], "kind": pos.kind, "lang": lang,
                              "group": pos.historical and "historical" or pos.kind,
                              "origin": pos.origin, "uid": pos.block_uid,
                              "a": a, "b": b, "hubs": hubs, "names":
                              {k: v.name for k, v in reg.entries.items()}})
        for uid in negatives.get(ch["event"], []):
            if uid in ctx["cands"]:
                negs.append((a, {e for e, _ in matcher.find(ctx["cands"][uid], lang)}, hubs))
    return pairs, negs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="ai", choices=["ai", "human"])
    source = ap.parse_args().labels
    cfg = load_config(ROOT / "config.yaml")
    docs = parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, T0)
    documents = load_manual(ROOT / cfg.layer2.manual_file, sources=["documents"])
    test_pairs = load_manual(ROOT / cfg.layer2.manual_file, sources=["test_pairs"])
    # registry and hub sections: the automatic registry (no test_pairs entries)
    reg = build_registry(docs, documents)
    matcher = EntityMatcher(reg)
    mentions = [m for d in docs for m in matcher.mentions(d)]
    bodies = body_block_counts(docs)
    share = block_share(mentions, bodies, reg)

    def hubs(cutoff):
        return set() if cutoff is None else {e for e, s in share.items() if s > cutoff}

    out = ["# M4: entity registry without an LLM", "",
           f"Initial corpus, {len(reg.entries)} entities, {len(mentions)} mentions "
           f"(one per block and entity) over {sum(bodies.values())} body blocks "
           f"({', '.join(f'{k} {v}' for k, v in sorted(bodies.items()))}).", "",
           "## Registry", "", "| language | type | entities | never mentioned |",
           "|---|---|---|---|"]
    for (lang, typ), n in sorted(Counter((e.language, e.entity_type)
                                         for e in reg.entries.values()).items()):
        zero = sum(1 for e in reg.entries.values() if e.language == lang
                   and e.entity_type == typ and share.get(e.entity_id, 0) == 0)
        out.append(f"| {lang} | {typ} | {n} | {zero} |")
    src = Counter(s.split(":")[0] for e in reg.entries.values() for s in set(
        x.split(":")[0] for x in e.sources))
    out += ["", "Sources (an entity can have several): "
            + ", ".join(f"{k} {v}" for k, v in sorted(src.items())), ""]
    per_block: dict[str, set[str]] = defaultdict(set)
    for m in mentions:
        per_block[m.block_uid].add(m.entity_id)
    out += ["Body blocks by number of entities mentioned:", "",
            "| language | 0 | 1 | 2 | 3+ |", "|---|---|---|---|---|"]
    for lang in sorted(bodies):
        c = Counter(min(len(per_block[pb.block.block_uid]), 3) for d in docs
                    if d.document.language.value == lang for pb in d.blocks
                    if pb.block.role.value == "body")
        out.append(f"| {lang} | {c[0]} | {c[1]} | {c[2]} | {c[3]} |")

    out += ["", "## Hub distribution", "",
            "Share of the body blocks of the entity's language that mention it.", "",
            "| cut-off (share >) | th hubs | en hubs |", "|---|---|---|"]
    for c in CUTOFFS[1:]:
        h = hubs(c)
        out.append(f"| {c} | {sum(reg.entries[e].language == 'th' for e in h)} "
                   f"| {sum(reg.entries[e].language == 'en' for e in h)} |")
    out += ["", "Thai entities above 0.05:", "", "| entity | type | share |", "|---|---|---|"]
    for e, s in sorted(share.items(), key=lambda kv: -kv[1]):
        if s > 0.05 and reg.entries[e].language == "th":
            out.append(f"| {reg.entries[e].name} | {reg.entries[e].entity_type} | {s:.3f} |")
    top_en = sorted((s for e, s in share.items() if reg.entries[e].language == "en"),
                    reverse=True)[:3]
    out.append(f"\nEnglish: highest shares {', '.join(f'{s:.3f}' for s in top_en)} "
               "(names in the detail file, not in git).")

    # ------------------------------------------------ coverage of review pairs
    from m5_labels import by_change, positives

    merged = by_change(positives(source), include_historical=True)
    negatives = negatives_by_event(source)
    contexts = list(change_contexts(cfg))
    out += ["", "## Coverage of review pairs (states / depends)", "",
            f"**Label source: {source}** ({DESCRIPTION[source]}). Labels merged from the "
            "m5 / m5s / m5e sheets and the additions, each (change, block) pair once "
            "(eval/m5_labels.py). A pair is linked when the changed block (old + new "
            "text) and the review block share an entity that is not a hub. The registry "
            "and the hub shares are rebuilt from the store as it was at each change. "
            "**Historical** pairs (blocks of an amending act, reason notes; "
            "kg/historical.py) are left out of states / depends / all and shown apart. "
            "Negatives: (change, block) pairs of the same event labelled "
            "needs_review = no.", "",
            "**automatic** = registry rules plus manual entries with source `documents` "
            f"({len(documents)} so far). **+ test_pairs** adds the manual entries taken "
            f"from the measured pairs ({len(test_pairs)}); that row is not an independent "
            "measurement and is never a headline number.", "",
            "| registry | hubs excluded above | states linked | depends linked "
            "| all linked | historical linked | negatives linked |",
            "|---|---|---|---|---|---|---|"]
    variants = {"automatic": documents, "+ test_pairs": documents + test_pairs}
    pairs_by_variant = {}
    for variant, extra in variants.items():
        pairs, negs = coverage_pairs(contexts, extra, merged, negatives)
        pairs_by_variant[variant] = pairs
        for c in CUTOFFS:
            linked, n = Counter(), Counter(p["group"] for p in pairs)
            for p in pairs:
                linked[p["group"]] += bool((p["a"] & p["b"]) - p["hubs"][c])
            main_l = linked["states"] + linked["depends"]
            neg = sum(bool((a & b) - h[c]) for a, b, h in negs)
            out.append(f"| {variant} | {c if c is not None else 'none'} "
                       f"| {linked['states']}/{n['states']} "
                       f"| {linked['depends']}/{n['depends']} "
                       f"| {main_l}/{n['states'] + n['depends']} "
                       f"| {linked['historical']}/{n['historical']} "
                       f"| {neg}/{len(negs)} ({neg / len(negs):.0%}) |")
    # the brief's coverage file (AI), same pairs seen another way
    cov_path = sheet("m4_entity_type_coverage", source)
    if cov_path.exists():
        cov = {(r["block_uid"], c) for r in read(cov_path)
               for c in [x.strip() for x in r["change_ids"].split(";") if x.strip()]}
        auto = pairs_by_variant["automatic"]
        hub = cfg.layer2.hub_block_share
        hit = [p for p in auto if (p["uid"], p["change"]) in cov]
        out.append(f"\nCoverage file `{cov_path.name}` ({len(cov)} change-block pairs): "
                   f"{len(hit)} found among the labelled pairs above; automatic registry "
                   f"links {sum(bool((p['a'] & p['b']) - p['hubs'][hub]) for p in hit)} of "
                   f"them at the hub cut-off {hub} "
                   f"({sum(1 for p in hit if p['group'] == 'historical')} historical).")
    pairs = pairs_by_variant["automatic"]
    out.append(f"\nPairs by language: {dict(sorted(Counter(p['lang'] for p in pairs).items()))}. "
               "Pairs where the changed block has no entity at all: "
               + ", ".join(f"{v} {sum(1 for p in ps if not p['a'])}"
                           for v, ps in pairs_by_variant.items()) + ".")
    out += ["", "Not checked: precision of single mentions (needs the blind MENTIONS "
            "sheet); values on MENTIONS (step 3)."]
    text = "\n".join(out)
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / f"m4_registry_coverage_{source}.md").write_text(
        text, encoding="utf-8")
    print(text)

    # ------------------------------------------------ detail, not in git
    h = hubs(cfg.layer2.hub_block_share)
    det = [f"# M4 registry detail ({source} labels; hubs above "
           f"{cfg.layer2.hub_block_share})", "", "## Entities", "",
           "| id | name | type | share | aliases | sources |", "|---|---|---|---|---|---|"]
    for e in sorted(reg.entries.values(), key=lambda e: (e.language, -share.get(e.entity_id, 0))):
        det.append(f"| {e.entity_id} | {e.name} | {e.entity_type} | "
                   f"{share.get(e.entity_id, 0):.3f} | {', '.join(sorted(e.aliases - {e.name}))} "
                   f"| {', '.join(sorted(e.sources))} |")
    for variant, ps in pairs_by_variant.items():
        det += ["", f"## Review pairs, {variant}", "",
                "| change | kind | lang | shared (non-hub) | changed block entities "
                "| review block entities |", "|---|---|---|---|---|---|"]
        for p in sorted(ps, key=lambda p: (p["kind"], p["change"])):
            name, hub = p["names"], p["hubs"].get(cfg.layer2.hub_block_share, set())
            det.append(f"| {p['change']} | {p['kind']} | {p['lang']} "
                       f"| {', '.join(sorted(name[x] for x in (p['a'] & p['b']) - hub))} "
                       f"| {', '.join(sorted(name[x] for x in p['a']))} "
                       f"| {', '.join(sorted(name[x] for x in p['b']))} |")
    (LABELS / f"m4_registry_detail_{source}.md").write_text("\n".join(det), encoding="utf-8")


if __name__ == "__main__":
    main()
