# M4 step 3: values on MENTIONS (rules, no LLM)

Normalization: `src/kg/values.py` (table agreed 2026-11-25). Attribute = (nearest non-hub entity, unit family), a provisional rule. Registry: automatic; hubs above 0.2 excluded.

## 1. Values in the initial corpus (body blocks)

| language | blocks | values | blocks with a value | ... of which no entity | values with no entity in the block |
|---|---|---|---|---|---|
| th | 364 | 234 | 109 | 28 | 48 |
| en | 74 | 92 | 40 | 18 | 28 |

Most frequent values (blocks that contain the value; the noise a plain "same value" signal would pull in):

| language | value (family, comparable) | blocks |
|---|---|---|
| th | calendar_days 30 | 16 |
| th | calendar_days 15 | 13 |
| th | months 12 | 9 |
| th | months 216 | 9 |
| th | calendar_days 7 | 8 |
| th | count_persons 10 | 7 |
| th | months 1 | 6 |
| th | calendar_days 180 | 5 |
| th | percent 15 | 5 |
| th | work_days 3 | 5 |
| en | percent 100 | 6 |
| en | months 12 | 5 |
| en | calendar_days 84 | 5 |
| en | percent 10 | 5 |
| en | months 3 | 4 |
| en | calendar_days 90 | 3 |
| en | percent 75 | 2 |
| en | percent 6 | 2 |
| en | calendar_days 56 | 2 |
| en | calendar_days 28 | 2 |

## 2. Changed values per change item

23 of 55 change items change at least one value (a comparable value in the old text that is not in the new text).
Candidate blocks that contain one of the changed values (noise of the plain value signal): median 2, max 20 (of 489 candidates).

| change | language | changed values | candidate blocks with one |
|---|---|---|---|
| C01 | en | 1 | 0 |
| C04 | en | 1 | 1 |
| C09 | en | 4 | 0 |
| C11 | en | 1 | 0 |
| C16 | en | 1 | 1 |
| C17 | en | 1 | 2 |
| C18 | en | 1 | 2 |
| C21 | en | 1 | 3 |
| C36 | th | 1 | 6 |
| C37 | th | 1 | 12 |
| C39 | th | 2 | 3 |
| XS01 | en | 1 | 5 |
| XS03 | en | 1 | 0 |
| XS04 | en | 2 | 1 |
| XS06 | en | 1 | 0 |
| XS07 | en | 1 | 4 |
| XS08 | th | 1 | 10 |
| XS09 | th | 1 | 10 |
| XS10 | th | 1 | 2 |
| XS11 | th | 1 | 1 |
| XS13 | th | 1 | 20 |
| XS14 | th | 1 | 2 |
| XS15 | th | 1 | 20 |

## 3. Review pairs

**Label source: ai** (an AI reviewer, not a person; does not count for a milestone's done check). E = shared non-hub entity; V = the review block contains a changed value; EV = same entity and attribute with the old value, while the new text gives that entity and attribute a different value (the brief's step 3 count).

| group | pairs | E | V | E or V | EV |
|---|---|---|---|---|---|
| states | 7 | 3 | 4 | 5 | 2 |
| depends | 9 | 3 | 2 | 5 | 0 |
| cites | 34 | 10 | 3 | 12 | 1 |
| historical | 11 | 11 | 7 | 11 | 7 |
| states + depends, th | 5 | 3 | 3 | 5 | 1 |
| states + depends, en | 11 | 3 | 3 | 5 | 1 |
| negatives | 2805 | 271 (0.10) | 16 (0.01) | 282 (0.10) | 3 |

## 4. Ranking all candidate blocks, same number of candidates

Expected recall@k when each change's candidate blocks are ranked by the score alone (ties in random order). entity = number of shared non-hub entities; value = number of changed values in the block.

| group | pairs | score | @5 | @10 | @20 |
|---|---|---|---|---|---|
| states + depends | 16 | entity | 0.30 | 0.35 | 0.39 |
| states + depends | 16 | entity + value | 0.46 | 0.49 | 0.56 |
| states + depends | 16 | value | 0.26 | 0.33 | 0.40 |
| states | 7 | entity | 0.36 | 0.43 | 0.44 |
| states | 7 | entity + value | 0.44 | 0.48 | 0.56 |
| states | 7 | value | 0.29 | 0.44 | 0.59 |
| depends | 9 | entity | 0.26 | 0.29 | 0.36 |
| depends | 9 | entity + value | 0.47 | 0.50 | 0.57 |
| depends | 9 | value | 0.23 | 0.24 | 0.26 |
| cites | 34 | entity | 0.05 | 0.12 | 0.20 |
| cites | 34 | entity + value | 0.10 | 0.17 | 0.25 |
| cites | 34 | value | 0.08 | 0.10 | 0.12 |
| historical | 11 | entity | 0.24 | 0.44 | 0.79 |
| historical | 11 | entity + value | 0.47 | 0.75 | 0.94 |
| historical | 11 | value | 0.46 | 0.64 | 0.65 |

Not checked: whether each extracted value and its attachment is right (no labels for values yet); the attribute rule is provisional.