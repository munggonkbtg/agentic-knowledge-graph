"""Impact analysis (M5, workflow steps 11-12): candidate blocks for a change.

A change is an edited, moved, removed or added block (old text, new text, the
document and the heading path where it sits). Candidates are the existing body
blocks of the store, ranked by:

Graph signals (layers 0-2, each its own ranked list):
* cite_section  the block has a REFERENCES edge to the changed document whose
                cited section is the changed block's section (Thai มาตรา / ข้อ,
                English #anchor of the heading)
* value         the block states the old value of an attribute that the change
                gives a different value (same entity and unit family), or holds
                a changed value at all
* entity        the block shares non-hub entities with the change (more first)
* cite_document the block cites the changed document as a whole
Within a list, ties follow the hybrid ranking.

Hybrid search (baseline): passed in by the caller (character-trigram TF-IDF and
multilingual-e5 fused with RRF), so this module has no model dependency.

Final ranking: Reciprocal Rank Fusion of the hybrid ranking and the graph lists
(workflow step 12). Nothing here reads or writes Neo4j: a GraphView is built
from parsed documents, so the same code runs on the graph's current versions or
on the synthetic stores of the change test set.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from kg.layer0_structure import ParsedDocument
from kg.layer1_references import Registry, RegistryEntry, ReferenceExtractor, compact
from kg.layer2_entities import EntityMatcher, block_share, body_block_counts, build_registry
from kg.values import AttachedValue, attach_values, extract_values

RRF_K = 60
SIGNALS = ("cite_section", "value", "entity", "cite_document")


@dataclass(frozen=True)
class ChangeItem:
    change_id: str
    doc_key: str
    section_path: str  # heading path of the changed block ("_" for none)
    old_text: str
    new_text: str
    language: str


def section_key(section_path: str) -> str | None:
    """'หมวด 2 … > มาตรา 34' -> 'มาตรา34' (compact), else None."""
    last = section_path.split(" > ")[-1]
    m = re.fullmatch(r"(มาตรา|ข้อ)\s*([0-9๐-๙]+(?:/[0-9๐-๙]+)?)", last.strip())
    return compact(f"{m.group(1)}{m.group(2)}")[0] if m else None


def heading_anchor(section_path: str) -> str | None:
    """English heading -> '#anchor' as GitHub builds it ('Your First 90 Days' ->
    '#your-first-90-days')."""
    if section_path in ("", "_"):
        return None
    heading = section_path.split(" > ")[-1].lower()
    return "#" + re.sub(r"[^\w\s-]", "", heading).strip().replace(" ", "-")


def _cites(cited: str, key: str) -> bool:
    """'มาตรา118(6)' cites 'มาตรา118'; 'มาตรา1181' does not."""
    return cited == key or (cited.startswith(key) and not re.match(r"[\d/]", cited[len(key):]))


@dataclass
class BlockFacts:
    doc_key: str
    text: str
    language: str
    entities: set[str] = field(default_factory=set)        # non-hub
    values: list[AttachedValue] = field(default_factory=list)


class GraphView:
    """Layers 0-2 of a store, in memory: REFERENCES by target document, and the
    non-hub entities and attached values of every body block."""

    def __init__(self, docs: list[ParsedDocument], layer1_cfg, hub_cut: float | None,
                 manual: list[dict] = ()) -> None:
        entries = []
        for d in docs:
            names = {PurePosixPath(d.version.source_url).name} if d.version.source_url else set()
            names.add(d.version.source_file)
            entries.append(RegistryEntry(d.document.doc_key, d.document.title,
                                         d.document.language.value, tuple(sorted(names))))
        extractor = ReferenceExtractor(Registry(entries), layer1_cfg)
        self.refs: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for d in docs:
            for r in extractor.extract(d).references:
                self.refs[r.target].append((r.block_uid, compact(r.cited_section)[0].lower()))
        self.registry = build_registry(docs, manual)
        self.matcher = EntityMatcher(self.registry)
        mentions = [m for d in docs for m in self.matcher.mentions(d)]
        share = block_share(mentions, body_block_counts(docs), self.registry)
        self.hubs = {e for e, s in share.items() if hub_cut is not None and s > hub_cut}
        self.blocks: dict[str, BlockFacts] = {}
        for d in docs:
            lang = d.document.language.value
            for pb in d.blocks:
                if pb.block.role.value == "body":
                    ents, vals = self.facts(pb.block.text, lang)
                    self.blocks[pb.block.block_uid] = BlockFacts(
                        d.document.doc_key, pb.block.text, lang, ents, vals)

    def facts(self, text: str, language: str) -> tuple[set[str], list[AttachedValue]]:
        spans = self.matcher.find_spans(text, language)
        ents = {s[0] for s in spans} - self.hubs
        return ents, attach_values(extract_values(text, language), spans, self.hubs)


def graph_signals(view: GraphView, change: ChangeItem, candidates: set[str]
                  ) -> dict[str, dict[str, float]]:
    """signal -> {block_uid: strength} for the candidate blocks that have it."""
    out: dict[str, dict[str, float]] = {s: {} for s in SIGNALS}
    key = section_key(change.section_path)
    anchor = heading_anchor(change.section_path)
    for uid, cited in view.refs.get(change.doc_key, []):
        if uid not in candidates:
            continue
        if (key and _cites(cited, key.lower())) or (anchor and cited == anchor):
            out["cite_section"][uid] = 1.0
        elif cited == "":
            out["cite_document"][uid] = 1.0
    old_e, old_v = view.facts(change.old_text, change.language)
    new_e, new_v = view.facts(change.new_text, change.language)
    ents = old_e | new_e
    new_comp = {a.value.comparable() for a in new_v}
    changed = {a.value.comparable() for a in old_v} - new_comp
    new_by_attr = defaultdict(set)
    for a in new_v:
        new_by_attr[a.attribute].add(a.value.comparable())
    changed_attr = {(a.attribute, a.value.comparable()) for a in old_v
                    if a.entity_id and new_by_attr.get(a.attribute)
                    and a.value.comparable() not in new_by_attr[a.attribute]}
    for uid in candidates:
        b = view.blocks.get(uid)
        if b is None:
            continue
        shared = len(b.entities & ents)
        if shared:
            out["entity"][uid] = float(shared)
        attr_hit = {(a.attribute, a.value.comparable()) for a in b.values} & changed_attr
        value_hit = {a.value.comparable() for a in b.values} & changed
        if attr_hit or value_hit:
            out["value"][uid] = 2.0 * len(attr_hit) + len(value_hit)
    return out


def ranked(signal: dict[str, float], tie_break: list[str]) -> list[str]:
    pos = {u: i for i, u in enumerate(tie_break)}
    return sorted(signal, key=lambda u: (-signal[u], pos.get(u, len(pos)), u))


def rrf(*rankings: list[str], k: int = RRF_K) -> list[str]:
    score: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for r, key in enumerate(ranking, start=1):
            score[key] += 1.0 / (k + r)
    return sorted(score, key=lambda x: (-score[x], x))


def graph_first(signals: dict[str, dict[str, float]], hybrid: list[str]) -> list[str]:
    """Blocks with a graph signal, strongest signal first (cite_section, value,
    entity, cite_document), then the rest in hybrid order."""
    out, seen = [], set()
    for s in SIGNALS:
        for u in ranked(signals[s], hybrid):
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out + [u for u in hybrid if u not in seen]


def impact_ranking(signals: dict[str, dict[str, float]], hybrid: list[str]) -> list[str]:
    """Variant A: RRF of the hybrid ranking and one ranking per graph signal;
    blocks no list reaches keep their hybrid order at the end."""
    fused = rrf(hybrid, *[ranked(signals[s], hybrid) for s in SIGNALS if signals[s]])
    return fused + [u for u in hybrid if u not in set(fused)]

