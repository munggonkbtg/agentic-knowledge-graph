"""Impact analysis (M5, workflow steps 11-12): candidate blocks for a change.

A change is an edited, moved, removed or added block (old text, new text, the
document and the heading path where it sits). Candidates are the existing body
blocks of the store, ranked by:

Graph signals (layers 0-2, each its own ranked list):
* broken_reference  the block cites the changed section or heading anchor and
                that target no longer exists in the document's version after
                the upload (renamed heading, removed section): a rule, no LLM
* depends       a DEPENDS edge (layer 4) joins the block and the changed block
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

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from kg.layer0_structure import ParsedDocument
from kg.layer1_references import Registry, RegistryEntry, ReferenceExtractor, compact
from kg.layer2_entities import EntityMatcher, block_share, body_block_counts, build_registry
from kg.values import AttachedValue, Value, attach_values, extract_values

RRF_K = 60
SIGNALS = ("broken_reference", "cite_section", "depends", "value", "entity", "cite_document")
_SECTION_HEAD = re.compile(r"^(มาตรา|ข้อ|หมวด|ส่วน)([0-9]+(?:/[0-9]+)?)")


@dataclass(frozen=True)
class ChangeItem:
    change_id: str
    doc_key: str
    section_path: str  # heading path of the changed block ("_" for none)
    old_text: str
    new_text: str
    language: str
    block_uid: str = ""  # the changed block: the old one if any, else the new one


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


def citable_targets(doc: ParsedDocument) -> set[str]:
    """What a citation can point at in this version of a document, in the compact,
    lower-case form REFERENCES store: section keys (มาตรา118, ข้อ9/1, หมวด5) and
    the '#anchor' of every heading."""
    out = set()
    for pb in doc.blocks:
        for heading in pb.block.block_id.split("::")[1].split(" > "):
            if heading == "_":
                continue
            m = _SECTION_HEAD.match(compact(heading)[0])
            if m:
                out.add((m.group(1) + m.group(2)).lower())
            out.add(heading_anchor(heading))
    return out


def target_exists(cited: str, targets: set[str]) -> bool:
    """'มาตรา118(6)' exists when 'มาตรา118' does; '#anchor' must match exactly."""
    if cited.startswith("#"):
        return cited in targets
    m = _SECTION_HEAD.match(cited)
    return (m.group(1) + m.group(2)).lower() in targets if m else True


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
                 manual: list[dict] = (), merges: dict[str, str] | None = None,
                 depends: list[tuple[str, str]] = ()) -> None:
        self.canonical = dict(merges or {})
        self.depends: dict[str, set[str]] = defaultdict(set)
        for a, b in depends:
            self.depends[a].add(b)
            self.depends[b].add(a)
        self.ref_conf: dict[tuple[str, str, str], float] = {}
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
        self.targets = {d.document.doc_key: citable_targets(d) for d in docs}
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

    @classmethod
    def from_graph(cls, blocks: list[dict], edges: dict[str, list], docs: list[ParsedDocument],
                   manual: list[dict] = ()) -> GraphView:
        """The same view, read from Neo4j: current body blocks
        (Store.current_body_blocks), valid REFERENCES and MENTIONS with their
        values and the hub flags (Store.impact_edges). The registry is rebuilt
        from the current versions only to read entities in the change text (the
        old and new block), with the same rules and manual file as the graph."""
        view = cls.__new__(cls)
        view.canonical = dict(edges.get("merges", {}))
        view.depends = defaultdict(set)
        for a, b in edges.get("depends", []):
            view.depends[a].add(b)
            view.depends[b].add(a)
        view.refs = defaultdict(list)
        view.ref_conf = {}
        for r in edges["refs"]:
            cited = compact(r["cited_section"] or "")[0].lower()
            view.refs[r["target"]].append((r["uid"], cited))
            if r.get("confidence") is not None:
                view.ref_conf[(r["uid"], r["target"], cited)] = float(r["confidence"])
        view.targets = {d.document.doc_key: citable_targets(d) for d in docs}
        view.registry = build_registry(docs, manual)
        view.matcher = EntityMatcher(view.registry)
        view.hubs = set(edges["hubs"])
        view.blocks = {b["uid"]: BlockFacts(b["doc_key"], b["text"], b["language"])
                       for b in blocks}

        def values_of(row: dict, entity: str | None) -> list[AttachedValue]:
            if not row.get("value"):
                return []
            return [AttachedValue(Value(v, u, f, bv, bu, t, 0, 0), entity, a)
                    for v, u, f, bv, bu, t, a in zip(row["value"], row["unit"], row["family"],
                                                    row["base_value"], row["base_unit"],
                                                    row["value_text"], row["attribute"])]

        for m in edges["mentions"]:
            b = view.blocks.get(m["uid"])
            if b is None or m["hub"]:
                continue
            eid = view.canonical.get(m["entity"], m["entity"])
            b.entities.add(eid)
            b.values += values_of(m, eid)
        for r in edges["loose"]:
            b = view.blocks.get(r["uid"])
            if b is not None:
                b.values += values_of(r, None)
        return view

    def facts(self, text: str, language: str) -> tuple[set[str], list[AttachedValue]]:
        """Non-hub entities (canonical after layer 3 merges) and attached values."""
        spans = self.matcher.find_spans(text, language)
        canon = getattr(self, "canonical", {})
        if canon:
            spans = [(canon.get(e, e), sf, a, b) for e, sf, a, b in spans]
        ents = {s[0] for s in spans} - self.hubs
        return ents, attach_values(extract_values(text, language), spans, self.hubs)


def graph_signals(view: GraphView, change: ChangeItem, candidates: set[str],
                  targets_after: dict[str, set[str]] | None = None
                  ) -> dict[str, dict[str, float]]:
    """signal -> {block_uid: strength} for the candidate blocks that have it.
    targets_after: what each document can be cited at after the upload
    (default: the view's own documents, i.e. the current versions)."""
    out: dict[str, dict[str, float]] = {s: {} for s in SIGNALS}
    key = section_key(change.section_path)
    anchor = heading_anchor(change.section_path)
    after = (targets_after if targets_after is not None else view.targets).get(change.doc_key)
    for uid, cited in view.refs.get(change.doc_key, []):
        if uid not in candidates:
            continue
        if (key and _cites(cited, key.lower())) or (anchor and cited == anchor):
            # edge confidence: a citation rejected in review ranks lower (step 15)
            conf = view.ref_conf.get((uid, change.doc_key, cited), 1.0)
            out["cite_section"][uid] = max(out["cite_section"].get(uid, 0.0), conf)
            if after is not None and not target_exists(cited, after):
                out["broken_reference"][uid] = 1.0
        elif cited == "":
            out["cite_document"][uid] = 1.0
    for uid in view.depends.get(change.block_uid, ()):
        if uid in candidates:
            out["depends"][uid] = 1.0
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
        for u in ranked(signals.get(s, {}), hybrid):
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out + [u for u in hybrid if u not in seen]


def impact_ranking(signals: dict[str, dict[str, float]], hybrid: list[str]) -> list[str]:
    """Variant A: RRF of the hybrid ranking and one ranking per graph signal;
    blocks no list reaches keep their hybrid order at the end."""
    fused = rrf(hybrid, *[ranked(signals[s], hybrid) for s in SIGNALS if signals.get(s)])
    return fused + [u for u in hybrid if u not in set(fused)]



# ---------------------------------------------------------------- hybrid search


def _trigrams(text: str) -> Counter:
    c = compact(text)[0].lower()
    return Counter(c[i:i + 3] for i in range(max(0, len(c) - 2)))


class Char3Index:
    """TF-IDF over character trigrams (works for Thai without word splitting).
    Same as the index the M5 change test set was pooled with."""

    def __init__(self, texts: dict[str, str]) -> None:
        self.tf = {k: _trigrams(v) for k, v in texts.items()}
        df = Counter(g for tf in self.tf.values() for g in tf)
        n = len(self.tf)
        self.idf = {g: math.log((1 + n) / (1 + d)) + 1 for g, d in df.items()}
        self.vec = {k: self._weigh(tf) for k, tf in self.tf.items()}

    def _weigh(self, tf: Counter) -> dict[str, float]:
        v = {g: c * self.idf.get(g, 1.0) for g, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {g: x / norm for g, x in v.items()}

    def ranking(self, text: str) -> list[str]:
        """Every indexed key, best first (zero scores last, by key)."""
        q = self._weigh(_trigrams(text))
        scores = [(sum(w * vec.get(g, 0.0) for g, w in q.items()), key)
                  for key, vec in self.vec.items()]
        return [key for _, key in sorted(scores, key=lambda x: (-x[0], x[1]))]


def changes_from_stored_diff(doc_key: str, diff: dict, language: str) -> list[ChangeItem]:
    """Change items from Store.version_changes: edited / moved / added blocks and
    removed blocks of a document's current version."""
    out = []
    for i, c in enumerate(diff["changed"], start=1):
        where = c["prev_block_id"] if c["status"] in ("edited", "moved") and c["prev_block_id"] \
            else c["block_id"]
        out.append(ChangeItem(f"{c['status']}-{i}", c["prev_doc"] or doc_key,
                              where.split("::")[1] if where else "_", c["old_text"] or "",
                              c["new_text"] or "", language, c["prev_uid"] or c["uid"]))
    for i, r in enumerate(diff["removed"], start=1):
        where = r["block_id"] or ""
        out.append(ChangeItem(f"removed-{i}", doc_key,
                              where.split("::")[1] if "::" in where else "_",
                              r["old_text"] or "", "", language, r["uid"]))
    return out


def order_after_check(order: list[str], verdicts: dict[str, str], historical: set[str],
                      top: int) -> list[str]:
    """M5 step 13 as a label, not a filter (decided 2026-11-26): every candidate
    stays. Inside the checked top, blocks the checker marked needs_update come
    first (stable), except historical blocks; the rest keeps its order."""
    head, tail = order[:top], order[top:]
    first = [u for u in head if verdicts.get(u) == "needs_update" and u not in historical]
    return first + [u for u in head if u not in set(first)] + tail


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "\u0093": '"', "\u0094": '"'})


def evidence_in(evidence: str, text: str) -> bool:
    """The checker's quoted evidence occurs in the candidate block: compared in
    compact form (no spaces, Arabic digits), case-insensitive, with curly and
    straight quotes treated alike; a quote that joins fragments with '...' or
    '…' counts when every fragment occurs."""
    def norm(s: str) -> str:
        return compact(s.translate(_QUOTES))[0].lower().strip("\"'")

    body = norm(text)
    parts = [norm(p) for p in re.split(r"\.\.\.|…", evidence)]
    parts = [p for p in parts if p]
    return bool(parts) and all(p in body for p in parts)
