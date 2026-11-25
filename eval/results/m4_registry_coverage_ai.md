# M4: entity registry without an LLM

Initial corpus, 95 entities, 1062 mentions (one per block and entity) over 438 body blocks (en 74, th 364).

## Registry

| language | type | entities | never mentioned |
|---|---|---|---|
| en | Concept | 35 | 15 |
| en | Place | 5 | 0 |
| th | Body | 3 | 0 |
| th | Concept | 41 | 7 |
| th | Role | 11 | 0 |

Sources (an entity can have several): definition 33, heading 65, title 3

Body blocks by number of entities mentioned:

| language | 0 | 1 | 2 | 3+ |
|---|---|---|---|---|
| en | 45 | 18 | 10 | 1 |
| th | 77 | 58 | 56 | 173 |

## Hub distribution

Share of the body blocks of the entity's language that mention it.

| cut-off (share >) | th hubs | en hubs |
|---|---|---|
| 0.3 | 2 | 0 |
| 0.2 | 2 | 0 |
| 0.15 | 4 | 0 |
| 0.1 | 6 | 0 |
| 0.05 | 17 | 2 |

Thai entities above 0.05:

| entity | type | share |
|---|---|---|
| นายจ้าง | Role | 0.459 |
| ลูกจ้าง | Role | 0.451 |
| ค่าจ้าง | Concept | 0.184 |
| สวัสดิการ | Concept | 0.154 |
| พนักงานตรวจแรงงาน | Role | 0.110 |
| ความปลอดภัย | Concept | 0.104 |
| รัฐมนตรี | Role | 0.099 |
| อธิบดี | Role | 0.077 |
| วันหยุด | Concept | 0.074 |
| กองทุนสงเคราะห์ลูกจ้าง | Body | 0.071 |
| พนักงานเจ้าหน้าที่ | Role | 0.069 |
| อาชีวอนามัย | Concept | 0.066 |
| ค่าทำงานในวันหยุด | Concept | 0.063 |
| สภาพแวดล้อมในการทำงาน | Concept | 0.063 |
| ค่าล่วงเวลาในวันหยุด | Concept | 0.060 |
| ค่าล่วงเวลา | Concept | 0.058 |
| วันทำงาน | Concept | 0.055 |

English: highest shares 0.081, 0.054, 0.041 (names in the detail file, not in git).

## Coverage of review pairs (states / depends)

**Label source: ai** (an AI reviewer, not a person; does not count for a milestone's done check). A pair is linked when the changed block (old + new text) and the review block share an entity that is not a hub. The registry and the hub shares are rebuilt from the store as it was at each change (initial corpus plus earlier uploads). Negatives: (change, block) pairs of the same event labelled needs_review = no.

**With the manual file:** its entries are the continuation brief's examples, which were taken from these same pairs, so that row is not an independent measurement.

| registry | hubs excluded above | states linked | depends linked | all linked | negatives linked |
|---|---|---|---|---|---|
| automatic only | none | 9/13 | 2/7 | 11/20 | 768/2805 (27%) |
| automatic only | 0.3 | 9/13 | 2/7 | 11/20 | 271/2805 (10%) |
| automatic only | 0.2 | 9/13 | 2/7 | 11/20 | 271/2805 (10%) |
| automatic only | 0.15 | 8/13 | 2/7 | 10/20 | 172/2805 (6%) |
| automatic only | 0.1 | 8/13 | 2/7 | 10/20 | 159/2805 (6%) |
| automatic only | 0.05 | 3/13 | 1/7 | 4/20 | 46/2805 (2%) |
| with manual file | none | 10/13 | 4/7 | 14/20 | 852/2805 (30%) |
| with manual file | 0.3 | 10/13 | 4/7 | 14/20 | 355/2805 (13%) |
| with manual file | 0.2 | 10/13 | 3/7 | 13/20 | 289/2805 (10%) |
| with manual file | 0.15 | 9/13 | 3/7 | 12/20 | 190/2805 (7%) |
| with manual file | 0.1 | 9/13 | 3/7 | 12/20 | 159/2805 (6%) |
| with manual file | 0.05 | 8/13 | 2/7 | 10/20 | 47/2805 (2%) |

Pairs by language: {'en': 10, 'th': 10}. Pairs where the changed block has no entity at all: automatic only 6, with manual file 1.

Not checked: precision of single mentions (needs the blind MENTIONS sheet); the brief's 19-pair file; values on MENTIONS (step 3).