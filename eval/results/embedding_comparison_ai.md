# Embedding comparison (multilingual-e5-large vs char-trigram TF-IDF)

Model load 8 s; encoded 0 new texts in 0 s on CPU (cached texts not counted).

## Task A: impact retrieval on the M5 change test set (needs_review)

**Label source: ai** (an AI reviewer, not a person; does not count for a milestone's done check); 448 answered rows over the m5, m5s and m5e sheets. The synthetic edits (m5s) were written by an AI reviewer.

Labels: first pool (char3 top 3, section-number search, layer 1, random), then extended with e5 top 5 and char3 top 5 (m5e), so both methods are judged to depth 5. @5 compares them fairly; deeper ranks are unjudged for both, and the first pool's cite / graph sources lean lexical.

**Not a general finding.** Read this table with these limits:

* Most positives are citations: 30 of the 43 needs_review rows (historical blocks excluded) cite the changed section, mostly by number, which favours character matching.
* The pool came from these methods (plus section-number search, layer 1 and a random sample). A block that every pooled method missed was never judged; the additions sheets add 8 such pairs, which every method may miss.
* The sample is small (43 rows, 50 change-block pairs), so one or two pairs move a cell by several points.
* Historical blocks (amending act, reason notes; 11 pairs) are left out of every row except their own (`historical ...`).
* The synthetic edits were written by the same AI reviewer that labelled them, so those labels are not blind.

| group | pairs | char3 @5 | char3 @10 | char3 @20 | e5 @5 | e5 @10 | e5 @20 | hybrid @5 | hybrid @10 | hybrid @20 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 50 | 0.36 | 0.46 | 0.58 | 0.28 | 0.40 | 0.60 | 0.28 | 0.50 | 0.62 |
| real | 15 | 0.40 | 0.47 | 0.53 | 0.27 | 0.33 | 0.53 | 0.20 | 0.53 | 0.53 |
| synthetic | 35 | 0.34 | 0.46 | 0.60 | 0.29 | 0.43 | 0.63 | 0.31 | 0.49 | 0.66 |
| historical amending_act | 10 | 0.80 | 0.80 | 1.00 | 0.40 | 0.60 | 0.60 | 0.60 | 0.60 | 0.80 |
| historical reason_note | 1 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 |
| kind cites | 34 | 0.21 | 0.26 | 0.38 | 0.18 | 0.29 | 0.50 | 0.18 | 0.32 | 0.47 |
| kind depends | 9 | 0.67 | 0.89 | 1.00 | 0.22 | 0.44 | 0.78 | 0.33 | 0.89 | 0.89 |
| kind states | 7 | 0.71 | 0.86 | 1.00 | 0.86 | 0.86 | 0.86 | 0.71 | 0.86 | 1.00 |
| lang en | 16 | 0.56 | 0.69 | 0.75 | 0.38 | 0.62 | 0.81 | 0.25 | 0.75 | 0.88 |
| lang th | 34 | 0.26 | 0.35 | 0.50 | 0.24 | 0.29 | 0.50 | 0.29 | 0.38 | 0.50 |

## Task B: finding the same passage after an edit (real uploads)

| language | pairs | char3 hit@1 | char3 MRR | e5 hit@1 | e5 MRR | hybrid hit@1 | hybrid MRR |
|---|---|---|---|---|---|---|---|
| en | 22 | 1.00 | 1.00 | 0.95 | 0.98 | 0.95 | 0.98 |
| th | 20 | 0.95 | 0.97 | 0.95 | 0.97 | 0.95 | 0.97 |