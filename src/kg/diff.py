"""Block matching across versions (pipeline step 9).

Given the old and new version of a document, label every block:

* ``unchanged`` – pass 1: the same normalized text (same ``content_hash``).
* ``edited``    – pass 2: in the same section, text similarity at or above
                  ``diff.edit_similarity_threshold``; or pass 2b: in another
                  section of the same document, similarity at or above
                  ``diff.cross_section_edit_threshold`` (moved and edited).
* ``moved``     – pass 3: a removed block found among the *added* blocks of another
                  document uploaded in the same event (exact or similar text).
* ``removed`` / ``added`` – everything left over.

Blocks with ``role == footnote`` (entries of the Thai footnote lists, see
``layer0.footnote_sections``) are matched in pass 1 only: their text is a
template, so similarity would pair unrelated entries.

Pass 3 has its own threshold, ``diff.move_similarity_threshold``, because a
paragraph moved to another document is often rewritten on the way.

"Same section" means the same normalized heading path. With
``align_renamed_sections`` a renamed heading still counts as the same section when
most of its unchanged blocks went to one new section.

*Similarity* is rapidfuzz's ``ratio`` on normalized text: 1.0 for identical text,
0.0 for nothing in common. It works on characters, so Thai needs no word splitting.

Each pairing is one-to-one: a block is matched at most once. Within a pass, the
best-scoring pairs are taken first (greedy matching).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum

from rapidfuzz import fuzz

from kg.config import DiffSettings
from kg.layer0_structure import Normalizer, ParsedBlock, ParsedDocument
from kg.models import BlockRole


class MatchStatus(StrEnum):
    UNCHANGED = "unchanged"
    EDITED = "edited"
    MOVED = "moved"
    REMOVED = "removed"
    ADDED = "added"


@dataclass(frozen=True)
class BlockMatch:
    status: MatchStatus
    old: ParsedBlock | None
    new: ParsedBlock | None
    similarity: float | None = None  # None when there is no partner
    # A block moved to another document and split there: the new blocks after
    # ``new`` (consecutive in that document). Empty otherwise.
    extra_new: tuple[ParsedBlock, ...] = ()

    @property
    def new_blocks(self) -> tuple[ParsedBlock, ...]:
        """Every new block this match covers (several when a moved block was split)."""
        return ((self.new,) if self.new else ()) + self.extra_new

    @property
    def same_position(self) -> bool:
        return bool(self.old and self.new and self.old.block.block_id == self.new.block.block_id)


def similarity(a: str, b: str) -> float:
    return fuzz.ratio(a, b) / 100.0


def _section_paths(doc: ParsedDocument) -> dict[str, tuple[str, ...]]:
    return {ps.section.section_id: ps.section.heading_path for ps in doc.sections}


def _fuzzy(pb: ParsedBlock) -> bool:
    """May this block be paired by similarity (passes 2, 2b, 3)?"""
    return pb.block.role != BlockRole.FOOTNOTE


def _greedy(
    pairs: list[tuple[float, int, int, int]], threshold: float
) -> list[tuple[int, int, float]]:
    """Pick one-to-one pairs, best score first. Items: (score, tiebreak, old_i, new_i)."""
    taken_old: set[int] = set()
    taken_new: set[int] = set()
    chosen = []
    for score, _, oi, ni in sorted(pairs, key=lambda p: (-p[0], p[1], p[2], p[3])):
        if score < threshold or oi in taken_old or ni in taken_new:
            continue
        taken_old.add(oi)
        taken_new.add(ni)
        chosen.append((oi, ni, score))
    return chosen


def diff_versions(
    old: ParsedDocument, new: ParsedDocument, cfg: DiffSettings, norm: Normalizer
) -> list[BlockMatch]:
    """Match the blocks of two versions of the same document."""
    if old.document.doc_key != new.document.doc_key:
        raise ValueError("diff_versions needs two versions of the same document")
    olds, news = list(old.blocks), list(new.blocks)
    old_left = set(range(len(olds)))
    new_left = set(range(len(news)))
    matches: list[BlockMatch] = []

    # ---- pass 1: identical normalized text --------------------------------
    # Same block_id first, then nearest position, so repeated short paragraphs
    # pair up sensibly.
    by_hash_new: dict[str, list[int]] = defaultdict(list)
    for ni, pb in enumerate(news):
        by_hash_new[pb.block.content_hash].append(ni)
    exact_pairs = []
    for oi, pb in enumerate(olds):
        for ni in by_hash_new.get(pb.block.content_hash, []):
            same_id = pb.block.block_id == news[ni].block.block_id
            exact_pairs.append((1.0, (0 if same_id else 1, abs(oi - ni)), oi, ni))
    for oi, ni, _ in _greedy(exact_pairs, 1.0):
        matches.append(BlockMatch(MatchStatus.UNCHANGED, olds[oi], news[ni], 1.0))
        old_left.discard(oi)
        new_left.discard(ni)

    # ---- section alignment -------------------------------------------------
    old_path = _section_paths(old)
    new_path = _section_paths(new)
    new_paths = set(new_path.values())
    section_map: dict[tuple[str, ...], tuple[str, ...]] = {
        p: p for p in set(old_path.values()) if p in new_paths
    }
    if cfg.align_renamed_sections:
        votes: dict[tuple[str, ...], Counter] = defaultdict(Counter)
        for m in matches:
            votes[old_path[m.old.section_id]][new_path[m.new.section_id]] += 1
        claimed = set(section_map.values())
        for op, counter in sorted(votes.items()):
            if op in section_map:
                continue
            target, n = counter.most_common(1)[0]
            if target not in claimed and n * 2 > sum(counter.values()):
                section_map[op] = target
                claimed.add(target)

    # Blocks in exact-only sections (e.g. footnote lists) stop after pass 1.
    old_fuzzy = {i for i in old_left if _fuzzy(olds[i])}
    new_fuzzy = {i for i in new_left if _fuzzy(news[i])}

    # ---- pass 2: similar text within the same (aligned) section -------------
    old_norm = {i: norm.normalize(olds[i].block.text) for i in old_fuzzy}
    new_norm = {i: norm.normalize(news[i].block.text) for i in new_fuzzy}
    new_by_path: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for ni in new_fuzzy:
        new_by_path[new_path[news[ni].section_id]].append(ni)
    edit_pairs = []
    for oi in old_fuzzy:
        target = section_map.get(old_path[olds[oi].section_id])
        if target is None:
            continue
        for ni in new_by_path.get(target, []):
            score = similarity(old_norm[oi], new_norm[ni])
            edit_pairs.append((score, abs(olds[oi].block.order - news[ni].block.order), oi, ni))
    for oi, ni, score in _greedy(edit_pairs, cfg.edit_similarity_threshold):
        matches.append(BlockMatch(MatchStatus.EDITED, olds[oi], news[ni], score))
        old_left.discard(oi)
        new_left.discard(ni)
        old_fuzzy.discard(oi)
        new_fuzzy.discard(ni)

    # ---- pass 2b: very similar text in a different section ------------------
    # Catches a paragraph that moved to another section AND was edited. It needs
    # a higher threshold because any section of the document is allowed.
    if cfg.cross_section_edit_threshold is not None:
        cross_pairs = [
            (similarity(old_norm[oi], new_norm[ni]),
             abs(olds[oi].block.order - news[ni].block.order), oi, ni)
            for oi in old_fuzzy for ni in new_fuzzy
        ]
        for oi, ni, score in _greedy(cross_pairs, cfg.cross_section_edit_threshold):
            matches.append(BlockMatch(MatchStatus.EDITED, olds[oi], news[ni], score))
            old_left.discard(oi)
            new_left.discard(ni)

    # ---- leftovers ---------------------------------------------------------
    matches += [BlockMatch(MatchStatus.REMOVED, olds[i], None) for i in sorted(old_left)]
    matches += [BlockMatch(MatchStatus.ADDED, None, news[i]) for i in sorted(new_left)]
    return matches


@dataclass(frozen=True)
class DocumentDiff:
    doc_key: str
    old: ParsedDocument | None  # None for a brand-new document
    new: ParsedDocument
    matches: list[BlockMatch]


def diff_event(
    old_versions: dict[str, ParsedDocument],
    uploaded: list[ParsedDocument],
    cfg: DiffSettings,
    norm: Normalizer,
) -> list[DocumentDiff]:
    """Diff every uploaded file against its previous version, then look for blocks
    that moved between documents of the same upload event."""
    results: list[DocumentDiff] = []
    for new in uploaded:
        old = old_versions.get(new.document.doc_key)
        if old is None:
            matches = [BlockMatch(MatchStatus.ADDED, None, pb) for pb in new.blocks]
        else:
            matches = diff_versions(old, new, cfg, norm)
        results.append(DocumentDiff(new.document.doc_key, old, new, matches))

    if cfg.detect_cross_document_moves and len(results) > 1:
        _detect_moves(results, cfg, norm)
    return results


def _windows(results: list[DocumentDiff], added: list, size: int) -> list[tuple[int, tuple[int, ...]]]:
    """Runs of 1..size added blocks that stand next to each other in their new
    document: (id of the document diff, indexes into ``added``)."""
    pos = {pb.block.block_uid: k for d in results for k, pb in enumerate(d.new.blocks)}
    by_doc: dict[int, list[int]] = defaultdict(list)
    for ai, (ad, _, am) in enumerate(added):
        by_doc[id(ad)].append(ai)
    out = []
    for did, ais in by_doc.items():
        ais.sort(key=lambda a: pos[added[a][2].new.block.block_uid])
        for s, first in enumerate(ais):
            run = [first]
            out.append((did, tuple(run)))
            for nxt in ais[s + 1: s + size]:
                if pos[added[nxt][2].new.block.block_uid] != \
                        pos[added[run[-1]][2].new.block.block_uid] + 1:
                    break
                run.append(nxt)
                out.append((did, tuple(run)))
    return out


def _detect_moves(results: list[DocumentDiff], cfg: DiffSettings, norm: Normalizer) -> None:
    """Pass 3: pair removed blocks with added blocks of *other* documents.

    A moved paragraph is often split on the way (the E3 -> E2 severance paragraph
    became three blocks: 0.40-0.49 against each, 0.76 against the three joined).
    So a removed block is compared with runs of up to ``diff.split_window``
    consecutive added blocks; the best run at or above the move threshold wins,
    each block used once, smaller runs first on ties."""
    removed = [(d, i, m) for d in results for i, m in enumerate(d.matches)
               if m.status == MatchStatus.REMOVED and _fuzzy(m.old)]
    added = [(d, i, m) for d in results for i, m in enumerate(d.matches)
             if m.status == MatchStatus.ADDED and _fuzzy(m.new)]
    windows = _windows(results, added, max(1, cfg.split_window))
    text = {ai: norm.normalize(am.new.block.text) for ai, (_, _, am) in enumerate(added)}
    candidates = []
    for ri, (rd, _, rm) in enumerate(removed):
        r_text = norm.normalize(rm.old.block.text)
        for did, run in windows:
            if did == id(rd):
                continue
            if len(run) == 1 and rm.old.block.content_hash == added[run[0]][2].new.block.content_hash:
                score = 1.0
            else:
                score = similarity(r_text, " ".join(text[a] for a in run))
            if score >= cfg.move_similarity_threshold:
                candidates.append((score, len(run), ri, run))
    used_r: set[int] = set()
    used_a: set[int] = set()
    replace: dict[int, dict[int, BlockMatch | None]] = defaultdict(dict)
    for score, _, ri, run in sorted(candidates, key=lambda c: (-c[0], c[1], c[2], c[3])):
        if ri in used_r or used_a.intersection(run):
            continue
        used_r.add(ri)
        used_a.update(run)
        rd, r_idx, rm = removed[ri]
        ad, a_idx, am = added[run[0]]
        # The moved pair is recorded once, on the document it moved *to*.
        replace[id(ad)][a_idx] = BlockMatch(MatchStatus.MOVED, rm.old, am.new, score,
                                            tuple(added[a][2].new for a in run[1:]))
        for a in run[1:]:
            replace[id(added[a][0])][added[a][1]] = None
        replace[id(rd)][r_idx] = None
    for d in results:
        changes = replace.get(id(d))
        if not changes:
            continue
        new_list = []
        for i, m in enumerate(d.matches):
            if i in changes:
                if changes[i] is not None:
                    new_list.append(changes[i])
            else:
                new_list.append(m)
        d.matches[:] = new_list


# ---------------------------------------------------------------- review sheet
#
# One row per match a person should check. Rows with identical text at the same
# position are left out: their text is identical by construction (same hash) and
# their position did not change, so there is nothing to judge.

REVIEW_COLUMNS = [
    "row_id", "event", "doc_key", "status", "role", "similarity",
    "old_file", "old_block_id", "old_lines", "new_file", "new_block_id", "new_lines",
    "old_text", "new_text", "closest_other_block_id", "closest_other_similarity",
    # filled in by the person:
    "verdict", "correct_partner_block_id", "note",
]
VERDICT_HELP = (
    "verdict: 'correct' if the status and pairing are right, 'wrong' otherwise. "
    "If wrong, put the block it should be paired with in correct_partner_block_id "
    "(or leave it empty if it really has no partner)."
)


def review_rows(event: str, results: list[DocumentDiff], norm: Normalizer) -> list[dict]:
    removed = [m.old for d in results for m in d.matches if m.status == MatchStatus.REMOVED]
    added = [m.new for d in results for m in d.matches if m.status == MatchStatus.ADDED]

    def closest(pb: ParsedBlock, pool: list[ParsedBlock]) -> tuple[str, str]:
        if not pool:
            return "", ""
        text = norm.normalize(pb.block.text)
        score, other = max(((similarity(text, norm.normalize(o.block.text)), o) for o in pool),
                           key=lambda x: x[0])
        return other.block.block_id, f"{score:.3f}"

    rows = []
    for d in results:
        old_file = d.old.version.source_file if d.old else ""
        for m in d.matches:
            if m.status == MatchStatus.UNCHANGED and m.same_position:
                continue
            other_id, other_score = "", ""
            if m.status == MatchStatus.REMOVED:
                other_id, other_score = closest(m.old, added)
            elif m.status == MatchStatus.ADDED:
                other_id, other_score = closest(m.new, removed)
            source_old = old_file
            if m.status == MatchStatus.MOVED:
                source_old = next((x.old.version.source_file for x in results
                                   if x.old and x.doc_key == m.old.block.doc_key), "")
            rows.append({
                "row_id": f"{event}-{len(rows) + 1:04d}",
                "event": event,
                "doc_key": d.doc_key,
                "status": m.status.value,
                "role": ("footnote" if any(pb is not None and not _fuzzy(pb)
                                           for pb in (m.old, m.new)) else "body"),
                "similarity": "" if m.similarity is None else f"{m.similarity:.3f}",
                "old_file": source_old if m.old else "",
                "old_block_id": m.old.block.block_id if m.old else "",
                "old_lines": f"{m.old.block.lines.start}-{m.old.block.lines.end}" if m.old else "",
                "new_file": d.new.version.source_file if m.new else "",
                "new_block_id": "; ".join(pb.block.block_id for pb in m.new_blocks),
                "new_lines": "; ".join(f"{pb.block.lines.start}-{pb.block.lines.end}"
                                       for pb in m.new_blocks),
                "old_text": m.old.block.text if m.old else "",
                "new_text": "\n\n".join(pb.block.text for pb in m.new_blocks),
                "closest_other_block_id": other_id,
                "closest_other_similarity": other_score,
                "verdict": "",
                "correct_partner_block_id": "",
                "note": "",
            })
    return rows
