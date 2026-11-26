# M5 step 1: impact retrieval, baseline vs graph (layers 0-2)

**Label source: ai** (an AI reviewer, not a person; does not count for a milestone's done check). Most pairs come from synthetic edits written by the same AI reviewer that labelled them; real changes have very few dependents in this pilot.

24 change items with at least one needs_review pair. Candidates: all existing body blocks of the store at that time except the changed ones (about 300-490). Recall@N = share of (change, block) pairs labelled needs_review in the top N. baseline = hybrid search (char3 + e5, RRF); graph = blocks reached by a graph signal first, then hybrid order; A = RRF of hybrid and the graph signal rankings. Registry automatic, hubs above 0.2. No LLM check (step 13) yet.

## Recall at the same N

| group | pairs | baseline @5 | baseline @10 | baseline @20 | graph @5 | graph @10 | graph @20 | A @5 | A @10 | A @20 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 50 | 0.28 | 0.50 | 0.62 | 0.66 | 0.90 | 1.00 | 0.54 | 0.64 | 0.72 |
| all without C32, C38 | 50 | 0.28 | 0.50 | 0.62 | 0.66 | 0.90 | 1.00 | 0.54 | 0.64 | 0.72 |
| needs_revision yes / unsure | 12 | 0.42 | 0.83 | 0.92 | 0.75 | 0.92 | 1.00 | 0.83 | 0.92 | 1.00 |
| real | 15 | 0.20 | 0.53 | 0.53 | 0.80 | 0.80 | 1.00 | 0.60 | 0.60 | 0.73 |
| synthetic | 35 | 0.31 | 0.49 | 0.66 | 0.60 | 0.94 | 1.00 | 0.51 | 0.66 | 0.71 |
| kind cites | 34 | 0.18 | 0.32 | 0.47 | 0.74 | 0.97 | 1.00 | 0.47 | 0.56 | 0.59 |
| kind depends | 9 | 0.33 | 0.89 | 0.89 | 0.44 | 0.56 | 1.00 | 0.56 | 0.67 | 1.00 |
| kind states | 7 | 0.71 | 0.86 | 1.00 | 0.57 | 1.00 | 1.00 | 0.86 | 1.00 | 1.00 |
| lang en | 16 | 0.25 | 0.75 | 0.88 | 0.56 | 0.69 | 1.00 | 0.69 | 0.75 | 1.00 |
| lang th | 34 | 0.29 | 0.38 | 0.50 | 0.71 | 1.00 | 1.00 | 0.47 | 0.59 | 0.59 |
| historical amending_act | 10 | 0.60 | 0.60 | 0.80 | 0.70 | 0.80 | 1.00 | 0.80 | 0.80 | 0.90 |
| historical reason_note | 1 | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

## Which graph signal reaches the positives (main pairs, any rank)

| kind | pairs | cite_section | value | entity | cite_document | any |
|---|---|---|---|---|---|---|
| states | 7 | 0 | 4 | 3 | 2 | 5 |
| cites | 34 | 32 | 3 | 10 | 5 | 33 |
| depends | 9 | 1 | 2 | 3 | 0 | 5 |

## How many blocks the graph reaches per change

Over 24 change items: median 22, max 135, total 996 blocks reached, of which 54 are labelled needs_review (historical included). A short list puts every reached block near the top, so graph @N is high when lists are short; the precision of the list is what the LLM check (step 13) has to handle.

| change | blocks reached | needs_review among them |
|---|---|---|
| XS12 | 135 | 4 |
| XS15 | 134 | 1 |
| XS14 | 109 | 8 |
| XS11 | 102 | 8 |
| C31 | 83 | 2 |
| C34 | 81 | 2 |
| XS13 | 59 | 6 |
| XS10 | 55 | 5 |
| C36 | 51 | 1 |
| XS09 | 48 | 2 |

**Pooling bias:** the judged candidates were pooled from char3, section-number search, layer 1 REFERENCES, e5 and random blocks (plus 8 hand additions). Layer 1 and section search are close to the cite_section signal, so cites positives the graph reaches were more likely to be judged at all; positives no pooled method found are absent. Recall here is relative to the judged pool, not to all true dependents.

Not checked: the LLM check of step 13 (precision of the final list), tokens per file, and any human label; results on Neo4j's stored graph (step 2) may differ where the graph holds older rule versions.