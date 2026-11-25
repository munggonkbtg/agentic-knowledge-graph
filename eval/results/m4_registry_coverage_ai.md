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

**Label source: ai** (an AI reviewer, not a person; does not count for a milestone's done check). Labels merged from the m5 / m5s / m5e sheets and the additions, each (change, block) pair once (eval/m5_labels.py). A pair is linked when the changed block (old + new text) and the review block share an entity that is not a hub. The registry and the hub shares are rebuilt from the store as it was at each change. **Historical** pairs (blocks of an amending act, reason notes; kg/historical.py) are left out of states / depends / all and shown apart. Negatives: (change, block) pairs of the same event labelled needs_review = no.

**automatic** = registry rules plus manual entries with source `documents` (0 so far). **+ test_pairs** adds the manual entries taken from the measured pairs (11); that row is not an independent measurement and is never a headline number.

| registry | hubs excluded above | states linked | depends linked | all linked | historical linked | negatives linked |
|---|---|---|---|---|---|---|
| automatic | none | 3/7 | 3/9 | 6/16 | 6/6 | 768/2805 (27%) |
| automatic | 0.3 | 3/7 | 3/9 | 6/16 | 6/6 | 271/2805 (10%) |
| automatic | 0.2 | 3/7 | 3/9 | 6/16 | 6/6 | 271/2805 (10%) |
| automatic | 0.15 | 3/7 | 3/9 | 6/16 | 5/6 | 172/2805 (6%) |
| automatic | 0.1 | 3/7 | 3/9 | 6/16 | 5/6 | 159/2805 (6%) |
| automatic | 0.05 | 2/7 | 1/9 | 3/16 | 1/6 | 46/2805 (2%) |
| + test_pairs | none | 4/7 | 5/9 | 9/16 | 6/6 | 852/2805 (30%) |
| + test_pairs | 0.3 | 4/7 | 5/9 | 9/16 | 6/6 | 355/2805 (13%) |
| + test_pairs | 0.2 | 4/7 | 4/9 | 8/16 | 6/6 | 289/2805 (10%) |
| + test_pairs | 0.15 | 4/7 | 4/9 | 8/16 | 5/6 | 190/2805 (7%) |
| + test_pairs | 0.1 | 4/7 | 4/9 | 8/16 | 5/6 | 159/2805 (6%) |
| + test_pairs | 0.05 | 4/7 | 2/9 | 6/16 | 4/6 | 47/2805 (2%) |

Coverage file `m4_entity_type_coverage_ai.csv` (22 change-block pairs): 22 found among the labelled pairs above; automatic registry links 12 of them at the hub cut-off 0.2 (6 historical).

Pairs by language: {'en': 11, 'th': 11}. Pairs where the changed block has no entity at all: automatic 6, + test_pairs 1.

Not checked: precision of single mentions (needs the blind MENTIONS sheet); values on MENTIONS (step 3).