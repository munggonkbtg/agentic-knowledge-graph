# Plan and decision log

Living plan for the milestones in the project brief. It records what was
decided, what is provisional and what is still open, so the reasons do not live
only in commit messages. Measurements are from the pilot set unless stated.

## Status (2026-11-25)

| Milestone | State |
|---|---|
| M0 Setup | Done |
| M1 Layer 0 | Done; extended after review (block role, long-list splitting) |
| M2 Diff | **Built, not verified.** Scored against the blind sheet (30 old blocks, 10 per upload event), but the answers came from an AI reviewer, not a person (see "Label provenance"). Against those AI labels: status and partner agree on 29/30 (97%), partner 30/30. The one difference is a case-only change ("QueenBee" -> "Queenbee"): the AI labels say same, the diff says edited. Not covered by the sample: the E3 -> E2 severance move and edits across sections (thresholds `move_similarity_threshold`, `cross_section_edit_threshold` stay provisional). Known case checked separately (hand-picked, `m2_known`, answered by the user after reading the AI reviewer's answers for the same rows: source `person_seen_ai`, not a blind human label): E3 "Performance Improvement Plans" b0 -> removed (agrees); b1, the severance paragraph -> labels: moved to E2 and **split into 3 blocks**; diff: removed (**missed**). Each E2 block scores 0.40-0.49 against it, the 3 joined 0.76; other removed blocks reach at most 0.44 against 1-3 joined blocks of another document. **Fixed 2026-11-25 (split-aware moves, `diff.split_window = 3`):** pass 3 also compares a removed block with up to 3 consecutive added blocks of another document joined; the severance paragraph is now moved and split into E2 b0-b2 (0.76). Random sample unchanged (29/30); known case 2/2, but that case was used to design the rule, so it is not independent evidence. **To verify:** a person fills `m2_blind_sample_human.csv` blind |
| Upload (part of M5 steps 8-9) | `kg upload --layer 0` done early, so unchanged blocks keep their nodes |
| M3 Layer 1 | **Built, not verified** (started before M2, at the user's request). Document identification (`src/kg/identify.py`) and `REFERENCES` (`src/kg/layer1_references.py`, rule_version L1-v3). Held-out test against **AI labels**: precision 0.94, recall 0.94. **To verify:** a person fills `m3_references_test_sample_human.csv` blind |
| M5 change test set | Built 2026-11-25 before any upload or impact run (`eval/make_change_test_set.py`): 40 change items (event1 15 incl. the sabbatical edit, event2 all 13 incl. the severance move, event3 12), 141 pooled candidates to judge blind (char-trigram TF-IDF, section-number search, layer 1 REFERENCES, 15 random per event) plus free additions. Pool includes layer 1, part of the system under test: report this. **All M5 labels below come from an AI reviewer** (not blind for the synthetic edits, which it wrote). **Labelled 2026-11-25:** 141 candidates, 0 additions; needs_revision yes = 1 (E4 link to the renamed E3 heading, kind cites), no = 140; the 45 random candidates had no yes. Too few positives to measure recall per kind. **Decided:** (1) second label `needs_review` (the block should be looked at because it states, cites or depends on changed content, even if its text stays correct), added to the same sheet, earlier labels kept (backup m5_candidates.before_review_column.csv, also AI); (2) synthetic edits (`eval/make_synthetic_events.py`), each its own event on the store after events 1-3, same pooling, reported apart from the real events. **needs_review labelled:** yes = 8 (event1: states 1, depends 1; event2: cites 1, depends 1; event3: cites 4), found by char3 6, cite 4, graph 3 (a block can be found by several); 0 of 45 random. **Synthetic edits:** 15 written by the AI reviewer (E1 5, E3 1, E5 1, T1 8; S07 and S15 are controls with no dependents expected), built into 179 pooled candidates, labelled by the same reviewer: needs_review yes = 33 (states 8, cites 24, depends 1), needs_revision yes/unsure = 6 (states 3, cites 2, depends 1); controls S07 0, S15 1 (a citing block the reviewer found); found by cite 25, char3 14, graph 7; 0 of 75 random. **M5 test set in total** (recounted 2026-11-25 with `eval/m5_labels.py`: m5 + m5s + m5e and the additions, each (change, block) pair once): needs_review **54 rows** (46 in the pools + 8 additions in `m5s_additions_ai.csv`) = **61 change-block pairs**. **Historical** blocks (decided 2026-11-25, `src/kg/historical.py`: every block of an amending act, i.e. a title with "(ฉบับที่ N)", and reason notes starting "หมายเหตุ :- เหตุผลในการประกาศใช้") are kept with their labels but left out of the main numbers and reported as their own row: 11 rows / 11 pairs (states 6, cites 5). **Main: 43 rows (states 7, cites 30, depends 6) = 50 pairs (states 7, cites 34, depends 9).** The additions file has 8 rows (not 10) and no rows for x-S450 / x-S451; those T5 ข้อ 16 blocks are only in m5e (S13-E01 / E02), so nothing is counted twice. x-S097 appears twice (XS11 cites, XS14 depends): two rows. Historical states rows: 6 of 13 (S08-B09, S08-E02, S08-E05, S10-B01, S11-B11, S14-B11), not 8; the other 7 are current rules in E2, E4, T3, T4, T5 |
| M4 Layer 2 | **Started 2026-11-25.** Steps 1-2 of the continuation brief: entity registry without an LLM, measured (see "M4" below); written to Neo4j with `kg build --layer 2` (L2-v1). Step 3 (values) measured and written to the graph (L2-v2). Step 4 (local LLM fallback) measured offline: not adopted, stopped for the user's decision |
| M5 Impact analysis | **Started 2026-11-26.** Step 1 (offline retrieval experiment) and step 2 (diff, embeddings and `kg impact` on the graph; events 1-3 uploaded) done; see "M5" below. Steps 3-4 (LLM check, review report) not started |
| M6-M7 | Not started |

## Label provenance (corrected 2026-11-25)

Earlier versions of this plan said the sheets below were labelled by a person.
They were not: the answers came from an AI reviewer, and the 15 synthetic edits
(`m5s_edits.csv`) were written by that reviewer, so its labels on them are not
blind. Only a person's blind answers count for a milestone's "done" check, so
M2 and M3 are **built, not verified**.

| Sheet | Label source |
|---|---|
| `m2_blind_sample` | AI reviewer |
| `m2_known_sample` | the user, after reading the AI reviewer's answers for the same two rows (`person_seen_ai`): a person, but not independent of the AI and not blind |
| `m5s_additions`, `m4_entity_type_coverage` | AI reviewer (added to `data/labels/` 2026-11-25 as `_ai`) |
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

**Result with both methods judged to depth 5**, AI labels, recounted
2026-11-25 with the additions and without historical blocks (50 pairs):
recall@5 char3 0.36, e5 0.28, hybrid 0.28; recall@10 char3 0.46, e5 0.40,
hybrid 0.50. By kind @5: states (7) char3 0.71 / e5 0.86; cites (34) 0.21 /
0.18; depends (9) 0.67 / 0.22. Historical pairs on their own (10 amending act):
char3 @5 0.80, e5 0.40, i.e. the earlier 0.51 vs 0.34 was lifted by
historical blocks that repeat the changed words. On these labels e5 is still
below char3 overall but not on states; e5 is fine for Thai text itself (Task B).
Earlier figure, for the record: 53 pairs without additions, historical
included: @5 char3 0.51, e5 0.34. The first-pool results are kept in
`eval/results/embedding_comparison_first_pool_ai.md`.

**Not a general finding yet** (corrected 2026-11-25). Limits:
- 30 of the 43 main needs_review rows are citations, mostly by section number,
  which favours character matching.
- The candidate pool came from these two methods (plus section-number search,
  layer 1 and random). Blocks that every pooled method missed were never judged
  except the 8 additions.
- 43 rows (50 pairs) is a small sample; one pair moves a cell by 2 points
  overall and by 11-14 points for states or depends.
- The labels are an AI reviewer's, and for the synthetic edits (35 of 50 main
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
- a hand-kept file `registry/entities_manual.yaml`. **Rules (decided
  2026-11-25):** every entry records `source`, `added_by`, `added_on`; new
  entries may only come from reading the documents (`source: documents`), never
  from the label sheets or the coverage file. The 11 entries seeded from the
  brief's examples are `source: test_pairs`: they stay out of every headline
  number and are reported apart.
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
- Coverage of the states / depends pairs, AI labels, hubs above 0.2 excluded,
  **recounted 2026-11-25** with the additions and without historical blocks
  (16 main pairs: states 7, depends 9):
  - automatic registry: **6 / 16** (states 3/7, depends 3/9). 10% of judged
    negative pairs are also linked.
  - historical pairs on their own: 6 / 6 linked. The first count (11 / 20) was
    mostly these: T2 repeats the changed section's words.
  - with the test_pairs entries: 8 / 16; not an independent measurement.
  - The brief's coverage file (`m4_entity_type_coverage_ai.csv`, 19 rows = 22
    change-block pairs, all among the labelled pairs): 12 linked, 6 of them
    historical.
  - Lower cut-offs cost coverage quickly: at 0.05, 3 / 16.
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

**Step 3, values** (`src/kg/values.py`, `eval/m4_values.py`, results in
`eval/results/m4_values_ai.md`; **scored against the AI labels**; normalization
table agreed 2026-11-25 before the run):
- A value is a number with a unit right after it: Thai and Arabic digits, Thai
  number words (สามสิบ = 30), English number words; units in families compared
  only inside the family (1 year = 12 months, 1 week = 7 days); วันทำงาน /
  work days are a family of their own; days and months are never converted.
  Years after พ.ศ. and bare numbers are not values.
- Each value is attached to the nearest non-hub entity in its block; the
  attribute is **(entity, unit family)**, a provisional rule-based stand-in for
  "what the value is about". Values in blocks without an entity are kept with
  the block (entity none).
- Initial corpus: Thai 234 values in 109 of 364 body blocks (28 of those blocks
  have no entity); English 92 values in 40 of 74 blocks (18 with no entity).
  Spot check of 40 random values in context (20 th, 20 en, by Claude, not a
  label): all 40 correct.
- Noise of a plain "same value" signal: the most frequent Thai value, 30
  calendar days, is in 16 blocks; 15 days in 13. 23 of 55 change items change a
  value; median 2 candidate blocks contain a changed value (max 20, XS13 and
  XS15, of about 490). Only 16 of 2,805 judged negative pairs (1%) contain a
  changed value, against 10% for a shared entity.
- Review pairs (main 16 states / depends, historical apart):
  - linked by entity 6, by changed value 6, by either **10 / 16** (Thai 5 / 5,
    English 5 / 11);
  - the brief's count, same entity and attribute with the old value while the
    new text gives a different value: **2 of 7 states pairs** (historical: 7 of
    11). The coarse attribute and the missing entities in English limit it.
- Ranking all candidate blocks of a change (expected recall with random
  tie-breaking, no other signal): states + depends @5 entity alone 0.30,
  **entity + value 0.46**, value alone 0.26; @20 0.39 / 0.56 / 0.40. Values
  help most on depends (@5 0.26 -> 0.47). On cites both are weak (layer 1
  handles those).
- **In the graph** (`kg build --layer 2`, rule_version **L2-v2**,
  2026-11-25): values are parallel lists on the MENTIONS edge (`value`, `unit`,
  `family`, `base_value`, `base_unit`, `value_text`, `attribute`), because one
  entity can carry several values in a block; values in a block with no
  non-hub entity are `unattached_*` lists on the Block node, with
  `values_rule_version`. Hub mentions carry no values. The L2-v1 MENTIONS
  (1,110) are closed, not deleted; 1,110 L2-v2 MENTIONS carry 252 values and 44
  blocks keep 74 unattached values (326 = the 234 Thai + 92 English measured
  above). Rerun closes nothing.
- The attribute rule is coarse: on T1 มาตรา 118/1 the ค่าชดเชย mention carries
  both "สามสิบวัน" (about the payment) and "หกสิบปี" (the retirement age).
- Not checked: whether each value is attached to the right entity (no labels
  for values).

**Step 4, local LLM fallback** (decided by the user 2026-11-25: local first,
no API; `src/kg/llm.py`, `prompts/mentions_v1.md`, `eval/m4_llm_fallback.py`,
results in `eval/results/m4_llm_fallback_ai.md`; **scored against the AI
labels**, most pairs from synthetic edits by the same reviewer):
- Model `qwen3.5:4b-q4_K_M` via Ollama 0.40.18 (3.3 GB download; 3.1 GB loaded,
  100% GPU, context 2048), temperature 0, `think: false` (no thinking text in
  any reply). Gemma 4 E4B dropped for now: Ollama lists it at 6.6-9.5 GB, over
  the 6 GB card.
- Fallback on body blocks with no non-hub registry entity (126 Thai, 45 English
  in the initial corpus). Kept terms must occur in the block (10% dropped);
  new terms are LLM-sourced entities, never merged into registry entities.
- Pairs linked (states + depends, 16): A registry 6 (th 3/5, en 3/11); B with
  the LLM **7** (en 4/11, one more: C08). Negatives linked: English 10 -> 29 of
  1,591 (1% -> 2%), Thai unchanged. Blocks without any entity: Thai 126 -> 88,
  English 45 -> 18.
- JSON valid on the first attempt 254 / 254 (stability rerun 171 / 171);
  stability Jaccard Thai 0.91, English 0.98; 2.9 s and about 456 / 26 tokens
  per block.
- Mention precision / recall: not reported, the person's sheet is empty.
- **Reading (the user's rule):** B does not link clearly more English pairs.
  The 7 English pairs still unlinked are joined by a period ("first 90 days" /
  "first week", "first year"), by names at a different scope ("Short Term and
  Long Term Disability policies" vs "short-term disability claim"), by a parent
  concept ("Medical Insurance" vs "Health Insurance") or by different words for
  the same thing ("standard-issue computer" vs "specs"). A bigger model would
  not fix these by extracting entities. **Stopped 2026-11-26 for the user's
  decision**; nothing written to Neo4j, no API used.

Not checked: precision of single mentions (the blind sheet
`data/labels/m4_mentions_sample_human.csv`, 20 Thai + 20 English blocks, is
built and waits for the labelling guide and a person); the brief's 19-pair
file (`m4_entity_type_coverage.csv`) is not in `data/labels/`.

## M5: impact analysis (workflow steps 10-14)

(Diagram v5, `docs/diagrams/document_graph_workflow_v5_EN.drawio` and `_TH`,
2026-11-26, shows the system as built through M5 step 2; v4 is kept for the
record.)

The scope comes from the workflow diagram v4 (steps 8-15, Part 4 "main
experiment") and this plan; the original brief's text was not available when
M5 started. Steps 8-9 (upload, diff) were done earlier; step 15 belongs to
M6-M7.

**Step 1, offline experiment (2026-11-26)** (`src/kg/impact.py`,
`eval/m5_impact_experiment.py`, results in `eval/results/m5_impact_ai.md`;
**scored against the AI labels**, merged sheets, historical blocks apart):
- Candidates for a change: all existing body blocks of the store at that time.
  Graph signals from layers 0-2, each its own ranked list: `cite_section`
  (REFERENCES to the changed document at the changed มาตรา / ข้อ or heading
  anchor), `value` (old value of an attribute the change alters, or a changed
  value), `entity` (shared non-hub entities), `cite_document`. Ties follow the
  hybrid ranking. The same code runs on in-memory stores (experiment) and will
  run on the graph's current versions (step 2).
- Compared at the same N (50 main pairs, 24 change items):

  | method | @5 | @10 | @20 |
  |---|---|---|---|
  | baseline: hybrid search (char3 + e5, RRF) | 0.28 | 0.50 | 0.62 |
  | graph-first: graph-reached blocks by signal strength, then hybrid | **0.66** | **0.90** | **1.00** |
  | A: RRF of hybrid and the graph signal rankings | 0.54 | 0.64 | 0.72 |

  By kind @5 (baseline / graph-first / A): cites (34) 0.18 / 0.74 / 0.47;
  states (7) 0.71 / 0.57 / 0.86; depends (9) 0.33 / 0.44 / 0.56. Thai @10:
  0.38 / 1.00 / 0.59; English @10: 0.75 / 0.69 / 0.75. needs_revision pairs
  (12) @5: 0.42 / 0.75 / 0.83. C32 and C38 have no needs_review pair, so
  removing them changes nothing.
- Plain RRF dilutes the strongest signal (a section citation) with the hybrid
  ranking; ordering by signal strength works better on these labels. States
  pairs are the exception (A best at @5).
- **Decided 2026-11-26 (user): M5 carries graph-first forward**
  (`impact.ranking: graph_first` in config.yaml); RRF stays available for
  comparison.
- The graph reaches a median of 22 blocks per change (max 135), so graph-first
  is not high only because its lists are short; the list is long enough that
  the LLM check (step 13) must cut it.
- **Pooling bias:** the judged pool came from char3, section-number search,
  layer 1, e5 and random blocks plus 8 additions. Section search and layer 1
  are close to `cite_section`, so cites positives the graph reaches were more
  likely to be judged. Recall is relative to the judged pool.
- Not checked: precision of the final list (LLM check), tokens per file, any
  human label.

**Step 2, on the graph (2026-11-26)**:
- Diff results stored at upload (`Store.write_diff_results`, after every
  document of the event, because moves cross documents): on the CONTAINS edge
  of the new version, `diff_status`, `previous_block_uid`, `diff_similarity`;
  on the new Version, `removed_block_uids`. No new relationship type (the
  graph keeps the 8 types of the diagram).
- Embeddings in Neo4j (user decision 2026-11-26): `kg embed` writes the e5
  vector (1024, normalized) and `embedding_model` on the body blocks of current
  versions; `kg init-schema` creates the vector index `block_embedding`
  (cosine). Encoder moved to `src/kg/embedding.py`, same cache as the
  evaluations.
- `kg impact --doc KEY [--doc KEY]`: change items from the stored diff
  (edited / moved / added / removed body blocks), candidates = current body
  blocks, graph signals read from Neo4j (valid REFERENCES, MENTIONS with values,
  hub flags; `GraphView.from_graph`), hybrid = trigrams + e5 through the vector
  index, ranking `impact.ranking` (graph_first), top `impact.top_n` (20) per
  change to a CSV in `data/reports/` (not in git).
- **Events 1-3 uploaded into Neo4j** (approved), then the light update:
  `kg build --layer 1`, `--layer 2`, `kg embed`. Graph after: 13 versions
  (3 SUPERSEDES), 490 current body blocks, 668 references and 1,225 mentions
  with 282 values written for the current versions. E2 and T2 are new
  documents: each has a row in `doc_identification_queue.csv` to confirm.
  Old versions are closed (valid_to), not deleted; edges on old blocks stay
  open until the full update (step 15, M6-M7).
- Check against the experiment (`eval/m5_graph_check.py`, AI labels, 15 real
  main pairs): recall@5 0.73, @10 0.80, @20 0.87 vs 0.80 / 0.80 / 1.00
  offline. The difference is C01 and C11: their labelled block (E3
  "Performance Improvement Plans" b1) moved to E2 in event 2, so it is no
  longer a current block; the experiment ran on the store before event 2.
- Event 3 gives 70 changes, not about 104: footnote entries (25 added in T1)
  are skipped by rule.

**Step 3, LLM check measured offline (2026-11-26)** (decided: local
Qwen3.5-4B, top 10 per change; `prompts/impact_check_v1.md`,
`eval/m5_check_experiment.py`, results in `eval/results/m5_check_ai.md`;
**scored against the AI labels**):
- 240 checks (24 change items x top 10 graph-first), 15 min, 3.7 s and about
  860 / 60 tokens per call, JSON valid 235 / 235, no thinking text, 100% GPU
  with num_ctx 4096. The model never answered "unsure".
- Verdicts: labelled positives 21 needs_update / 24 not_affected; judged
  negatives 9 / 72; historical 9 / 0; unjudged 3 / 102. The list shrinks from
  10 to a median of 1 per change.
- Recall of needs_review pairs drops from 0.90 (top 10) to **0.42** after the
  check; of the kept judged candidates 21 / 30 are positive.
- By kind: states with needs_revision yes kept 4 / 4; cites kept 13 / 33
  (citing blocks whose text stays correct are mostly called not_affected,
  which matches "needs update" but not "needs review"); 3 cites blocks that do
  need revision were called not_affected; depends kept 2 / 5.
- Prompt rule 4 (historical text is not affected) is ignored: all 9 historical
  blocks were called needs_update because they repeat the old value.
- Evidence quoted from the candidate was found in it for 37 / 42 kept.
- Reading: the checker answers "does the text need changing", which is closer
  to needs_revision (8 / 11 checked) than to needs_review. As a hard filter it
  would hide most blocks a person should look at. Not run on the 116 graph
  changes yet.
- **Decided 2026-11-26 (user): the checker labels, it does not filter.**
  `kg impact --check` keeps every reported candidate; the top
  `impact.check_top_n` get verdict, reason and evidence; inside that top, blocks
  marked needs_update move first, except historical blocks (rule in code,
  `src/kg/historical.py`, because the model ignored the prompt rule).
- First run on the graph, event 1 (E1, 31 changes): `kg impact --doc
  en-benefits-and-perks --check`, 310 checks in 16 min (about 200K tokens):
  10 needs_update in 6 of 31 changes, now at ranks 1-4; 300 not_affected; 4
  historical rows flagged. The evidence check first failed on 8 of 10 quotes
  because the documents use curly apostrophes and the model straight ones, and
  some quotes join fragments with "..."; `evidence_in` now normalizes both:
  10 / 10 found.
- All three events checked (2026-11-26), 116 changes, 1,160 checks in about
  64 min, about 830K tokens:

  | event | changes | needs_update | changes with one | evidence found | historical rows |
  |---|---|---|---|---|---|
  | 1 (E1) | 31 | 10 | 6 | 10 / 10 | 4 |
  | 2 (E2, E3) | 15 | 5 | 5 | 4 / 5 | 1 |
  | 3 (T1, T2) | 70 | 79 | 32 | 74 / 79 | 59 (reason notes; none moved up) |

- Real labelled pairs on the graph (`eval/m5_graph_check.py`, AI labels, 15
  pairs): recall@5 0.73 -> **0.80** after the reordering, @10 0.80, @20 0.87.
  Verdicts on them: needs_update 3 (2 cites, 1 depends), not_affected 9,
  not checked or below 20 3. **The 3 cites pairs labelled needs_revision yes
  were called not_affected** (among them the E4 link to the renamed E3
  heading "Your First 90 Days"): the checker misses a broken link or a
  renamed target, which a rule could catch (a link anchor that no longer
  exists).

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
| Historical text: T2 and the reason notes appended to T1 restate old wording | **Decided 2026-11-25:** flagged by rule (`src/kg/historical.py`), out of the main numbers, reported as their own row |
| Section numbers are not unique across laws: T5 cites มาตรา ๓๔ of the Home Workers Act; matching on the number alone links it to the Labour Protection Act | Layer 1 / M5 section search: require the law name when the cited act is not the block's own |
| Diff results are not stored in the graph (old -> new block for edits) | M5, impact analysis needs them |
| Edges on the node of an edited block are not moved or closed yet | M5 light / full update |
| `valid_to IS NULL` cannot use a Neo4j range index | M5, when queries filter on validity |
| `DEPENDS` evidence needs a quote from each block (one field today) | M7 |
| Thai full-text analyzer exists (`thai`); quality not checked against PyThaiNLP | M5 hybrid search |
| Full review sheet (deleted with the data reset) | Rebuild after the blind answers, so it cannot anchor them |
| LLM (API or local), `DEPENDS` labelling guide | M4/M7; the user's decisions. MENTIONS guide agreed 2026-11-25: `docs/labelling_guide_mentions.md` |
| English entity coverage is low with headings as the only source (3 / 10 pairs) | M4: decide between more rule sources, the LLM fallback, or relying on values / embeddings for English |
| Entities that leave the registry keep their node (no validity on nodes) | M4/M5, when the registry changes between runs |
| No person has labelled any sheet yet | Before any milestone is marked done |
