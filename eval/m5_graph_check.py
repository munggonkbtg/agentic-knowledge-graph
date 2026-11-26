"""M5 step 2 check: `kg impact` on the stored graph vs the offline experiment.

Reads the latest `kg impact` report per upload event (data/reports/) and, for
every real change item C01-C40 with needs_review pairs (main, not historical),
finds the report's change on the same old block and measures recall@5/10/20 of
the labelled blocks in the reported top 20.

Differences from the offline experiment are expected and reported, not hidden:
* candidates are the CURRENT blocks after all three events (the experiment used
  the store just before each event): a labelled block that was itself edited
  later has a new node and cannot be found by its old uid;
* the graph holds the edges written by layers 1-2 on the current versions.

Label source: --labels ai | human. Writes eval/results/m5_graph_check_<source>.md.

Run:  uv run python eval/m5_graph_check.py
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from label_sources import DESCRIPTION
from m5_labels import by_change, positives

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels"
REPORTS = ROOT / "data" / "reports"
EVENT_DOCS = {"event1": "impact_en-benefits-and-perks_",
              "event2": "impact_en-severance_en-making-a-career_",
              "event3": "impact_th-labour-protection-act-2541_th-labour-protection-act-"
                        "amendment-7-2562_"}
KS = (5, 10, 20)


def latest(prefix: str) -> Path | None:
    files = sorted(REPORTS.glob(f"{prefix}*.csv"))
    return files[-1] if files else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="ai", choices=["ai", "human"])
    source = ap.parse_args().labels
    key = json.loads((LABELS / "m5_key.json").read_text(encoding="utf-8"))["changes"]
    pos = by_change(positives(source))  # main pairs only
    reports = {}
    for ev, prefix in EVENT_DOCS.items():
        path = latest(prefix)
        if path is None:
            raise SystemExit(f"no report for {ev}: run kg impact first")
        by_change_uid: dict[str, list[dict]] = defaultdict(list)
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                by_change_uid[r["changed_block_uid"]].append(r)
        reports[ev] = (path.name, by_change_uid)
    out = ["# M5 step 2: `kg impact` on the stored graph vs the offline experiment", "",
           f"**Label source: {source}** ({DESCRIPTION[source]}). Real change items "
           "C01-C40 only (the synthetic edits are not in the graph); main needs_review "
           "pairs, historical blocks left out.", "",
           "Reports: " + ", ".join(f"`{n}`" for n, _ in reports.values()), "",
           "| change | event | pairs | found in graph report | @5 | @10 | @20 |",
           "|---|---|---|---|---|---|---|"]
    tot = defaultdict(int)
    missing_change = []
    for cid in sorted(c for c in pos if c.startswith("C")):
        info = key[cid]
        name, rows = reports[info["event"]]
        listed = rows.get(info["old_block_uid"])
        pairs = pos[cid]
        tot["pairs"] += len(pairs)
        if not listed:
            missing_change.append(cid)
            out.append(f"| {cid} | {info['event']} | {len(pairs)} | change not in report | - | - | - |")
            continue
        rank = {r["block_uid"]: int(r["rank"]) for r in listed}
        hits = {k: sum(rank.get(p.block_uid, 99) <= k for p in pairs) for k in KS}
        for k in KS:
            tot[k] += hits[k]
        tot["found"] += len(pairs)
        out.append(f"| {cid} | {info['event']} | {len(pairs)} | yes | {hits[5]} | {hits[10]} "
                   f"| {hits[20]} |")
    n = tot["pairs"]
    out += ["", f"**All real pairs ({n}):** recall@5 {tot[5] / n:.2f}, @10 {tot[10] / n:.2f}, "
            f"@20 {tot[20] / n:.2f}. Offline experiment, graph-first, real set (15 pairs, "
            "store before each event): @5 0.80, @10 0.80, @20 1.00." if n else "No pairs.",
            "", f"Change items whose old block has no change in the reports: "
            f"{', '.join(missing_change) or 'none'}."]
    text = "\n".join(out)
    (ROOT / "eval" / "results" / f"m5_graph_check_{source}.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
