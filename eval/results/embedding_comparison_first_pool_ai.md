# Embedding comparison (multilingual-e5-large vs char-trigram TF-IDF)

Model load 8 s; encoded 0 new texts in 0 s on CPU (cached texts not counted).

## Task A: impact retrieval on the M5 change test set (needs_review)

**Label source: ai** (an AI reviewer, not a person). Kept for the record: the first pool, before the e5 extension (m5e). Not a general finding; see embedding_comparison_ai.md for the caveats.

Labels were pooled without any embedding method: blocks only e5 finds were never judged, so this table favours char3 (a lower bound for e5).

| group | pairs | char3 @5 | char3 @10 | char3 @20 | e5 @5 | e5 @10 | e5 @20 | hybrid @5 | hybrid @10 | hybrid @20 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 48 | 0.50 | 0.56 | 0.69 | 0.33 | 0.44 | 0.60 | 0.38 | 0.54 | 0.65 |
| real | 15 | 0.40 | 0.47 | 0.53 | 0.27 | 0.33 | 0.53 | 0.20 | 0.53 | 0.53 |
| synthetic | 33 | 0.55 | 0.61 | 0.76 | 0.36 | 0.48 | 0.64 | 0.45 | 0.55 | 0.70 |
| kind cites | 33 | 0.30 | 0.36 | 0.55 | 0.21 | 0.33 | 0.52 | 0.24 | 0.39 | 0.52 |
| kind depends | 6 | 0.83 | 1.00 | 1.00 | 0.33 | 0.33 | 0.67 | 0.33 | 0.83 | 0.83 |
| kind states | 9 | 1.00 | 1.00 | 1.00 | 0.78 | 0.89 | 0.89 | 0.89 | 0.89 | 1.00 |
| lang en | 13 | 0.62 | 0.69 | 0.77 | 0.46 | 0.54 | 0.77 | 0.31 | 0.77 | 0.85 |
| lang th | 35 | 0.46 | 0.51 | 0.66 | 0.29 | 0.40 | 0.54 | 0.40 | 0.46 | 0.57 |

## Task B: finding the same passage after an edit (real uploads)

| language | pairs | char3 hit@1 | char3 MRR | e5 hit@1 | e5 MRR | hybrid hit@1 | hybrid MRR |
|---|---|---|---|---|---|---|---|
| en | 22 | 1.00 | 1.00 | 0.95 | 0.98 | 0.95 | 0.98 |
| th | 20 | 0.95 | 0.97 | 0.95 | 0.97 | 0.95 | 0.97 |