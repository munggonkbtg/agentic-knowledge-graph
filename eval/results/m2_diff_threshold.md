# M2: diff results by edit-similarity threshold

Block counts per upload event. Not yet checked by a person.
Pass 2b (any section of the same document) stays at 0.8, so same-section thresholds above that value change little.

| event | threshold | unchanged | edited | moved | removed | added |
|---|---|---|---|---|---|---|
| event1 | 0.4 | 19 | 15 | 0 | 8 | 8 |
| event1 | 0.5 | 19 | 15 | 0 | 8 | 8 |
| event1 | 0.6 | 19 | 13 | 0 | 10 | 10 |
| event1 | 0.7 | 19 | 13 | 0 | 10 | 10 |
| event1 | 0.8 | 19 | 13 | 0 | 10 | 10 |
| event1 | 0.9 | 19 | 13 | 0 | 10 | 10 |
| event2 | 0.4 | 9 | 7 | 2 | 0 | 5 |
| event2 | 0.5 | 9 | 7 | 0 | 2 | 7 |
| event2 | 0.6 | 9 | 5 | 0 | 4 | 9 |
| event2 | 0.7 | 9 | 5 | 0 | 4 | 9 |
| event2 | 0.8 | 9 | 4 | 0 | 5 | 10 |
| event2 | 0.9 | 9 | 4 | 0 | 5 | 10 |
| event3 | 0.4 | 290 | 20 | 1 | 9 | 73 |
| event3 | 0.5 | 290 | 20 | 1 | 9 | 73 |
| event3 | 0.6 | 290 | 19 | 1 | 10 | 74 |
| event3 | 0.7 | 290 | 16 | 1 | 13 | 77 |
| event3 | 0.8 | 290 | 12 | 1 | 17 | 81 |
| event3 | 0.9 | 290 | 12 | 1 | 17 | 81 |

## Edited and moved pairs at threshold 0.4, lowest score first

| event | status | similarity | old block | new block |
|---|---|---|---|---|
| event1 | edited | 0.58 | `en-benefits-and-perks::Home Office Set-up::b0` | `en-benefits-and-perks::Home Office Set-up::b0` |
| event1 | edited | 0.58 | `en-benefits-and-perks::Bereavement Leave::b1` | `en-benefits-and-perks::Bereavement Leave::b1` |
| event1 | edited | 0.81 | `en-benefits-and-perks::Family Leave::b1` | `en-benefits-and-perks::Family Leave::b1` |
| event1 | edited | 0.84 | `en-benefits-and-perks::Employee Profit Sharing::b1` | `en-benefits-and-perks::Employee Profit Sharing::b1` |
| event1 | edited | 0.86 | `en-benefits-and-perks::Family Leave::b0` | `en-benefits-and-perks::Family Leave::b0` |
| event1 | edited | 0.87 | `en-benefits-and-perks::Paid Time Off > Sick Time::b1` | `en-benefits-and-perks::Paid Time Off > Paid Sick Time::b3` |
| event1 | edited | 0.87 | `en-benefits-and-perks::Flexible Spending Account (FSA)::b0` | `en-benefits-and-perks::Flexible Spending Account (FSA)::b0` |
| event1 | edited | 0.93 | `en-benefits-and-perks::Health Insurance > Medical Insurance::b2` | `en-benefits-and-perks::Health Insurance > Medical Insurance::b2` |
| event1 | edited | 0.93 | `en-benefits-and-perks::Paid Time Off > Vacation Time::b0` | `en-benefits-and-perks::Paid Time Off::b0` |
| event1 | edited | 0.97 | `en-benefits-and-perks::Expense Account::b0` | `en-benefits-and-perks::Expense Account::b0` |
| event1 | edited | 0.97 | `en-benefits-and-perks::Paid Time Off > Summer Hours::b0` | `en-benefits-and-perks::Paid Time Off > Summer Hours::b0` |
| event1 | edited | 0.99 | `en-benefits-and-perks::Paid Time Off > Sabbatical::b0` | `en-benefits-and-perks::Paid Time Off > Sabbatical::b0` |
| event1 | edited | 0.99 | `en-benefits-and-perks::Health Insurance > Health Insurance for Staff Outside the US::b0` | `en-benefits-and-perks::Health Insurance > Health Insurance for Staff Outside the US::b0` |
| event1 | edited | 0.99 | `en-benefits-and-perks::Employee Profit Sharing::b0` | `en-benefits-and-perks::Employee Profit Sharing::b0` |
| event1 | edited | 1.00 | `en-benefits-and-perks::Personal 37signals Accounts::b0` | `en-benefits-and-perks::Personal 37signals Accounts::b0` |
| event2 | moved | 0.44 | `en-making-a-career::Performance Improvement Plans::b0` | `en-severance::_::b0` |
| event2 | moved | 0.49 | `en-making-a-career::Performance Improvement Plans::b1` | `en-severance::_::b1` |
| event2 | edited | 0.52 | `en-making-a-career::Mastery & Titles::b3` | `en-making-a-career::Mastery & Titles::b5` |
| event2 | edited | 0.53 | `en-making-a-career::Mastery & Titles::b2` | `en-making-a-career::Mastery & Titles::b2` |
| event2 | edited | 0.78 | `en-making-a-career::Your First 90 Days::b2` | `en-making-a-career::Your First Year::b3` |
| event2 | edited | 0.91 | `en-making-a-career::Mastery & Titles::b1` | `en-making-a-career::Mastery & Titles::b1` |
| event2 | edited | 0.91 | `en-making-a-career::Mastery & Titles::b4` | `en-making-a-career::Mastery & Titles::b6` |
| event2 | edited | 0.91 | `en-making-a-career::Your First 90 Days::b3` | `en-making-a-career::Your First Year::b5` |
| event2 | edited | 0.97 | `en-making-a-career::Your First 90 Days::b1` | `en-making-a-career::Your First Year::b1` |
| event3 | edited | 0.50 | `th-labour-protection-act-2541::หมวด 11 ค่าชดเชย > มาตรา 120::b0` | `th-labour-protection-act-2541::หมวด 11 ค่าชดเชย > มาตรา 120::b0` |
| event3 | edited | 0.67 | `th-labour-protection-act-2541::หมวด 16 บทกำหนดโทษ > มาตรา 155/1::b0` | `th-labour-protection-act-2541::หมวด 16 บทกำหนดโทษ > มาตรา 155/1::b0` |
| event3 | edited | 0.67 | `th-labour-protection-act-2541::หมวด 5 ค่าจ้าง ค่าล่วงเวลา ค่าทำงานในวันหยุด และค่าล่วงเวลาในวันหยุด > มาตรา 53::b0` | `th-labour-protection-act-2541::หมวด 5 ค่าจ้าง ค่าล่วงเวลา ค่าทำงานในวันหยุด และค่าล่วงเวลาในวันหยุด > มาตรา 53::b0` |
| event3 | edited | 0.68 | `th-labour-protection-act-2541::หมวด 1 บททั่วไป > มาตรา 13::b0` | `th-labour-protection-act-2541::หมวด 1 บททั่วไป > มาตรา 13::b0` |
| event3 | edited | 0.76 | `th-labour-protection-act-2541::มาตรา 5::b1` | `th-labour-protection-act-2541::มาตรา 5::b1` |
| event3 | edited | 0.76 | `th-labour-protection-act-2541::หมวด 3 การใช้แรงงานหญิง > มาตรา 41::b0` | `th-labour-protection-act-2541::หมวด 3 การใช้แรงงานหญิง > มาตรา 41::b0` |
| event3 | edited | 0.78 | `th-labour-protection-act-2541::หมวด 2 การใช้แรงงานทั่วไป > มาตรา 34::b0` | `th-labour-protection-act-2541::หมวด 2 การใช้แรงงานทั่วไป > มาตรา 34::b0` |
| event3 | edited | 0.80 | `th-labour-protection-act-2541::หมวด 5 ค่าจ้าง ค่าล่วงเวลา ค่าทำงานในวันหยุด และค่าล่วงเวลาในวันหยุด > มาตรา 70::b0` | `th-labour-protection-act-2541::หมวด 5 ค่าจ้าง ค่าล่วงเวลา ค่าทำงานในวันหยุด และค่าล่วงเวลาในวันหยุด > มาตรา 70::b0` |
| event3 | edited | 0.84 | `th-labour-protection-act-2541::หมวด 5 ค่าจ้าง ค่าล่วงเวลา ค่าทำงานในวันหยุด และค่าล่วงเวลาในวันหยุด > มาตรา 75::b0` | `th-labour-protection-act-2541::หมวด 5 ค่าจ้าง ค่าล่วงเวลา ค่าทำงานในวันหยุด และค่าล่วงเวลาในวันหยุด > มาตรา 75::b0` |
| event3 | edited | 0.84 | `th-labour-protection-act-2541::หมวด 12 การยื่นคำร้องและการพิจารณาคำร้อง > มาตรา 124/1::b0` | `th-labour-protection-act-2541::หมวด 12 การยื่นคำร้องและการพิจารณาคำร้อง > มาตรา 124/1::b0` |
| event3 | edited | 0.86 | `th-labour-protection-act-2541::หมวด 16 บทกำหนดโทษ > มาตรา 145::b0` | `th-labour-protection-act-2541::หมวด 16 บทกำหนดโทษ > มาตรา 145::b0` |
| event3 | edited | 0.89 | `th-labour-protection-act-2541::หมวด 1 บททั่วไป > มาตรา 9::b0` | `th-labour-protection-act-2541::หมวด 1 บททั่วไป > มาตรา 9::b0` |
| event3 | edited | 0.91 | `th-labour-protection-act-2541::หมวด 5 ค่าจ้าง ค่าล่วงเวลา ค่าทำงานในวันหยุด และค่าล่วงเวลาในวันหยุด > มาตรา 70::b1` | `th-labour-protection-act-2541::หมวด 5 ค่าจ้าง ค่าล่วงเวลา ค่าทำงานในวันหยุด และค่าล่วงเวลาในวันหยุด > มาตรา 70::b1` |
| event3 | edited | 0.94 | `th-labour-protection-act-2541::หมวด 16 บทกำหนดโทษ > มาตรา 146::b0` | `th-labour-protection-act-2541::หมวด 16 บทกำหนดโทษ > มาตรา 146::b0` |
| event3 | edited | 0.94 | `th-labour-protection-act-2541::หมวด 11 ค่าชดเชย > มาตรา 118::b1` | `th-labour-protection-act-2541::หมวด 11 ค่าชดเชย > มาตรา 118::b1` |