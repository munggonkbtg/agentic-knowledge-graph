# Labelling guide: MENTIONS (M4)

Agreed 2026-11-25. Used for `data/labels/m4_mentions_sample_human.csv`.

The sheet measures **extraction**: which entities a block names. Read each block
without looking at what the system found, and list every entity it names.

## How to write the answer

Column `mentions`: items separated by `;`, each `<Type> | <term as written>`.
Write `none` if the block names no entity.

Example: `Concept | ค่าชดเชย; Role | พนักงานตรวจแรงงาน`

Thai spacing inside a term does not matter.

## Types

| Type | What it is | Examples |
|---|---|---|
| Concept | A right, benefit, defined term or procedure. **Test:** it has a name that another document could use to refer to it, **and** a rule or value can be attached to it. | ค่าชดเชย, ลาเพื่อคลอดบุตร, การเปรียบเทียบ, sabbatical, performance review |
| Role | A position that the text gives duties or powers to. | อธิบดี, พนักงานตรวจแรงงาน, นายจ้าง, People Ops; "your manager" → `Role \| manager` |
| Artifact | A form, system or non-legal document. | แบบ กสร.นก. ๑, ทะเบียนลูกจ้าง, Basecamp, Airbase |
| Body | An organization: agency, committee, fund, company. | กรมสวัสดิการและคุ้มครองแรงงาน, คณะกรรมการค่าจ้าง, 37signals |
| Place | A jurisdiction. | California, Oregon |
| Other | An entity that fits none of the types above. Its share is reported; a high share means the type list is missing something. | |

Role is a position; Body is an organization.

## Rules

1. **Generic nouns are not entities:** เงิน, เอกสาร, เวลา, day, work, team.
2. **Label the longest name.** Do not also label a shorter name inside it:
   "ค่าล่วงเวลาในวันหยุด" is one entity, not also "ค่าล่วงเวลา". The exception is
   when the shorter name also appears on its own elsewhere in the block.
3. **Label hubs too** (นายจ้าง, ลูกจ้าง, manager). The hub flag is a system
   setting, not a labelling rule.
4. **Only names written in the block.** No pronouns or back-references
   ("ดังกล่าว", "the program", "they").
5. **One item per (type, term) per block**, however often it occurs.

## Not entities

- Laws and their sections. These are REFERENCES (layer 1).
- People's names.
- Bare dates and amounts. Values go on MENTIONS separately (M4 step 3).
