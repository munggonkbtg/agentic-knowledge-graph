"""Precision and recall of layer 1 REFERENCES against the person's blind labels.

Reads data/labels/m3_references_sample.csv (the `citations` column) and the key
file, runs layer 1 on the same blocks, and compares per block:

* exact:    (document, cited section) pairs must match
* document: only the cited document must match (section ignored)

A citation counts once per block, as layer 1 writes one edge per
(block, document, section). Sections are compared in compact form (spaces
removed, Thai digits -> Arabic), so "มาตรา ๑๑๘ (๖)" equals "มาตรา 118(6)".

Reported overall, per language, per stratum, and precision per layer-1
resolution (explicit, same_block_context, issued_under, ...). Writes counts and
row ids only (no document text) to eval/results/m3_references_agreement.md.
Targets from the brief: precision >= 0.9, recall >= 0.8.

Run:  uv run python eval/references_agreement.py
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from kg.layer1_references import Registry, compact, law_name_from_title, slug

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "labels"

Citation = tuple[str, str]  # (doc_key, compact section; "" = whole document)


def norm_section(section: str) -> str:
    s = compact(section.strip())[0]
    return s.lower() if s.startswith("#") else s


def resolve_doc(text: str, own: str, registry: Registry) -> str:
    t = text.strip()
    if t.lower() == "self":
        return own
    if t.lower().startswith("ext:"):
        name = t[4:].strip()
        if name.startswith(("http://", "https://")):
            path = urlparse(name).path
            if path.lower().endswith(".md"):
                base = PurePosixPath(path).name.lower()
                return registry.by_file.get(base) or "ext-" + slug(compact(f"handbook/{base}")[0])
            return "ext-url-" + hashlib.sha1(name.split("#", 1)[0].encode()).hexdigest()[:10]
        c = compact(law_name_from_title(name))[0]
        return registry.by_name.get(c) or "ext-" + slug(c)
    if t in registry.entries:
        return t
    raise ValueError(f"unknown document {t!r} (use a doc_key, 'self' or 'ext: <name>')")


def parse_citations(cell: str, own: str, registry: Registry) -> set[Citation] | None:
    """None if the row is not labelled yet; an empty set for 'none'."""
    cell = cell.strip()
    if not cell:
        return None
    if cell.lower() == "none":
        return set()
    out = set()
    for item in cell.split(";"):
        if not item.strip():
            continue
        doc, _, section = item.partition("|")
        out.add((resolve_doc(doc, own, registry), norm_section(section)))
    return out


def _new() -> dict[str, int]:
    return {"blocks": 0, "tp": 0, "fp": 0, "fn": 0, "doc_tp": 0, "doc_fp": 0, "doc_fn": 0}


def score(rows: list[dict], key: dict, registry: Registry,
          system: dict[str, list[tuple[str, str, str]]]) -> dict:
    """system: block_uid -> [(doc_key, cited_section, resolution)]."""
    groups: dict[str, dict[str, int]] = defaultdict(_new)
    by_resolution: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0})
    disagreements, errors, unlabelled = [], [], 0
    for row in rows:
        info = key["rows"][row["row_id"]]
        try:
            person = parse_citations(row["citations"], info["doc_key"], registry)
        except ValueError as e:
            errors.append(f"{row['row_id']}: {e}")
            continue
        if person is None:
            unlabelled += 1
            continue
        sys_items = system.get(info["block_uid"], [])
        sys_set = {(d, norm_section(s)) for d, s, _ in sys_items}
        tp, fp, fn = sys_set & person, sys_set - person, person - sys_set
        sys_docs, person_docs = {d for d, _ in sys_set}, {d for d, _ in person}
        for g in ("all", info["language"], info["stratum"]):
            c = groups[g]
            c["blocks"] += 1
            c["tp"] += len(tp)
            c["fp"] += len(fp)
            c["fn"] += len(fn)
            c["doc_tp"] += len(sys_docs & person_docs)
            c["doc_fp"] += len(sys_docs - person_docs)
            c["doc_fn"] += len(person_docs - sys_docs)
        for d, s, res in sys_items:
            by_resolution[res]["tp" if (d, norm_section(s)) in person else "fp"] += 1
        if fp or fn:
            disagreements.append({"row_id": row["row_id"], "system_only": len(fp),
                                  "person_only": len(fn)})
    return {"groups": dict(groups), "by_resolution": dict(by_resolution),
            "disagreements": disagreements, "errors": errors, "unlabelled": unlabelled}


def _ratio(a: int, b: int) -> str:
    return f"{a / b:.2f}" if b else "-"


def render(s: dict) -> str:
    out = ["# M3: REFERENCES vs the person's blind labels", "",
           "Targets (brief): precision >= 0.9, recall >= 0.8.", "",
           "| group | blocks | precision | recall | document precision | document recall |",
           "|---|---|---|---|---|---|"]
    for g, c in sorted(s["groups"].items(), key=lambda kv: (kv[0] != "all", kv[0])):
        out.append(f"| {g} | {c['blocks']} | {_ratio(c['tp'], c['tp'] + c['fp'])} "
                   f"| {_ratio(c['tp'], c['tp'] + c['fn'])} "
                   f"| {_ratio(c['doc_tp'], c['doc_tp'] + c['doc_fp'])} "
                   f"| {_ratio(c['doc_tp'], c['doc_tp'] + c['doc_fn'])} |")
    out += ["", "## Precision by how layer 1 resolved the target", "",
            "| resolution | edges | correct | precision |", "|---|---|---|---|"]
    for res, c in sorted(s["by_resolution"].items()):
        out.append(f"| {res} | {c['tp'] + c['fp']} | {c['tp']} | {_ratio(c['tp'], c['tp'] + c['fp'])} |")
    out.append(f"\nUnlabelled rows: {s['unlabelled']}.")
    if s["errors"]:
        out += ["", "## Rows that could not be read", ""] + [f"- {e}" for e in s["errors"]]
    if s["disagreements"]:
        out += ["", "## Rows where layer 1 and the person differ", "",
                "| row | only layer 1 | only the person |", "|---|---|---|"]
        out += [f"| {d['row_id']} | {d['system_only']} | {d['person_only']} |"
                for d in s["disagreements"]]
    return "\n".join(out)


def system_references(registry: Registry) -> dict[str, list[tuple[str, str, str]]]:
    """Run layer 1 on the initial corpus, exactly as `kg build --layer 1` does."""
    from kg.config import load_config
    from kg.layer0_structure import parse_corpus
    from kg.layer1_references import ReferenceExtractor

    cfg = load_config(ROOT / "config.yaml")
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    extractor = ReferenceExtractor(registry, cfg.layer1)
    out: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for doc in parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, t0):
        for r in extractor.extract(doc).references:
            out[r.block_uid].append((r.target, r.cited_section, r.resolution))
    return out


def registry_from_corpus() -> Registry:
    """Same entries as Store.registry_entries() builds from the graph."""
    from kg.config import load_config
    from kg.layer0_structure import parse_corpus
    from kg.layer1_references import RegistryEntry, load_extra_aliases

    cfg = load_config(ROOT / "config.yaml")
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    entries = []
    for d in parse_corpus(ROOT / "data" / "initial_corpus", cfg.layer0, t0):
        names = {PurePosixPath(d.version.source_url).name} if d.version.source_url else set()
        names.add(d.version.source_file)
        entries.append(RegistryEntry(d.document.doc_key, d.document.title,
                                     d.document.language.value, tuple(sorted(names))))
    return Registry(entries, load_extra_aliases(ROOT / cfg.layer1.aliases_file))


def main() -> None:
    key = json.loads((LABELS / "m3_references_key.json").read_text(encoding="utf-8"))
    with (LABELS / "m3_references_sample.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    registry = registry_from_corpus()
    text = render(score(rows, key, registry, system_references(registry)))
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / "m3_references_agreement.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
