# M1: block ID stability on the 3 version pairs

Counts of OLD blocks by what happens to them in the NEW version. Exact matching only; not yet checked by a person.

## configured (title out of path, markers stripped, digits unified)

| pair | old blocks | new blocks | same uid | moved | edited in place | unmatched | text unchanged (uid+moved) |
|---|---|---|---|---|---|---|---|
| E1 | 42 | 42 | 19 | 0 | 13 | 10 | 19 (45%) |
| E3 (+E2) | 18 | 23 | 8 | 1 | 4 | 5 | 9 (50%) |
| T1 | 325 | 351 | 232 | 63 | 28 | 2 | 295 (91%) |

## title heading kept in path

| pair | old blocks | new blocks | same uid | moved | edited in place | unmatched | text unchanged (uid+moved) |
|---|---|---|---|---|---|---|---|
| E1 | 42 | 42 | 19 | 0 | 13 | 10 | 19 (45%) |
| E3 (+E2) | 18 | 23 | 8 | 1 | 4 | 5 | 9 (50%) |
| T1 | 325 | 351 | 0 | 295 | 0 | 30 | 295 (91%) |

## no text normalization (markers and Thai digits kept)

| pair | old blocks | new blocks | same uid | moved | edited in place | unmatched | text unchanged (uid+moved) |
|---|---|---|---|---|---|---|---|
| E1 | 42 | 42 | 19 | 0 | 13 | 10 | 19 (45%) |
| E3 (+E2) | 18 | 23 | 8 | 1 | 4 | 5 | 9 (50%) |
| T1 | 325 | 351 | 175 | 4 | 136 | 10 | 179 (55%) |
