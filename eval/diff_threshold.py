"""How does the diff change with the edit-similarity threshold?

For each of the 3 upload events, run the diff at several thresholds and count
unchanged / edited / moved / removed / added blocks. It also prints the
similarity scores of the pairs that sit near the boundary, so a person can see
which pairs a threshold would accept or reject.

This shows *what changes* with the threshold, not which value is *right*: that
needs the person's check (data/labels/m2_diff_review.csv).

Run:  uv run python eval/diff_threshold.py
Writes counts and scores only (no document text) to eval/results/m2_diff_threshold.md.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from kg.config import load_config
from kg.diff import MatchStatus, diff_event
from kg.layer0_structure import Normalizer, parse_corpus

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
THRESHOLDS = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
STATUSES = [s for s in MatchStatus]


def main() -> None:
    cfg = load_config(ROOT / "config.yaml")
    norm = Normalizer(cfg.layer0)
    olds = {d.document.doc_key: d
            for d in parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, T0)}
    events = {ev: parse_corpus(ROOT / "data" / "uploads" / ev, cfg.layer0, T0)
              for ev in ("event1", "event2", "event3")}

    out = ["# M2: diff results by edit-similarity threshold", "",
           "Block counts per upload event. Not yet checked by a person.",
           f"Pass 2b (any section of the same document) stays at "
           f"{cfg.diff.cross_section_edit_threshold}, so same-section thresholds above that "
           "value change little.", "",
           "| event | threshold | " + " | ".join(s.value for s in STATUSES) + " |",
           "|---|---|" + "---|" * len(STATUSES)]
    for ev, uploaded in events.items():
        for t in THRESHOLDS:
            dcfg = cfg.diff.model_copy(update={"edit_similarity_threshold": t})
            c = Counter(m.status for d in diff_event(olds, uploaded, dcfg, norm)
                        for m in d.matches)
            out.append(f"| {ev} | {t:.1f} | " + " | ".join(str(c[s]) for s in STATUSES) + " |")

    # Scores of every edited / moved pair at the lowest threshold.
    low = cfg.diff.model_copy(update={"edit_similarity_threshold": min(THRESHOLDS)})
    out += ["", f"## Edited and moved pairs at threshold {min(THRESHOLDS)}, lowest score first",
            "", "| event | status | similarity | old block | new block |", "|---|---|---|---|---|"]
    for ev, uploaded in events.items():
        pairs = [m for d in diff_event(olds, uploaded, low, norm) for m in d.matches
                 if m.status in (MatchStatus.EDITED, MatchStatus.MOVED)]
        for m in sorted(pairs, key=lambda m: m.similarity)[:15]:
            out.append(f"| {ev} | {m.status.value} | {m.similarity:.2f} | "
                       f"`{m.old.block.block_id}` | `{m.new.block.block_id}` |")
    text = "\n".join(out)
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / "m2_diff_threshold.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
