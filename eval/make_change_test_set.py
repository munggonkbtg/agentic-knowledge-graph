"""Change test set for M5 (brief section 9): which existing blocks truly need
revision after each upload event. Built BEFORE `kg upload` and before any impact
analysis runs, so the labels cannot come from the system's own output.

Change items (what an upload changed) come from the diff (M2, verified): blocks
edited, removed or moved, and blocks added inside a document that already
existed. Brand-new documents (E2, T2) are not change items. Sample of 40:
  event1 15 (always including the sabbatical edit named in the brief),
  event2 all 13 (including the E3 -> E2 severance move),
  event3 12.

Candidates (existing blocks a person judges) are pooled per event from several
methods, then shuffled; the person never sees which method found a block:
  * char3   - character-trigram TF-IDF similarity to the change (top 3 per change)
  * cite    - blocks that write the changed section's number ("มาตรา 34") (up to 5)
  * graph   - layer 1 REFERENCES to the changed document / section (up to 5)
  * random  - 15 other blocks per event, to estimate what the pool misses
Plus the person may add any block from the catalogue (additions sheet).
Note for reporting: "graph" uses layer 1, which is part of the system under test.

The experiment runs forward in time: the store for event 2 already holds the
event 1 uploads, and so on.

Files written to data/labels/ (not in git):
* m5_changes.csv          the 40 change items: C-id, old text, new text
* m5_candidates.csv       blocks to judge. Fill in:
     needs_revision  yes | no | unsure
     kind            states | cites | depends   (only when yes / unsure)
                     states  = repeats the changed fact
                     cites   = refers to the changed document or section
                     depends = relies on the fact without stating or citing it
     change_ids      the C-ids that make it need revision, ";"-separated
     note            optional
* m5_store_blocks.csv     every existing block per event (ref S-…), to add blocks
* m5_additions.csv        blocks the pool missed: event, store_ref, kind, change_ids, note
* m5_key.json             seeds, sampled changes, pool sources per candidate

Run:  uv run python eval/make_change_test_set.py
"""

from __future__ import annotations

import csv
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from kg.config import load_config
from kg.diff import MatchStatus, diff_event
from kg.layer0_structure import Normalizer, ParsedDocument, parse_corpus
from kg.layer1_references import Registry, RegistryEntry, ReferenceExtractor, compact

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels"
EVENTS = ("event1", "event2", "event3")
PER_EVENT = {"event1": 15, "event2": None, "event3": 12}  # None = all
MUST_INCLUDE = {  # cases the brief names
    "event1": ["en-benefits-and-perks::Paid Time Off > Sabbatical::b0"],
    "event2": ["en-making-a-career::Performance Improvement Plans::b1"],
}
SEED = 20261127
TOP_CHAR3, TOP_CITE, TOP_GRAPH, RANDOM_PER_EVENT = 3, 5, 5, 15
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
CHANGE_STATUSES = (MatchStatus.EDITED, MatchStatus.REMOVED, MatchStatus.MOVED, MatchStatus.ADDED)


# ---------------------------------------------------------------- pooling helpers


def trigrams(text: str) -> Counter:
    c = compact(text)[0].lower()
    return Counter(c[i:i + 3] for i in range(max(0, len(c) - 2)))


class Char3Index:
    """TF-IDF over character trigrams (works for Thai without word splitting)."""

    def __init__(self, texts: dict[str, str]) -> None:
        self.tf = {k: trigrams(v) for k, v in texts.items()}
        df = Counter(g for tf in self.tf.values() for g in tf)
        n = len(self.tf)
        self.idf = {g: math.log((1 + n) / (1 + d)) + 1 for g, d in df.items()}
        self.vec = {k: self._weigh(tf) for k, tf in self.tf.items()}

    def _weigh(self, tf: Counter) -> dict[str, float]:
        v = {g: c * self.idf.get(g, 1.0) for g, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {g: x / norm for g, x in v.items()}

    def top(self, text: str, k: int, exclude: set[str]) -> list[str]:
        q = self._weigh(trigrams(text))
        scores = [(sum(w * vec.get(g, 0.0) for g, w in q.items()), key)
                  for key, vec in self.vec.items() if key not in exclude]
        return [key for s, key in sorted(scores, key=lambda x: (-x[0], x[1]))[:k] if s > 0]


def cited_section(block_id: str) -> str | None:
    """'…::หมวด 2 … > มาตรา 34::b0' -> 'มาตรา34' (compact), else None."""
    last = block_id.split("::")[1].split(" > ")[-1]
    m = re.fullmatch(r"(มาตรา|ข้อ)\s*(\d+(?:/\d+)?)", last)
    return f"{m.group(1)}{m.group(2)}" if m else None


def anchor_of(block_id: str) -> str | None:
    """English heading -> the #anchor a link to it uses ('Your First 90 Days' ->
    '#your-first-90-days'), the way GitHub builds heading anchors."""
    path = block_id.split("::")[1]
    if path == "_":
        return None
    heading = path.split(" > ")[-1].lower()
    # every space becomes "-" (GitHub keeps "--" where punctuation was removed)
    return "#" + re.sub(r"[^\w\s-]", "", heading).strip().replace(" ", "-")


def cites_section(text: str, section: str) -> bool:
    return re.search(re.escape(section) + r"(?![\d/])", compact(text)[0]) is not None


# ---------------------------------------------------------------- main


def registry_for(docs: dict[str, ParsedDocument]) -> Registry:
    entries = []
    for d in docs.values():
        names = {PurePosixPath(d.version.source_url).name} if d.version.source_url else set()
        names.add(d.version.source_file)
        entries.append(RegistryEntry(d.document.doc_key, d.document.title,
                                     d.document.language.value, tuple(sorted(names))))
    return Registry(entries)


def pool_candidates(store: dict[str, ParsedDocument], changed_old: set[str], changes: list,
                    cfg, rng: random.Random, random_n: int = RANDOM_PER_EVENT):
    """Existing body blocks of ``store`` (minus the changed ones) and, for the
    pooled ones, the methods that found them: char3, cite, graph, random."""
    cands = {pb.block.block_uid: (doc, pb) for doc in store.values() for pb in doc.blocks
             if pb.block.role.value == "body" and pb.block.block_uid not in changed_old}
    index = Char3Index({u: pb.block.text for u, (_, pb) in cands.items()})
    refs = defaultdict(list)  # target doc -> [(block_uid, compact section)]
    extractor = ReferenceExtractor(registry_for(store), cfg.layer1)
    for doc in store.values():
        for r in extractor.extract(doc).references:
            refs[r.target].append((r.block_uid, compact(r.cited_section)[0]))

    sources: dict[str, set[str]] = defaultdict(set)
    for m in changes:
        ref = m.old or m.new
        text = (m.old.block.text if m.old else "") + "\n" + "\n".join(
            pb.block.text for pb in m.new_blocks)
        for u in index.top(text, TOP_CHAR3, exclude=set()):
            sources[u].add("char3")
        section = cited_section(ref.block.block_id)
        if section:
            hits = [u for u, (_, pb) in cands.items() if cites_section(pb.block.text, section)]
            for u in sorted(hits)[:TOP_CITE] if len(hits) <= TOP_CITE else \
                    rng.sample(sorted(hits), TOP_CITE):
                sources[u].add("cite")
        anchor = anchor_of(ref.block.block_id)
        wanted = {"", section or "", (anchor or "").lower()}
        graph = [u for u, s in refs.get(ref.block.doc_key, [])
                 if u in cands and s.lower() in wanted]
        graph = sorted(set(graph))
        for u in graph if len(graph) <= TOP_GRAPH else rng.sample(graph, TOP_GRAPH):
            sources[u].add("graph")
    others = sorted(u for u in cands if u not in sources)
    for u in rng.sample(others, min(random_n, len(others))):
        sources[u].add("random")
    return cands, sources


def store_after_events(cfg) -> dict[str, ParsedDocument]:
    """The store after all real upload events (each upload replaces or adds a doc)."""
    store = {d.document.doc_key: d for d in parse_corpus(ROOT / "data" / "initial_corpus",
                                                         cfg.layer0, T0)}
    for ev in EVENTS:
        for d in parse_corpus(ROOT / "data" / "uploads" / ev, cfg.layer0, T0):
            store[d.document.doc_key] = d
    return store


def main() -> None:
    outputs = {n: LABELS / f"m5_{n}" for n in ("changes.csv", "candidates.csv",
                                               "store_blocks.csv", "additions.csv", "key.json")}
    for p in outputs.values():
        if p.exists():
            raise SystemExit(f"{p} exists (it may hold labels); not overwriting")
    cfg = load_config(ROOT / "config.yaml")
    norm = Normalizer(cfg.layer0)
    rng = random.Random(SEED)
    store = {d.document.doc_key: d for d in parse_corpus(ROOT / "data" / "initial_corpus",
                                                         cfg.layer0, T0)}
    changes_rows, cand_rows, store_rows = [], [], []
    key: dict = {"seed": SEED, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "changes": {}, "candidates": {}, "store_refs": {},
                 "note": "pool sources include 'graph' (layer 1, part of the system under test)"}
    cid_n = 0
    for ev in EVENTS:
        uploaded = parse_corpus(ROOT / "data" / "uploads" / ev, cfg.layer0, T0)
        results = diff_event(store, uploaded, cfg.diff, norm)

        # -- change items ---------------------------------------------------
        items = []
        for d in results:
            for m in d.matches:
                if m.status not in CHANGE_STATUSES:
                    continue
                pb = m.old or m.new
                if pb.block.role.value != "body":
                    continue
                if m.status == MatchStatus.ADDED and d.old is None:
                    continue  # a brand-new document is not an update
                items.append(m)
        must = [m for m in items if m.old and m.old.block.block_id in MUST_INCLUDE.get(ev, [])]
        rest = [m for m in items if m not in must]
        k = PER_EVENT[ev]
        chosen = must + (rest if k is None else rng.sample(rest, max(0, k - len(must))))
        ev_changes = []
        for m in chosen:
            cid_n += 1
            cid = f"C{cid_n:02d}"
            new_text = "\n\n".join(pb.block.text for pb in m.new_blocks)
            ref = m.old or m.new
            changes_rows.append({
                "change_id": cid, "event": ev, "document": ref.block.doc_key,
                "change": m.status.value, "section": ref.block.block_id.split("::")[1],
                "old_text": m.old.block.text if m.old else "", "new_text": new_text})
            key["changes"][cid] = {"event": ev, "status": m.status.value,
                                   "old_block_uid": m.old.block.block_uid if m.old else None,
                                   "new_block_ids": [pb.block.block_id for pb in m.new_blocks],
                                   "must_include": m in must}
            ev_changes.append((cid, m))

        # -- candidates: existing blocks of the store before this event -----------
        changed_old = {m.old.block.block_uid for d in results for m in d.matches
                       if m.old and m.status != MatchStatus.UNCHANGED}
        cands, sources = pool_candidates(store, changed_old, [m for _, m in ev_changes],
                                         cfg, rng)

        pooled = sorted(sources)
        rng.shuffle(pooled)
        for i, u in enumerate(pooled, start=1):
            doc, pb = cands[u]
            rid = f"{ev}-B{i:03d}"
            cand_rows.append({
                "row_id": rid, "event": ev, "file": doc.version.source_file,
                "lines": f"{pb.block.lines.start}-{pb.block.lines.end}",
                "section": pb.block.block_id.split("::")[1], "block_text": pb.block.text,
                "needs_revision": "", "kind": "", "change_ids": "", "note": ""})
            key["candidates"][rid] = {"block_uid": u, "block_id": pb.block.block_id,
                                      "doc_key": pb.block.doc_key, "sources": sorted(sources[u])}
        for i, (u, (doc, pb)) in enumerate(sorted(cands.items(), key=lambda x: (
                x[1][1].block.doc_key, x[1][1].block.lines.start)), start=1):
            sref = f"{ev[0]}{ev[-1]}-S{i:03d}"
            store_rows.append({"ref": sref, "event": ev, "file": doc.version.source_file,
                               "lines": f"{pb.block.lines.start}-{pb.block.lines.end}",
                               "section": pb.block.block_id.split("::")[1],
                               "block_text": pb.block.text})
            key["store_refs"][sref] = {"block_uid": u, "block_id": pb.block.block_id}
        print(f"{ev}: {len(ev_changes)} changes, {len(cands)} existing blocks, "
              f"{len(pooled)} candidates "
              f"{dict(Counter(s for u in pooled for s in sources[u]))}")

        # -- the store moves forward in time ------------------------------------
        for d in uploaded:
            store[d.document.doc_key] = d

    LABELS.mkdir(parents=True, exist_ok=True)

    def write(path: Path, rows: list[dict], cols: list[str]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)

    write(outputs["changes.csv"], changes_rows,
          ["change_id", "event", "document", "change", "section", "old_text", "new_text"])
    write(outputs["candidates.csv"], cand_rows,
          ["row_id", "event", "file", "lines", "section", "block_text",
           "needs_revision", "kind", "change_ids", "note"])
    write(outputs["store_blocks.csv"], store_rows,
          ["ref", "event", "file", "lines", "section", "block_text"])
    write(outputs["additions.csv"], [], ["event", "store_ref", "kind", "change_ids", "note"])
    outputs["key.json"].write_text(json.dumps(key, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    print(f"{len(changes_rows)} change items, {len(cand_rows)} candidates to judge")


if __name__ == "__main__":
    main()
