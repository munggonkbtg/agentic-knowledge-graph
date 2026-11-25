<!-- m3_references_test: test set (held out); layer 1 rule_version L1-v3 -->
# M3: REFERENCES vs the person's blind labels — test set (held out), L1-v3

Targets (brief): precision >= 0.9, recall >= 0.8.

| group | blocks | precision | recall | document precision | document recall |
|---|---|---|---|---|---|
| all | 60 | 0.94 | 0.94 | 0.87 | 0.87 |
| en | 10 | - | - | - | - |
| en_no_cue | 10 | - | - | - | - |
| th | 50 | 0.94 | 0.94 | 0.87 | 0.87 |
| th_cue | 40 | 0.94 | 0.94 | 0.87 | 0.87 |
| th_no_cue | 10 | - | - | - | - |

## Precision by how layer 1 resolved the target

| resolution | edges | correct | precision |
|---|---|---|---|
| explicit | 36 | 33 | 0.92 |
| issued_under | 25 | 25 | 1.00 |
| name_without_year | 3 | 0 | 0.00 |
| self_document | 60 | 59 | 0.98 |

Unlabelled rows: 0.

## Rows where layer 1 and the person differ

| row | only layer 1 | only the person |
|---|---|---|
| R003 | 0 | 1 |
| R010 | 1 | 0 |
| R026 | 3 | 1 |
| R028 | 1 | 2 |
| R035 | 0 | 1 |
| R039 | 0 | 1 |
| R042 | 0 | 1 |
| R047 | 1 | 0 |
| R052 | 1 | 0 |