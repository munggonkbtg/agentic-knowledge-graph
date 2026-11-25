# Plan and decision log

Living plan for the milestones in the project brief. It records what was
decided, what is provisional and what is still open, so the reasons do not live
only in commit messages. Measurements are from the pilot set unless stated.

## Status (2026-11-25)

| Milestone | State |
|---|---|
| M0 Setup | Done |
| M1 Layer 0 | Done; extended after review (block role, long-list splitting) |
| M2 Diff | Built; **waiting for the blind check** (`data/labels/m2_blind_sample.csv`) |
| Upload (part of M5 steps 8-9) | `kg upload --layer 0` done early, so unchanged blocks keep their nodes |
| M3 Layer 1 | Planned below (identification rules approved 2026-11-25); starts after M2 is verified |
| M4-M7 | Not started |

## Decisions so far

| Topic | Decision | Why / evidence |
|---|---|---|
| Block identity | `block_id` = position (`doc_key::H2 > H3::b<n>`); node key `block_uid` set when first seen; an upload reuses the node of every block the diff marks unchanged | Without reuse, 63 unchanged T1 blocks and 1 E3 block got new nodes; now 0 |
| Title heading | A single `#` title is left out of heading paths | Keeping it changed every T1 `block_id` between versions |
| Text normalization | NFC, whitespace, footnote markers removed, Thai digits -> Arabic, before hashing | Unchanged T1 text 91% with, 54% without |
| Footnote lists | `role = footnote`; matched by identical text only | Entries are template text; similarity paired unrelated entries |
| Long lists | Split into items above 1,500 characters | Blocks > 1,500 chars: 16 -> 11. One T1 มาตรา 5 item is still 3,170 chars (source merged definitions into one line) |
| Diff thresholds | edit 0.5, cross-section 0.8, move 0.5 — **all provisional** | Character similarity of unrelated English paragraphs is already 0.41-0.44; set from blind labels |
| Labels | Only a person's `verdict` / blind answers count; AI suggestions kept in a separate column | v2 labels were written by an AI |

## M3: document identification + Layer 1 (`REFERENCES`)

Review point 3: today a file without `doc_key` in its front matter is rejected.
Real organisational files will not have one. M3 adds the identification step
from the brief (pipeline steps 1 and 8) before the `REFERENCES` work.

### What the pilot data says

Measured by comparing each upload with every document in the initial corpus
(`rapidfuzz` ratio on normalized text, first 20,000 characters):

| Upload | Right document: text / file name / title | Best wrong document: text / file name / title |
|---|---|---|
| E1 | 0.82 / 1.00 / 1.00 | 0.37 / 0.41 / 0.32 |
| E3 | 0.75 / 1.00 / 1.00 | 0.39 / 0.50 / 0.47 |
| T1 | 0.96 / 1.00 / 0.82 | 0.33 / 0.47 / 0.35 |
| E2 (new) | — | 0.34 / 0.40 / 0.36 |
| T2 (new, amends T1) | — | **0.34 / 0.74 / 0.67** (T1) |

Exact block overlap with the right document: E1 0.45, E3 0.45, T1 0.84; the new
documents overlap 0.

Two lessons:
1. **Content separates cleanly; names do not.** T2 looks like T1 by file name
   and title but not by text. A rule that trusts names would file the amending
   act as a new version of the act it amends.
2. **File names here are ours.** The pilot files were renamed when the set was
   built (`E1_…`), so real file-name similarity will be weaker than 1.00.

### Steps

1. **Registry.** `doc_key` in front matter and known in the graph -> that
   document (method `registry`, confidence 1.0). Known keys come from the
   `Document` nodes; no separate registry file.
2. **`doc_key` present but unknown** -> a new document, but listed for a person
   to confirm (it may be a typo of an existing key).
3. **No `doc_key`** -> score every current version:
   - text similarity of the whole document (primary signal),
   - share of identical blocks (exact hashes),
   - file-name and title similarity (tie-breakers only, never enough alone).
4. **Decide** with three provisional values in `config.yaml`:
   - `doc_id.accept_text_similarity` (e.g. 0.7) **and** a margin over the
     second candidate (e.g. 0.2) -> accept automatically;
   - best text similarity below `doc_id.new_document_below` (e.g. 0.45) -> new
     document, listed for confirmation;
   - anything else -> **ask a person**.
5. **Asking a person** = the file is not uploaded; a row goes to
   `data/labels/doc_identification_queue.csv` with the top 3 candidates and
   their scores. The person writes the chosen `doc_key` (or `new`) and reruns
   `kg upload`, which reads the answers. Chosen over an interactive prompt so
   runs stay non-interactive and testable.
6. **Provenance.** `HAS_VERSION` gets `method` (`registry` / `content` /
   `human`), `confidence` and the scores used, like every other edge.

### How it will be tested

- Strip `doc_key` from the 5 upload files and from each initial file in turn
  (leave-one-out): count right / wrong / sent to a person.
- **T2 must not be filed under T1**, and E2 must not be filed under E3 (it
  contains the paragraph that moved out of E3).
- Unit tests on the fixtures (`tests/fixtures/`), so they run on a fresh clone.

### Then: Layer 1 `REFERENCES`

As in the brief: regex + the document registry; `REFERENCES` points to the
logical `Document`, with the cited section as a property; the LLM only for
ambiguous references. Thai patterns to cover: มาตรา N, มาตรา N/M, มาตรา N (k),
ข้อ N, in Thai or Arabic digits; links in the English files (E4 links to E3's
`#your-first-90-days`, a heading that was renamed). Target from the brief:
precision >= 0.9, recall >= 0.8 against labels made by reading.

## Open items carried forward

| Item | Where it belongs |
|---|---|
| Blocks that split or merge (E1 sick time, E3 -> E2 severance, T1 มาตรา 5 and 118) cannot be expressed by one-to-one matching | After the blind labels show how often it matters |
| Diff results are not stored in the graph (old -> new block for edits) | M5, impact analysis needs them |
| Edges on the node of an edited block are not moved or closed yet | M5 light / full update |
| `valid_to IS NULL` cannot use a Neo4j range index | M5, when queries filter on validity |
| `DEPENDS` evidence needs a quote from each block (one field today) | M7 |
| Thai full-text analyzer exists (`thai`); quality not checked against PyThaiNLP | M5 hybrid search |
| Full review sheet (v3) is stale after the list split | Rebuild after the blind answers, so it cannot anchor them |
| Entity types, embedding model, LLM, `DEPENDS` labelling guide | Raised when the milestone starts (brief section 12) |
