"""Early test #1: how stable are block IDs across the 3 real version pairs?

For every block in the OLD version, look it up in the NEW version:

* same_uid   – same position and same text: the node is reused as-is.
* moved      – same text, different position (heading renamed, paragraph inserted
               above, or moved to another document).
* edited     – same position, different text: a likely in-place edit.
* unmatched  – neither the text nor the position survives (removed, or edited
               and moved). M2's similarity pass will look at these.

This counts exact matches only. It says nothing yet about whether a match is
*correct*; that needs the person's check planned for M2.

Run:  uv run python eval/block_stability.py
Writes counts only (no document text) to eval/results/m1_block_stability.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from kg.config import Layer0Settings, load_config
from kg.layer0_structure import parse_file

ROOT = Path(__file__).resolve().parents[1]
INITIAL = ROOT / "data" / "initial_corpus"
UPLOADS = ROOT / "data" / "uploads"
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)

PAIRS = [
    ("E1", INITIAL / "E1_benefits_and_perks__2024-01-05_before_sabbatical_change.md",
     [UPLOADS / "event1" / "E1_benefits_and_perks.md"]),
    ("E3 (+E2)", INITIAL / "E3_making_a_career__2024-05-14_before_severance_move.md",
     [UPLOADS / "event2" / "E3_making_a_career.md", UPLOADS / "event2" / "E2_severance.md"]),
    ("T1", INITIAL / "T1_labour_protection_act_2541__2017-08-31.md",
     [UPLOADS / "event3" / "T1_labour_protection_act_2541.md"]),
]


def compare(old_path: Path, new_paths: list[Path], cfg: Layer0Settings) -> dict[str, int]:
    old = [pb.block for pb in parse_file(old_path, cfg, T0).blocks]
    new = [pb.block for p in new_paths for pb in parse_file(p, cfg, T0).blocks]
    new_uids = {b.block_uid for b in new}
    new_hashes = {b.content_hash for b in new}
    new_ids = {b.block_id for b in new}
    counts = {"old": len(old), "new": len(new), "same_uid": 0, "moved": 0, "edited": 0,
              "unmatched": 0}
    for b in old:
        if b.block_uid in new_uids:
            counts["same_uid"] += 1
        elif b.content_hash in new_hashes:
            counts["moved"] += 1
        elif b.block_id in new_ids:
            counts["edited"] += 1
        else:
            counts["unmatched"] += 1
    return counts


def main() -> None:
    base = load_config(ROOT / "config.yaml").layer0
    settings = {
        "configured (title out of path, markers stripped, digits unified)": base,
        "title heading kept in path": base.model_copy(update={"title_heading_in_path": True}),
        "no text normalization (markers and Thai digits kept)": base.model_copy(
            update={"strip_footnote_markers": False, "thai_digits_to_arabic": False}),
    }
    out = ["# M1: block ID stability on the 3 version pairs", "",
           "Counts of OLD blocks by what happens to them in the NEW version. "
           "Exact matching only; not yet checked by a person.", ""]
    for label, cfg in settings.items():
        out += [f"## {label}", "",
                "| pair | old blocks | new blocks | same uid | moved | edited in place "
                "| unmatched | text unchanged (uid+moved) |",
                "|---|---|---|---|---|---|---|---|"]
        for name, old, news in PAIRS:
            c = compare(old, news, cfg)
            unchanged = c["same_uid"] + c["moved"]
            out.append(
                f"| {name} | {c['old']} | {c['new']} | {c['same_uid']} | {c['moved']} | "
                f"{c['edited']} | {c['unmatched']} | {unchanged} ({unchanged / c['old']:.0%}) |"
            )
        out.append("")
    text = "\n".join(out)
    results = ROOT / "eval" / "results"
    results.mkdir(exist_ok=True)
    (results / "m1_block_stability.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
