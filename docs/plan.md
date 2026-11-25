# Plan and decision log

Living plan for the milestones in the project brief. It records what was
decided, what is provisional and what is still open, so the reasons do not live
only in commit messages. Measurements are from the pilot set unless stated.

## Status (2026-11-25)

| Milestone | State |
|---|---|
| M0 Setup | Done |
| M1 Layer 0 | Done; extended after review (block role, long-list splitting) |
| M2 Diff | **Built, not verified.** Scored against the blind sheet (30 old blocks, 10 per upload event), but the answers came from an AI reviewer, not a person (see "Label provenance"). Against those AI labels: status and partner agree on 29/30 (97%), partner 30/30. The one difference is a case-only change ("QueenBee" -> "Queenbee"): the AI labels say same, the diff says edited. Not covered by the sample: the E3 -> E2 severance move and edits across sections (thresholds `move_similarity_threshold`, `cross_section_edit_threshold` stay provisional). Known case checked separately (hand-picked, `m2_known`, label source not confirmed, treated as AI): E3 "Performance Improvement Plans" b0 -> removed (agrees); b1, the severance paragraph -> labels: moved to E2 and **split into 3 blocks**; diff: removed (**missed**). Each E2 block scores 0.40-0.49 against it, the 3 joined 0.76; other removed blocks reach at most 0.44 against 1-3 joined blocks of another document. **Fixed 2026-11-25 (split-aware moves, `diff.split_window = 3`):** pass 3 also compares a removed block with up to 3 consecutive added blocks of another document joined; the severance paragraph is now moved and split into E2 b0-b2 (0.76). Random sample unchanged (29/30); known case 2/2, but that case was used to design the rule, so it is not independent evidence. **To verify:** a person fills `m2_blind_sample_human.csv` blind |
| Upload (part of M5 steps 8-9) | `kg upload --layer 0` done early, so unchanged blocks keep their nodes |
| M3 Layer 1 | **Built, not verified** (started before M2, at the user's request). Document identification (`src/kg/identify.py`) and `REFERENCES` (`src/kg/layer1_references.py`, rule_version L1-v3). Held-out test against **AI labels**: precision 0.94, recall 0.94. **To verify:** a person fills `m3_references_test_sample_human.csv` blind |
| M5 change test set | Built 2026-11-25 before any upload or impact run (`eval/make_change_test_set.py`): 40 change items (event1 15 incl. the sabbatical edit, event2 all 13 incl. the severance move, event3 12), 141 pooled candidates to judge blind (char-trigram TF-IDF, section-number search, layer 1 REFERENCES, 15 random per event) plus free additions. Pool includes layer 1, part of the system under test: report this. **All M5 labels below come from an AI reviewer** (not blind for the synthetic edits, which it wrote). **Labelled 2026-11-25:** 141 candidates, 0 additions; needs_revision yes = 1 (E4 link to the renamed E3 heading, kind cites), no = 140; the 45 random candidates had no yes. Too few positives to measure recall per kind. **Decided:** (1) second label `needs_review` (the block should be looked at because it states, cites or depends on changed content, even if its text stays correct), added to the same sheet, earlier labels kept (backup m5_candidates.before_review_column.csv, also AI); (2) synthetic edits (`eval/make_synthetic_events.py`), each its own event on the store after events 1-3, same pooling, reported apart from the real events. **needs_review labelled:** yes = 8 (event1: states 1, depends 1; event2: cites 1, depends 1; event3: cites 4), found by char3 6, cite 4, graph 3 (a block can be found by several); 0 of 45 random. **Synthetic edits:** 15 written by the AI reviewer (E1 5, E3 1, E5 1, T1 8; S07 and S15 are controls with no dependents expected), built into 179 pooled candidates, labelled by the same reviewer: needs_review yes = 33 (states 8, cites 24, depends 1), needs_revision yes/unsure = 6 (states 3, cites 2, depends 1); controls S07 0, S15 1 (a citing block the reviewer found); found by cite 25, char3 14, graph 7; 0 of 75 random. **M5 test set in total** (m5 + m5s + m5e, recounted 2026-11-25): needs_review **46 rows** (states 13, cites 29, depends 4) = **53 change-block pairs** (states 13, cites 33, depends 7), because one block can depend on several change items; no pair is counted twice across the three sheets. No additions file holds rows (`m5_additions.csv` is empty; there is no `m5s_additions.csv`), so hand-added blocks are not in these totals. Weak spot: "depends" has only 4 rows / 7 pairs |
| M4 Layer 2 | **Started 2026-11-25.** Steps 1-2 of the continuation brief: entity registry without an LLM, measured (see "M4" below); written to Neo4j with `kg build --layer 2` (L2-v1). Values on MENTIONS (step 3) not started |
| M5-M7 | Not started |

## Label provenance (corrected 2026-11-25)

Earlier versions of this plan said the sheets below were labelled by a person.
They were not: the answers came from an AI reviewer, and the 15 synthetic edits
(`m5s_edits.csv`) were written by that reviewer, so its labels on them are not
blind. Only a person's blind answers count for a milestone's "done" check, so
M2 and M3 are **built, not verified**.

| Sheet | Label source |
|---|---|
| `m2_blind_sample` | AI reviewer |
| `m2_known_sample` | not confirmed; treated as AI until confirmed |
| `m3_references_sample` (dev), `m3_references_test_sample` | AI reviewer |
| `m5_candidates`, `m5s_candidates`, `m5e_candidates` | AI reviewer (synthetic edits written by it too) |

Since then, answers are kept apart by source (`eval/label_sources.py`): a
generator writes a blank sheet `<stem>.csv`; answers live in
`<stem>_ai.csv` and `<stem>_human.csv` (blank, same rows, for a person). Every
scoring script takes `--labels human | ai | both`, names the source at the top
of each result file (`eval/results/<name>_agreement_<source>.md`), and with
both sources writes their agreement (`<name>_labels_human_vs_ai.md`, exact
agreement and Cohen's kappa per column).

`data/labels/` is not in git. `uv run kg backup-labels` copies it to
`~/kg_label_backups/labels-<date>-<time>` (or `KG_LABEL_BACKUP_DIR`); every
sheet generator runs the same backup before writing and refuses to overwrite a
sheet or its `_ai` / `_human` copies.

## Decisions so far

| Topic | Decision | Why / evidence |
|---|---|---|
| Block identity | `block_id` = position (`doc_key::H2 > H3::b<n>`); node key `block_uid` set when first seen; an upload reuses the node of every block the diff marks unchanged | Without reuse, 63 unchanged T1 blocks and 1 E3 block got new nodes; now 0 |
| Title heading | A single `#` title is left out of heading paths | Keeping it changed every T1 `block_id` between versions |
| Text normalization | NFC, whitespace, footnote markers removed, Thai digits -> Arabic, before hashing | Unchanged T1 text 91% with, 54% without |
| Footnote lists | `role = footnote`; matched by identical text only | Entries are template text; similarity paired unrelated entries |
| Long lists | Split into items above 1,500 characters | Blocks > 1,500 chars: 16 -> 11. One T1 มาตรา 5 item is still 3,170 chars (source merged definitions into one line) |
| Diff thresholds | edit 0.5 **consistent with the AI labels** (they confirm edits at similarity 0.50, 0.53, 0.58; no false edits), not yet with a person's; cross-section 0.8 and move 0.5 **still provisional** (no such case in the sample) | Character similarity of unrelated English paragraphs is already 0.41-0.44; set from blind labels |
| Labels | Only a person's blind answers count; AI answers kept in separate files (`_ai.csv`) and reported apart | v2 labels and the M2 / M3 / M5 sheets were answered by an AI |

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

**Rules approved 2026-11-25** (implemented in `src/kg/layer1_references.py`):

1. A section cited inside the same act -> edge to its own document,
   `self_reference = true`.
2. Bare "มาตรา N" -> the law named most recently before it in the same block;
   else, inside an act, the act itself; inside a regulation, the act it is
   issued under (title / first blocks), lower confidence. A regulation's
   "this regulation" (กฎกระทรวงนี้) is never the target of a มาตรา citation,
   because regulations number their own parts with ข้อ.
3. A law not in the store -> stub `Document` with `in_store = false`, keyed by
   the compact name (spacing and digit style do not split one law).
4. One edge per cited section (`cited_section`, e.g. "มาตรา 118 (6)"); a law
   named without a section -> one document-level edge (`cited_section = ""`).

Other choices: names are matched on compact text (no spaces, Arabic digits);
a law named without its year goes to the only matching document, or to the
principal act when amending acts share its name; footnote entries are skipped;
English uses Markdown links (file name from `source_url`, `#anchor` as the
cited section; other URLs become stubs) and exact titles of other pages.
Confidence per resolution is in `config.yaml` (`layer1.confidence`), all
provisional. Extra names for documents go in `registry/aliases.yaml`
(reviewed by a person); `kg registry` shows what each document can be cited by.

Known limits: a range "มาตรา 118 ถึงมาตรา 122" gives edges for its two ends
only; stubs are not merged with a real document uploaded later under another
key; a law named without its year that is not in the store is not detected.

**Dev set** (77 blocks, `data/labels/m3_references_*`, labelled by an AI
reviewer, then **used to tune the rules**, so its later numbers are optimistic):

| rule_version | precision | recall | change |
|---|---|---|---|
| L1-v1 | 0.89 | 0.80 | first rules |
| L1-v3 | 0.96 | 0.93 | list "law A มาตรา X law B มาตรา Y" takes the law before; "วรรค N" kept inside the citation; ข้อ never targets an act; regulations named with a year or (กฎกระทรวง) without one; laws named by subject, only when the law is known; หมวด as a section; deterministic order (L1-v2 was not) |

Old edges are closed, not deleted: each REFERENCES edge has `rule_version`;
a rerun with a newer version sets `valid_to` and `closed_reason` on the older
edges (graph now: 528 open L1-v3 edges, 495 L1-v1 and 529 L1-v2 closed).
Known limit kept: section numbers of an amending act quoted in the
consolidated text (R036, R065 in the dev set) need the LLM step.

**Test set** (held out): 60 new blocks, seed 20261126, none from the dev set
(`data/labels/m3_references_test_*`). M3's precision / recall is reported on
this set only.

**Test set result (L1-v3, labelled by an AI reviewer, rules not changed
after it):** precision **0.94**, recall **0.94** (124 citations by layer 1,
124 in the AI labels, 117 shared); document-level precision / recall 0.87.
Targets met against the AI labels (>= 0.9 / >= 0.8); not yet checked against
a person. By resolution: issued_under 25/25,
self_document 59/60, explicit 33/36, name_without_year 0/3.

Remaining errors on the test set (for a later rule version, which would then
need a fresh test sample):
- "กฎกระทรวง…" without a year also catches ordinary phrases
  ("กฎกระทรวงดังกล่าว…", "กฎกระทรวงแต่ต้องไม่เกิน…"): all 3 name_without_year
  edges and 1 explicit edge were wrong (R026, R052).
- "ระเบียบ…" inside an act's name ("พระราชบัญญัติระเบียบบริหารราชการแผ่นดิน")
  is taken as a regulation, because regulations are matched before acts (R028).
- Not detected: an order of the Revolutionary Council named by number and
  date (R003), a regulation named by subject only that is not known (R039),
  a department manual (R042), an amending-act note naming this act as a whole
  (R035).
- Labelling convention: an act named after a list of its sections got an
  extra document-level edge the labels did not count (R010).

Limits of this measurement: AI labels only, no person yet (so no agreement
figure); 50 Thai blocks; the test set has no English blocks with links (all 17
were used in the dev set, where links scored 1.00, and link rules did not
change).

To verify: a person fills `data/labels/m3_references_test_sample_human.csv`
blind, then `uv run python eval/references_agreement.py --name
m3_references_test --labels both` scores layer 1 against each source and
reports how far the person and the AI agree.

## Embedding model (M4 / M5), first comparison 2026-11-25

Approved download: intfloat/multilingual-e5-large only (2.24 GB, MIT); CPU-only
PyTorch in the `embed` dependency group. `eval/compare_embeddings.py`, results
in `eval/results/embedding_comparison_ai.md` (Task A scored against the **AI
labels**; `--labels human` once a person has labelled):

- Task B, same passage after an edit (no labels needed): hit@1 Thai 0.95 for
  both char3 and e5, English char3 1.00 / e5 0.95. e5 handles Thai as well as
  the lexical method here.
- Task A, impact retrieval on the M5 change test set: recall@10 char3 0.56,
  e5 0.44, hybrid (RRF) 0.54. **Not a fair test yet:** 20 of the 41 positive
  blocks were pooled by char3's own top 3, and no embedding method was in the
  pool, so blocks only e5 would find were never judged.
- Speed: 641 texts in 273 s on CPU (about 0.4 s each); the model loads in 42 s.

Pool extension built (`eval/make_e5_pool.py`, 2026-11-25): for every change
item (40 real, 15 synthetic), e5's top 5 and char3 extended from depth 3 to 5,
so both methods are judged to the same depth; blocks judged before are skipped.
128 new blocks to judge blind in `data/labels/m5e_candidates.csv` (e5 only 79,
char3 only 27, both 22). Labelled 2026-11-25: 5 more needs_review blocks (states 4, depends 1; all
synthetic), 3 from char3 ranks 4-5 and 2 from e5 only; 2 needs_revision yes.

**Result with both methods judged to depth 5** (53 change-block pairs):
recall@5 char3 0.51, e5 0.34, hybrid 0.36; recall@10 char3 0.58, e5 0.45,
hybrid 0.57. By kind @10: states char3 0.92 / e5 0.77 / hybrid 0.85; cites
0.36 / 0.33 / 0.39; depends (7 pairs) 1.00 / 0.43 / 0.86. Thai @10 0.54 /
0.41 / 0.49. On these labels e5 does not beat the lexical method for finding
blocks that need review, and fusing it in does not help at @5. e5 is still fine
for Thai text itself (Task B). The first-pool results are kept in
`eval/results/embedding_comparison_first_pool_ai.md`.

**Not a general finding yet** (corrected 2026-11-25). Limits:
- 29 of the 46 needs_review rows are citations with matching section numbers,
  which favours character matching.
- The candidate pool came from these two methods (plus section-number search,
  layer 1 and random). Blocks that every pooled method missed were never judged
  and are absent; the brief mentions 10 blocks the reviewer added by hand, but
  no additions file with rows is in `data/labels/`, so they are not in this
  result.
- 46 rows (53 pairs) is a small sample; one pair moves a cell by about 2
  points overall and by up to 14 points for depends.
- The labels are an AI reviewer's, and for the synthetic edits (38 of 53
  pairs) the same reviewer wrote the edits.

**Decided 2026-11-25:** the M5 hybrid search uses intfloat/multilingual-e5-large
(`embedding` section in config.yaml). Reported as an observation on this pilot
with the limits above, not as a finding about embeddings. Only e5-large was
tested; other models were not.

## M4: entity layer (continuation brief, 2026-11-25)

Design as in the continuation brief: core types Concept (procedures included),
Role, Artifact; secondary Body, Place (registry only); laws, sections, people,
bare dates and amounts are not entities; values go on `MENTIONS` (step 3);
hubs flagged, not removed.

**Step 1, registry without an LLM** (`src/kg/layer2_entities.py`):
- Thai definitions "X หมายความว่า …" in every Thai document (33 entities;
  years and repealed terms skipped, "ตามมาตรานี้" dropped from the name);
- Thai chapter headings split into their list items, English section headings
  (an acronym in brackets becomes an alias; a US state in the heading also
  gives a Place);
- the "ว่าด้วย …" subject of Thai regulation titles;
- a hand-kept file `registry/entities_manual.yaml`, seeded only with the
  brief's own examples.
Types by plain rules (Body: คณะกรรมการ / กองทุน / กรม…; Artifact: แบบ /
ทะเบียน…; Role: titles and definitions that start with ผู้ / บุคคล /
ข้าราชการ…; else Concept). Matching: Thai on compact text, English case-
insensitive with plural "s" and hyphen = space; longest name first, no overlaps.
No NER model.

**Step 2, measured** (`eval/m4_registry_coverage.py`, results in
`eval/results/m4_registry_coverage_ai.md`; **scored against the AI labels**):

- Registry on the initial corpus: 95 entities (th: 41 Concept, 11 Role,
  3 Body; en: 35 Concept, 5 Place); 0 Artifact without the manual file.
  15 of 35 English concepts never occur in the text (heading names such as
  "Vacation Time" are not repeated in the paragraphs).
- Blocks without any entity: Thai 77 of 364, **English 45 of 74**.
- Hub distribution: นายจ้าง 0.46, ลูกจ้าง 0.45, then ค่าจ้าง 0.18,
  สวัสดิการ 0.15, พนักงานตรวจแรงงาน 0.11; no English entity above 0.08
  ("37signals" is not in the registry). A cut-off between 0.2 and 0.45 flags
  just the two; 0.15 adds ค่าจ้าง and สวัสดิการ. **Decided 2026-11-25 (user):
  `layer2.hub_block_share = 0.2`** (hubs: นายจ้าง, ลูกจ้าง).
- Coverage of the 20 states / depends pairs (13 states, 7 depends; Thai 10,
  English 10) with hubs above 0.2 excluded:
  - automatic registry: **11 / 20** (states 9/13, depends 2/7); Thai 9 / 10,
    English 3 / 10. 10% of judged negative pairs are also linked.
  - with the manual file: 13 / 20, but its entries were taken from these same
    pairs, so this is not an independent measurement.
  - Lower cut-offs cost coverage quickly: at 0.05, 4 / 20.
- Why English fails: in 6 of the 10 English pairs the changed block contains no
  registry name at all; what links them is a role ("your manager"), a period
  ("first 90 days" / "first week") or a phrase that is not a heading. Adding the
  block's own section heading as an implicit mention was tried and linked no
  new pair (it only linked more negatives: English 11 -> 76 of 1,591), so it
  was not adopted.

**In the graph** (`kg build --layer 2`, 2026-11-25, rule_version L2-v1): the
registry is rebuilt from the current version of every document in the graph
plus `registry/entities_manual.yaml`.
- `Entity {entity_id, entity_type, canonical_name, language, hub, block_share,
  sources, rule_version}`: 104.
- `Alias {alias_id, surface, language}` -[`ALIAS_OF`]-> `Entity`: 106, each alias
  to exactly one entity; method `regex` (definitions), `parser` (headings,
  titles) or `human` (manual file only).
- `Block` -[`MENTIONS` {rule_version, method regex, evidence_span = the name as
  matched, confidence 0.8 provisional, valid_from}]-> `Entity`: 1,110, one per
  (block, entity); body blocks only. No values yet (step 3).
- Rerun changes nothing (checked); a new rule_version closes older MENTIONS and
  ALIAS_OF (valid_to, closed_reason), as for REFERENCES.
- Hubs with the cut-off 0.2: นายจ้าง 0.46, ลูกจ้าง 0.45 and **manager 0.22**.
  "manager" comes from the manual file, so it was not in the distribution the
  cut-off was chosen from (automatic registry only). With it as a hub, one
  depends pair is no longer linked (manual-file row: 4/7 at 0.3, 3/7 at 0.2).
  **Decided 2026-11-25 (user): "manager" stays a hub**; manual entries follow
  the same cut-off as every other entity.
- Not handled yet: an entity that drops out of the registry keeps its node
  (no `valid_to` on nodes); mentions in old versions' blocks stay as written.

Not checked: precision of single mentions (the blind sheet
`data/labels/m4_mentions_sample_human.csv`, 20 Thai + 20 English blocks, is
built and waits for the labelling guide and a person); the brief's 19-pair
file (`m4_entity_type_coverage.csv`) is not in `data/labels/`.

## Open items carried forward

| Item | Where it belongs |
|---|---|
| Splits and merges: **done for moves to another document** (split_window = 3). Still one-to-one: blocks that split or merge inside one document cannot be expressed (E1 sick time; T1 มาตรา 5, 118; มาตรา 120, 124/1 from the second review, not re-checked); the E3 -> E2 severance move needed the split window and is the only real case. Evidence for the move rule is thin (1 real split move, 2 non-moves on the pilot) | Check on more upload events; extend to splits inside a document if they matter for impact |
| Amending act quoted as a move: T2 quotes the new wording of T1, and pass 3 takes T1 มาตรา 146 (3) as moved to T2 (change C32) | Diff: do not pair an act's block with a quotation inside an amending act; or mark amending acts |
| Footnote lines are template text ("มาตรา X แก้ไขเพิ่มเติมโดย …") and get paired across different sections (reported by the second review; not re-checked: of 66 footnote pairs in events 1-3, 59 changed position, which the identical-text rule allows and does not by itself show a wrong pair) | Check the pairs; if wrong, pair footnotes only within the same cited section |
| Change list: C32 (the T2 quotation above, new text differs only by a stray quote mark) and C38 (part of the T1 มาตรา 5 definitions, "removed" because the list was cut at a different point) in `m5_changes.csv` are diff artefacts, not real changes | Report M5 with and without them |
| T1 contains C1 control characters `\x93` / `\x94` (smart quotes decoded with the wrong code page) around defined terms; 11 blocks of the initial corpus have them, and normalization keeps them, so they reach hashes | Layer 0 normalization: map them to quotes (changes hashes, so with a rebuild) |
| Real changes have almost no cross-document dependents in this pilot: 1 needs_revision block out of 141 candidates for events 1-3. The synthetic edits compensate, but they were written by the AI reviewer that labelled them | Real edits from a person, or a second corpus, before M5 conclusions |
| Candidate pools miss true dependents: for XS13 the two T5 ข้อ 16 blocks that state "สามสิบวัน" were not in the first pool although they repeat the changed number (found only by the e5 / deeper char3 extension) | M5 recall is an upper bound for what the pool covers; keep an additions step |
| Historical text: T2 and the reason notes appended to T1 restate old wording; labelled "needs review, no revision" | **User decision:** whether they count as needs_review (labelling guide) |
| Section numbers are not unique across laws: T5 cites มาตรา ๓๔ of the Home Workers Act; matching on the number alone links it to the Labour Protection Act | Layer 1 / M5 section search: require the law name when the cited act is not the block's own |
| Additions: `m5_additions.csv` is empty and there is no `m5s_additions.csv`; the brief mentions hand-added blocks (x-S007 for XS04, x-S097 for XS14) that are not in any sheet here | Put the file in `data/labels/` if it exists elsewhere |
| `m2_known_sample` label source not confirmed (treated as AI) | User to confirm |
| Diff results are not stored in the graph (old -> new block for edits) | M5, impact analysis needs them |
| Edges on the node of an edited block are not moved or closed yet | M5 light / full update |
| `valid_to IS NULL` cannot use a Neo4j range index | M5, when queries filter on validity |
| `DEPENDS` evidence needs a quote from each block (one field today) | M7 |
| Thai full-text analyzer exists (`thai`); quality not checked against PyThaiNLP | M5 hybrid search |
| Full review sheet (deleted with the data reset) | Rebuild after the blind answers, so it cannot anchor them |
| LLM (API or local), `MENTIONS` and `DEPENDS` labelling guides (draft for MENTIONS in `eval/make_mentions_sheet.py`) | M4; the user's decisions |
| English entity coverage is low with headings as the only source (3 / 10 pairs) | M4: decide between more rule sources, the LLM fallback, or relying on values / embeddings for English |
| Entities that leave the registry keep their node (no validity on nodes) | M4/M5, when the registry changes between runs |
| No person has labelled any sheet yet | Before any milestone is marked done |
