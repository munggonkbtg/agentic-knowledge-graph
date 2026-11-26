"""Layer 3 (M6): merge duplicate entities, Thai-English included.

Workflow step 5. The registry of layer 2 makes one entity per name; the same
thing written differently ("Short Term Disability" / "short-term disability
claim", a Thai name and its English translation) stays apart, so a shared
entity is missed. This layer:

1. Candidate pairs, no LLM (blocking): same entity type, neither a hub, and
   either one name contains the other after normalization (same language), or
   the e5 similarity of the two names is at least `min_similarity`, keeping the
   `top_k` nearest names per entity.
2. The local LLM confirms each pair (prompt merge_v1): same / different / unsure.
3. Rule check: only "same" merges; types must match; a containment pair
   merges only when the longer name adds generic words alone ("claim",
   "policy", "สิทธิ") — the LLM merged "ค่าจ้างในวันทำงาน" into "วันทำงาน" on the
   pilot, so this is a code rule, not a prompt rule. Merges are transitive
   (union-find). The canonical entity of a group is the one with the most
   mentions (then: a definition source, then the shorter id).

Nothing here touches Neo4j; `Store.write_merges` writes the result: the merged
entities' aliases get ALIAS_OF to the canonical entity (method llm) and the
merged entity gets `merged_into` (reversible).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from kg.layer2_entities import EntityRegistry


@dataclass
class MergeEntity:
    entity_id: str
    name: str
    entity_type: str
    language: str
    mentions: int = 0
    hub: bool = False
    sources: tuple[str, ...] = ()
    examples: list[str] = field(default_factory=list)  # short passages, for the LLM


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    reason: str  # containment / similarity 0.91


@dataclass
class MergeResult:
    pairs: list[Pair]
    verdicts: dict[tuple[str, str], str]       # pair -> same / different / unsure / failed
    reasons: dict[tuple[str, str], str]
    canonical: dict[str, str]                  # merged entity -> canonical entity
    calls: int = 0


def _key(e: MergeEntity) -> str:
    """Thai: compact form; English: lower case, hyphens and spaces alike (as the
    layer 2 matcher treats them)."""
    if e.language == "th":
        return EntityRegistry.key(e.language, e.name)
    return re.sub(r"[\s-]+", " ", e.name.lower()).strip()


def candidate_pairs(entities: list[MergeEntity], embed: Callable[[list[str]], object] | None,
                    min_similarity: float, top_k: int, min_chars: int) -> list[Pair]:
    """Pairs to send to the LLM, each once (a < b by id)."""
    ents = [e for e in entities if not e.hub]
    found: dict[tuple[str, str], str] = {}

    def add(x: MergeEntity, y: MergeEntity, why: str) -> None:
        if x.entity_id == y.entity_id or x.entity_type != y.entity_type:
            return
        k = tuple(sorted((x.entity_id, y.entity_id)))
        found.setdefault(k, why)

    by_lang: dict[str, list[MergeEntity]] = {}
    for e in ents:
        by_lang.setdefault(e.language, []).append(e)
    for group in by_lang.values():
        keys = [(_key(e), e) for e in group]
        for ka, a in keys:
            if len(ka) < min_chars:
                continue
            for kb, b in keys:
                if a is not b and len(kb) > len(ka) and ka in kb:
                    add(a, b, "containment")
    if embed is not None and len(ents) > 1:
        import numpy as np  # embed dependency group

        vecs = np.asarray(embed([e.name for e in ents]), dtype=float)
        sims = vecs @ vecs.T
        for i, a in enumerate(ents):
            order = np.argsort(-sims[i], kind="stable")
            kept = 0
            for j in order:
                if j == i:
                    continue
                if sims[i, j] < min_similarity or kept >= top_k:
                    break
                if ents[j].entity_type == a.entity_type:
                    add(a, ents[j], f"similarity {sims[i, j]:.2f}")
                    kept += 1
    return [Pair(a, b, why) for (a, b), why in sorted(found.items())]


# A name that contains another is usually narrower ("ค่าล่วงเวลาในวันหยุด" is not
# "ค่าล่วงเวลา"). It may merge only when what it adds is generic wording.
GENERIC_EXTRA_EN = {"claim", "claims", "policy", "policies", "benefit", "benefits", "plan",
                    "plans", "program", "programs", "programme", "the", "of", "a"}
GENERIC_EXTRA_TH = ("สิทธิ์", "สิทธิ")


def containment_allows_merge(a: MergeEntity, b: MergeEntity) -> bool:
    """Rule check for a containment pair: True when the longer name only adds
    generic words to the shorter one (checked after the LLM said "same")."""
    ka, kb = _key(a), _key(b)
    short, long_ = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    if short not in long_:
        return True  # not a containment pair
    extra = long_.replace(short, " ", 1)
    if a.language == "th":
        rest = extra.strip()
        for g in GENERIC_EXTRA_TH:
            rest = rest.replace(g, "")
        return rest.strip() == ""
    return set(extra.split()) <= GENERIC_EXTRA_EN


def _canonical_order(e: MergeEntity) -> tuple:
    definition = any(s.startswith("definition") for s in e.sources)
    return (-e.mentions, not definition, len(e.entity_id), e.entity_id)


def merge_entities(entities: list[MergeEntity], pairs: list[Pair], confirm) -> MergeResult:
    """confirm(a, b) -> LLM CallResult with data.verdict / data.reason (or None)."""
    by_id = {e.entity_id: e for e in entities}
    verdicts, reasons, calls = {}, {}, 0
    parent = {e.entity_id: e.entity_id for e in entities}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        a, b = by_id[p.a], by_id[p.b]
        res = confirm(a, b)
        calls += not getattr(res, "cached", False)
        v = res.data.verdict if res.data is not None else "failed"
        if v == "same" and p.reason == "containment" and not containment_allows_merge(a, b):
            v = "same, blocked by rule (narrower / broader name)"
        verdicts[(p.a, p.b)] = v
        reasons[(p.a, p.b)] = res.data.reason if res.data is not None else ""
        if v == "same" and a.entity_type == b.entity_type:
            ra, rb = find(p.a), find(p.b)
            if ra != rb:
                parent[ra] = rb
    groups: dict[str, list[MergeEntity]] = {}
    for e in entities:
        groups.setdefault(find(e.entity_id), []).append(e)
    canonical = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        head = sorted(members, key=_canonical_order)[0]
        for m in members:
            if m.entity_id != head.entity_id:
                canonical[m.entity_id] = head.entity_id
    return MergeResult(pairs, verdicts, reasons, canonical, calls)
