"""Document identification (pipeline steps 1 and 8; plan in docs/plan.md, M3).

Which logical document is a file a version of?

1. ``doc_key`` in the front matter and known in the graph -> that document
   (method ``registry``).
2. ``doc_key`` given but unknown -> a new document, listed for a person to
   confirm (it may be a typo of an existing key). Method ``front_matter``.
3. No ``doc_key`` -> score every current version in the graph:
   * text similarity of the whole document (primary),
   * share of the file's blocks whose exact text the candidate has,
   * title and file-name similarity (tie-breakers only).
   Then:
   * best text >= accept_text_similarity and >= accept_margin above the second
     -> that document (method ``content``);
   * best text < new_document_below -> a new document, listed for confirmation
     (method ``new``);
   * otherwise -> **ask a person** (the file is not uploaded yet).
4. A person's answer in the queue file (matched by the file's hash) wins:
   method ``human``.

Why text first: on the pilot, the amending act T2 looks like T1 by file name
(0.74) and title (0.67) but not by text (0.34). Trusting names would file it as
a new version of the act it amends.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

from kg.config import AppConfig
from kg.layer0_structure import Normalizer, ParsedDocument, parse_file, read_front_matter

PROVISIONAL_KEY = "unidentified"


@dataclass(frozen=True)
class Candidate:
    """A document already in the graph (its current version)."""

    doc_key: str
    title: str
    source_file: str
    text: str  # normalized text of the current version, in document order
    block_hashes: frozenset[str]


@dataclass(frozen=True)
class Scores:
    doc_key: str
    text: float
    blocks: float
    title: float
    file_name: float

    def rank_key(self) -> tuple[float, float, float, float]:
        return (self.text, self.blocks, self.title, self.file_name)


@dataclass(frozen=True)
class Identification:
    file: str
    file_hash: str
    doc_key: str | None  # None while a person has to decide
    method: str  # registry | front_matter | content | new | human
    confidence: float
    needs_person: bool = False  # not uploaded until answered
    confirm_later: bool = False  # uploaded, but a person should confirm
    reason: str = ""
    ranked: tuple[Scores, ...] = field(default_factory=tuple)

    def provenance(self) -> dict[str, object]:
        """Flat properties for the HAS_VERSION relationship."""
        top = self.ranked[0] if self.ranked else None
        props: dict[str, object] = {"method": self.method, "confidence": self.confidence,
                                    "identification_reason": self.reason}
        if top is not None:
            props.update(id_text_similarity=round(top.text, 4),
                         id_block_overlap=round(top.blocks, 4),
                         id_title_similarity=round(top.title, 4),
                         id_file_name_similarity=round(top.file_name, 4))
        return props


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def name_stem(file_name: str) -> str:
    """File name without extension, lower case, separators as spaces."""
    return re.sub(r"[_\-\s.]+", " ", Path(file_name).stem.lower()).strip()


def document_text(doc: ParsedDocument, norm: Normalizer) -> str:
    return " ".join(norm.normalize(pb.block.text) for pb in doc.blocks)


def candidate_from(doc: ParsedDocument, norm: Normalizer) -> Candidate:
    return Candidate(doc.document.doc_key, doc.document.title, doc.version.source_file,
                     document_text(doc, norm),
                     frozenset(pb.block.content_hash for pb in doc.blocks))


def score(doc: ParsedDocument, cand: Candidate, norm: Normalizer, compare_chars: int) -> Scores:
    hashes = {pb.block.content_hash for pb in doc.blocks}
    return Scores(
        doc_key=cand.doc_key,
        text=fuzz.ratio(document_text(doc, norm)[:compare_chars],
                        cand.text[:compare_chars]) / 100,
        blocks=len(hashes & cand.block_hashes) / max(1, len(hashes)),
        title=fuzz.ratio(norm.normalize(doc.document.title), norm.normalize(cand.title)) / 100,
        file_name=fuzz.ratio(name_stem(doc.version.source_file), name_stem(cand.source_file)) / 100,
    )


def new_doc_key(path: Path) -> str:
    """Key for a new document without a doc_key: from the file name."""
    key = re.sub(r"[^\w]+", "-", path.stem.lower(), flags=re.UNICODE).strip("-")
    return f"doc-{key}" if key else f"doc-{file_hash(path)[:12]}"


def identify(
    path: Path,
    candidates: list[Candidate],
    cfg: AppConfig,
    valid_from: datetime,
    answers: dict[str, str] | None = None,
    trust_front_matter: bool = False,
) -> tuple[Identification, ParsedDocument | None]:
    """Decide the document for one file. Returns the decision and, unless a person
    must decide first, the file parsed under the chosen doc_key.

    ``trust_front_matter``: when building the initial store, front-matter keys
    seed the registry, so a new key needs no confirmation."""
    norm = Normalizer(cfg.layer0)
    meta = read_front_matter(path)
    fhash = file_hash(path)
    known = {c.doc_key for c in candidates}

    def parsed(key: str) -> ParsedDocument:
        return parse_file(path, cfg.layer0, valid_from, doc_key=key)

    front_key = str(meta["doc_key"]) if meta.get("doc_key") else None
    if front_key:
        if front_key in known:
            ident = Identification(path.name, fhash, front_key, "registry", 1.0,
                                   reason="doc_key in front matter matches the registry")
        else:
            ident = Identification(path.name, fhash, front_key, "front_matter", 1.0,
                                   confirm_later=bool(candidates) and not trust_front_matter,
                                   reason="doc_key in front matter is new to the registry")
        return ident, parsed(front_key)

    answer = (answers or {}).get(fhash, "").strip()
    if answer:
        key = new_doc_key(path) if answer.lower() == "new" else answer
        return (Identification(path.name, fhash, key, "human", 1.0,
                               reason=f"answered by a person: {answer}"), parsed(key))

    provisional = parsed(PROVISIONAL_KEY)
    ranked = tuple(sorted((score(provisional, c, norm, cfg.identify.compare_chars)
                           for c in candidates), key=Scores.rank_key, reverse=True))
    s = cfg.identify
    best = ranked[0] if ranked else None
    second = ranked[1].text if len(ranked) > 1 else 0.0
    if best and best.text >= s.accept_text_similarity and best.text - second >= s.accept_margin:
        return (Identification(path.name, fhash, best.doc_key, "content", round(best.text, 4),
                               reason=f"text similarity {best.text:.2f}, next {second:.2f}",
                               ranked=ranked), parsed(best.doc_key))
    if best is None or best.text < s.new_document_below:
        key = new_doc_key(path)
        top = f"{best.text:.2f}" if best else "no candidates"
        return (Identification(path.name, fhash, key, "new",
                               round(1 - (best.text if best else 0.0), 4),
                               confirm_later=bool(candidates),
                               reason=f"no document is similar enough (best {top})",
                               ranked=ranked), parsed(key))
    return (Identification(path.name, fhash, None, "content", round(best.text, 4),
                           needs_person=True,
                           reason=f"unsure: best {best.doc_key} {best.text:.2f}, "
                                  f"next {second:.2f}",
                           ranked=ranked), None)


# ---------------------------------------------------------------- person queue
#
# One row per file a person should look at. The person fills `answer` with an
# existing doc_key, or `new`, and reruns the command. Rows are matched by the
# file's hash, so renaming the file does not lose the answer. Existing rows and
# answers are never overwritten.

QUEUE_COLUMNS = ["file_hash", "file", "status", "reason", "candidate_1", "candidate_2",
                 "candidate_3", "answer"]


def read_answers(queue: Path) -> dict[str, str]:
    if not queue.exists():
        return {}
    with queue.open(encoding="utf-8-sig", newline="") as f:
        return {r["file_hash"]: r["answer"] for r in csv.DictReader(f) if r.get("answer")}


def add_to_queue(queue: Path, idents: list[Identification]) -> int:
    """Append rows for files that need a person; returns how many were added."""
    rows = []
    if queue.exists():
        with queue.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    present = {r["file_hash"] for r in rows}
    added = 0
    for ident in idents:
        if ident.file_hash in present or not (ident.needs_person or ident.confirm_later):
            continue
        cands = [f"{s.doc_key} (text {s.text:.2f}, blocks {s.blocks:.2f}, title {s.title:.2f}, "
                 f"file {s.file_name:.2f})" for s in ident.ranked[:3]]
        cands += [""] * (3 - len(cands))
        status = ("decide" if ident.needs_person
                  else f"confirm: uploaded as {ident.doc_key} ({ident.method})")
        rows.append({"file_hash": ident.file_hash, "file": ident.file, "status": status,
                     "reason": ident.reason, "candidate_1": cands[0], "candidate_2": cands[1],
                     "candidate_3": cands[2], "answer": ""})
        present.add(ident.file_hash)
        added += 1
    if added:
        queue.parent.mkdir(parents=True, exist_ok=True)
        with queue.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=QUEUE_COLUMNS)
            w.writeheader()
            w.writerows(rows)
    return added
