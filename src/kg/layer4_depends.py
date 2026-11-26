"""Layer 4 (M7): DEPENDS edges between blocks.

Workflow step 6. A block DEPENDS on another when it uses a fact stated there
without citing it, so a change to that fact can make it wrong while no citation,
shared name or value links them. The LLM is the only judge here, so the work is
capped:

1. Centrality: blocks ranked by degree (distinct blocks sharing a non-hub
   canonical entity + REFERENCES out of the block). Only the top
   `central_share` are processed (0.2 = variant B of the diagram, 1.0 = C); a
   pipeline run can instead pass the new / edited blocks (`only`).
2. Candidate pairs per processed block: blocks sharing a non-hub entity (most
   shared first), then the `nearest_k` nearest by e5; at most
   `max_pairs_per_block`; each unordered pair once.
3. The local LLM (prompt depends_v1) answers direction, fact and two quotes.
   An edge is kept only when the direction is not "none" and BOTH quotes are
   found in their blocks (kg.impact.evidence_in); everything else is counted.

Nothing here touches Neo4j; `Store.write_depends` writes
(dependent)-[:DEPENDS {fact, evidence_span, evidence_target, ...}]->(source).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable

from kg.impact import evidence_in


@dataclass
class DepBlock:
    uid: str
    text: str
    doc_key: str
    context: str                      # document > section, for the prompt
    entities: set[str] = field(default_factory=set)  # non-hub, canonical
    refs_out: int = 0


@dataclass(frozen=True)
class DependsEdge:
    dependent: str
    source: str
    fact: str
    evidence_dependent: str
    evidence_source: str


@dataclass
class DependsResult:
    processed: list[str]
    pairs: list[tuple[str, str]]
    edges: list[DependsEdge]
    stats: Counter


def centrality(blocks: dict[str, DepBlock]) -> dict[str, int]:
    holders: dict[str, set[str]] = defaultdict(set)
    for u, b in blocks.items():
        for e in b.entities:
            holders[e].add(u)
    out = {}
    for u, b in blocks.items():
        sharing = set().union(*(holders[e] for e in b.entities)) - {u} if b.entities else set()
        out[u] = len(sharing) + b.refs_out
    return out


def select_blocks(blocks: dict[str, DepBlock], share: float,
                  only: set[str] | None = None) -> list[str]:
    if only is not None:
        return sorted(u for u in only if u in blocks)
    score = centrality(blocks)
    n = max(1, math.ceil(share * len(blocks)))
    return sorted(blocks, key=lambda u: (-score[u], u))[:n]


def candidate_pairs(blocks: dict[str, DepBlock], processed: list[str],
                    nearest: Callable[[str], list[str]], nearest_k: int,
                    max_per_block: int) -> list[tuple[str, str]]:
    holders: dict[str, set[str]] = defaultdict(set)
    for u, b in blocks.items():
        for e in b.entities:
            holders[e].add(u)
    seen: set[tuple[str, str]] = set()
    out = []
    for u in processed:
        b = blocks[u]
        shared = Counter(v for e in b.entities for v in holders[e] if v != u)
        by_entity = [v for v, _ in sorted(shared.items(), key=lambda kv: (-kv[1], kv[0]))]
        near = [v for v in nearest(u)[:nearest_k] if v != u and v in blocks]
        kept = 0
        for v in by_entity + [v for v in near if v not in shared]:
            if kept >= max_per_block:
                break
            k = tuple(sorted((u, v)))
            if k in seen:
                continue
            seen.add(k)
            out.append(k)
            kept += 1
    return out


def find_depends(blocks: dict[str, DepBlock], pairs: list[tuple[str, str]], judge) -> DependsResult:
    """judge(a, b) -> LLM CallResult with data: DependsVerdict (or None)."""
    stats = Counter()
    edges = []
    for a, b in pairs:
        res = judge(blocks[a], blocks[b])
        stats["calls_new"] += not getattr(res, "cached", False)
        v = res.data
        if v is None:
            stats["failed"] += 1
            continue
        if v.direction == "none":
            stats["none"] += 1
            continue
        dep, src = (a, b) if v.direction == "a_on_b" else (b, a)
        if not (evidence_in(v.evidence_dependent, blocks[dep].text)
                and evidence_in(v.evidence_source, blocks[src].text)):
            stats["evidence_not_found"] += 1
            continue
        stats["edges"] += 1
        edges.append(DependsEdge(dep, src, v.fact, v.evidence_dependent, v.evidence_source))
    return DependsResult([], pairs, edges, stats)
