# Embedding comparison (multilingual-e5-large vs char-trigram TF-IDF)

Model load 10 s; encoded 0 new texts in 0 s on CPU (cached texts not counted).

## Task A: impact retrieval on the M5 change test set (needs_review)

**Label source: ai** (an AI reviewer, not a person; does not count for a milestone's done check); 448 answered rows over the m5, m5s and m5e sheets. The synthetic edits (m5s) were written by an AI reviewer.

Labels: first pool (char3 top 3, section-number search, layer 1, random), then extended with e5 top 5 and char3 top 5 (m5e), so both methods are judged to depth 5. @5 compares them fairly; deeper ranks are unjudged for both, and the first pool's cite / graph sources lean lexical.

**Not a general finding.** Read this table with these limits:

* Most positives are citations: 29 of the 46 needs_review rows cite the changed section, mostly by number, which favours character matching.
* The pool came from these methods (plus section-number search, layer 1 and a random sample). A block that every pooled method missed was never judged and is absent from the table; only hand additions could add such blocks.
* The sample is small (46 rows, 53 change-block pairs), so one or two pairs move a cell by several points.
* The synthetic edits were written by the same AI reviewer that labelled them, so those labels are not blind.

| group | pairs | char3 @5 | char3 @10 | char3 @20 | e5 @5 | e5 @10 | e5 @20 | hybrid @5 | hybrid @10 | hybrid @20 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 53 | 0.51 | 0.58 | 0.72 | 0.34 | 0.45 | 0.60 | 0.36 | 0.57 | 0.68 |
| real | 15 | 0.40 | 0.47 | 0.53 | 0.27 | 0.33 | 0.53 | 0.20 | 0.53 | 0.53 |
| synthetic | 38 | 0.55 | 0.63 | 0.79 | 0.37 | 0.50 | 0.63 | 0.42 | 0.58 | 0.74 |
| kind cites | 33 | 0.30 | 0.36 | 0.55 | 0.21 | 0.33 | 0.52 | 0.24 | 0.39 | 0.52 |
| kind depends | 7 | 0.86 | 1.00 | 1.00 | 0.29 | 0.43 | 0.71 | 0.29 | 0.86 | 0.86 |
| kind states | 13 | 0.85 | 0.92 | 1.00 | 0.69 | 0.77 | 0.77 | 0.69 | 0.85 | 1.00 |
| lang en | 14 | 0.64 | 0.71 | 0.79 | 0.43 | 0.57 | 0.79 | 0.29 | 0.79 | 0.86 |
| lang th | 39 | 0.46 | 0.54 | 0.69 | 0.31 | 0.41 | 0.54 | 0.38 | 0.49 | 0.62 |

## Task B: finding the same passage after an edit (real uploads)

| language | pairs | char3 hit@1 | char3 MRR | e5 hit@1 | e5 MRR | hybrid hit@1 | hybrid MRR |
|---|---|---|---|---|---|---|---|
| en | 22 | 1.00 | 1.00 | 0.95 | 0.98 | 0.95 | 0.98 |
| th | 20 | 0.95 | 0.97 | 0.95 | 0.97 | 0.95 | 0.97 |