# M3: document identification without doc_key

Thresholds: accept text >= 0.7 with margin >= 0.2; new below 0.45.
Upload files present: no (only the initial corpus was tested; the T2 / E2 cases need data/uploads)

| set | file | expected | outcome | best candidate (text / blocks / title / file) |
|---|---|---|---|---|
| initial, leave-one-out | E1_benefits_and_perks__2024-01-05_before_sabbatical_change.md | new | right | en-making-a-career: 0.36 / 0.00 / 0.32 / 0.54 |
| initial, self | E1_benefits_and_perks__2024-01-05_before_sabbatical_change.md | en-benefits-and-perks | right | en-benefits-and-perks: 1.00 / 1.00 / 1.00 / 1.00 |
| initial, leave-one-out | E3_making_a_career__2024-05-14_before_severance_move.md | new | right | en-state-leave-provisions: 0.40 / 0.00 / 0.32 / 0.29 |
| initial, self | E3_making_a_career__2024-05-14_before_severance_move.md | en-making-a-career | right | en-making-a-career: 1.00 / 1.00 / 1.00 / 1.00 |
| initial, leave-one-out | E4_getting_started.md | new | right | en-making-a-career: 0.39 / 0.00 / 0.47 / 0.26 |
| initial, self | E4_getting_started.md | en-getting-started | right | en-getting-started: 1.00 / 1.00 / 1.00 / 1.00 |
| initial, leave-one-out | E5_state_leave_provisions.md | new | right | en-making-a-career: 0.40 / 0.00 / 0.32 / 0.29 |
| initial, self | E5_state_leave_provisions.md | en-state-leave-provisions | right | en-state-leave-provisions: 1.00 / 1.00 / 1.00 / 1.00 |
| initial, leave-one-out | T1_labour_protection_act_2541__2017-08-31.md | new | right | th-regulation-criminal-proceedings-2558: 0.33 / 0.00 / 0.45 / 0.43 |
| initial, self | T1_labour_protection_act_2541__2017-08-31.md | th-labour-protection-act-2541 | right | th-labour-protection-act-2541: 1.00 / 1.00 / 1.00 / 1.00 |
| initial, leave-one-out | T3_ministerial_regulation_no9_2541.md | new | right | th-regulation-workplace-inspection-2542: 0.35 / 0.00 / 0.48 / 0.52 |
| initial, self | T3_ministerial_regulation_no9_2541.md | th-ministerial-regulation-9-2541 | right | th-ministerial-regulation-9-2541: 1.00 / 1.00 / 1.00 / 1.00 |
| initial, leave-one-out | T4_regulation_workplace_inspection_2542.md | new | right | th-ministerial-regulation-9-2541: 0.35 / 0.00 / 0.48 / 0.52 |
| initial, self | T4_regulation_workplace_inspection_2542.md | th-regulation-workplace-inspection-2542 | right | th-regulation-workplace-inspection-2542: 1.00 / 1.00 / 1.00 / 1.00 |
| initial, leave-one-out | T5_regulation_criminal_proceedings_2558.md | new | right | th-labour-protection-act-2541: 0.33 / 0.00 / 0.45 / 0.43 |
| initial, self | T5_regulation_criminal_proceedings_2558.md | th-regulation-criminal-proceedings-2558 | right | th-regulation-criminal-proceedings-2558: 1.00 / 1.00 / 1.00 / 1.00 |

| set | right | wrong | sent to a person |
|---|---|---|---|
| initial, leave-one-out | 8 | 0 | 0 |
| initial, self | 8 | 0 | 0 |