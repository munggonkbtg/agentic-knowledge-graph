"""How well does document identification work without doc_key? (docs/plan.md, M3)

Every file is read with its doc_key ignored (front matter stripped in memory) and
identified against candidates parsed from data/ — no database needed.

* Initial corpus, leave-one-out: candidates = the other 7 initial documents.
  The right answer is "new" (its own document is not a candidate).
* Initial corpus, self: candidates = all 8. The right answer is its own key.
* Upload files, if data/uploads/ exists: candidates = the 8 initial documents.
  E1, E3, T1 must be matched to their document; E2 and T2 must be "new"
  (T2 amends T1 and looks like it by name and title; E2 holds a paragraph that
  moved out of E3).

Outcome per file: right / wrong / sent to a person. Writes counts and scores
(no document text) to eval/results/m3_identification.md.

Run:  uv run python eval/identify_eval.py
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from kg.config import load_config
from kg.identify import candidate_from, identify
from kg.layer0_structure import Normalizer, parse_file, read_front_matter

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def stripped_copy(src: Path, tmp: Path) -> Path:
    text = src.read_text(encoding="utf-8")
    body = text.split("---", 2)[2].lstrip("\n") if text.startswith("---") else text
    dst = tmp / src.name
    dst.write_text(body, encoding="utf-8")
    return dst


def outcome(ident, expected: str) -> str:
    if ident.needs_person:
        return "person"
    got = "new" if ident.method == "new" else ident.doc_key
    return "right" if got == expected else f"wrong ({got})"


def main() -> None:
    cfg = load_config(ROOT / "config.yaml")
    norm = Normalizer(cfg.layer0)
    initial = sorted((ROOT / "data" / "initial_corpus").glob("*.md"))
    uploads = sorted((ROOT / "data" / "uploads").glob("*/*.md"))
    parsed = {p: parse_file(p, cfg.layer0, T0) for p in initial}
    cand = {p: candidate_from(d, norm) for p, d in parsed.items()}
    initial_keys = {d.document.doc_key for d in parsed.values()}

    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for p in initial:
            f = stripped_copy(p, tmp)
            ident, _ = identify(f, [c for q, c in cand.items() if q != p], cfg, T0)
            rows.append(("initial, leave-one-out", p.name, "new", ident))
            ident, _ = identify(f, list(cand.values()), cfg, T0)
            rows.append(("initial, self", p.name, parsed[p].document.doc_key, ident))
        for p in uploads:
            key = str(read_front_matter(p)["doc_key"])
            expected = key if key in initial_keys else "new"
            ident, _ = identify(stripped_copy(p, tmp), list(cand.values()), cfg, T0)
            rows.append(("upload", p.name, expected, ident))

    out = ["# M3: document identification without doc_key", "",
           f"Thresholds: accept text >= {cfg.identify.accept_text_similarity} with margin "
           f">= {cfg.identify.accept_margin}; new below {cfg.identify.new_document_below}.",
           "Upload files present: " + ("yes" if uploads else "no (only the initial corpus "
                                         "was tested; the T2 / E2 cases need data/uploads)"),
           "", "| set | file | expected | outcome | best candidate (text / blocks / title / file) |",
           "|---|---|---|---|---|"]
    totals: dict[str, dict[str, int]] = {}
    for group, name, expected, ident in rows:
        res = outcome(ident, expected)
        t = totals.setdefault(group, {"right": 0, "wrong": 0, "person": 0})
        t["right" if res == "right" else "person" if res == "person" else "wrong"] += 1
        b = ident.ranked[0] if ident.ranked else None
        best = (f"{b.doc_key}: {b.text:.2f} / {b.blocks:.2f} / {b.title:.2f} / {b.file_name:.2f}"
                if b else "-")
        out.append(f"| {group} | {name} | {expected} | {res} | {best} |")
    out += ["", "| set | right | wrong | sent to a person |", "|---|---|---|---|"]
    out += [f"| {g} | {t['right']} | {t['wrong']} | {t['person']} |" for g, t in totals.items()]
    text = "\n".join(out)
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / "m3_identification.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
