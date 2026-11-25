<!-- m3_references: dev set (used to tune the rules); layer 1 rule_version L1-v3 -->
# M3: REFERENCES vs the person's blind labels — dev set (used to tune the rules), L1-v3

Targets (brief): precision >= 0.9, recall >= 0.8.

| group | blocks | precision | recall | document precision | document recall |
|---|---|---|---|---|---|
| all | 77 | 0.96 | 0.93 | 0.97 | 0.94 |
| en | 27 | 1.00 | 1.00 | 1.00 | 1.00 |
| en_cue | 17 | 1.00 | 1.00 | 1.00 | 1.00 |
| en_no_cue | 10 | - | - | - | - |
| th | 50 | 0.95 | 0.90 | 0.95 | 0.88 |
| th_cue | 40 | 0.95 | 0.90 | 0.95 | 0.88 |
| th_no_cue | 10 | - | - | - | - |

## Precision by how layer 1 resolved the target

| resolution | edges | correct | precision |
|---|---|---|---|
| explicit | 47 | 45 | 0.96 |
| link | 36 | 36 | 1.00 |
| same_block_context | 4 | 3 | 0.75 |
| self_document | 22 | 21 | 0.95 |
| subject_name | 1 | 1 | 1.00 |

Unlabelled rows: 0.

## Rows where layer 1 and the person differ

| row | only layer 1 | only the person |
|---|---|---|
| R036 | 1 | 1 |
| R051 | 0 | 2 |
| R057 | 0 | 1 |
| R065 | 1 | 0 |
| R071 | 0 | 2 |
| R072 | 1 | 1 |
| R074 | 1 | 1 |