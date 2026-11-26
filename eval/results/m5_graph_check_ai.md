# M5 step 2: `kg impact` on the stored graph vs the offline experiment

**Label source: ai** (an AI reviewer, not a person; does not count for a milestone's done check). Real change items C01-C40 only (the synthetic edits are not in the graph); main needs_review pairs, historical blocks left out.

Reports: `impact_en-benefits-and-perks_20261126-112102.csv`, `impact_en-severance_en-making-a-career_20261126-114358.csv`, `impact_th-labour-protection-act-2541_th-labour-protection-act-amendment-7-2562_20261126-122534.csv`

| change | event | pairs | found in graph report | @5 | @10 | @20 |
|---|---|---|---|---|---|---|
| C01 | event1 | 1 | yes | 0 | 0 | 0 |
| C08 | event1 | 1 | yes | 1 | 1 | 1 |
| C11 | event1 | 1 | yes | 0 | 0 | 0 |
| C17 | event2 | 2 | yes | 2 | 2 | 2 |
| C18 | event2 | 2 | yes | 1 | 1 | 2 |
| C21 | event2 | 2 | yes | 2 | 2 | 2 |
| C31 | event3 | 2 | yes | 2 | 2 | 2 |
| C33 | event3 | 1 | yes | 1 | 1 | 1 |
| C34 | event3 | 2 | yes | 2 | 2 | 2 |
| C36 | event3 | 1 | yes | 1 | 1 | 1 |

**All real pairs (15):** recall@5 0.80, @10 0.80, @20 0.87. Offline experiment, graph-first, real set (15 pairs, store before each event): @5 0.80, @10 0.80, @20 1.00.

Change items whose old block has no change in the reports: none.