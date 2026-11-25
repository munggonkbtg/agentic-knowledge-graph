# Test fixtures (committed)

These small files let the Layer 0 and diff tests run on a fresh clone, where
`data/` is empty. Tests that use the full pilot files still skip without `data/`.

| File | Source | License |
|---|---|---|
| `th_lpa_old.md` | Excerpt of พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541, version of 31/08/2560 (ThaiLaw v0.2, source_id 830948): มาตรา ๑๑/๑, ๓๔, ๓๕, ๑๑๘ and the footnote entries they cite | CC0-1.0 |
| `th_lpa_new.md` | Same sections from the latest version in ThaiLaw v0.2 (source_id 642571) | CC0-1.0 |
| `th_inspection_arabic_digits.md` | ข้อ 1–2 of ระเบียบกระทรวงแรงงานฯ ว่าด้วยการตรวจสอบสถานประกอบกิจการ พ.ศ. 2542 (source_id 322766), which uses Arabic digits | CC0-1.0 |
| `en_policy_old.md`, `en_policy_new.md`, `en_severance_new.md` | Synthetic text written for these tests | n/a |

The Thai excerpts are copied line for line from the pilot files; only the front
matter was rewritten (fixture `doc_key`, note that it is an excerpt).

The English pilot files (37signals handbook) have no license and must not be
redistributed, so the English fixtures are written from scratch. They reproduce
the *kinds* of change seen in the pilot (heading renamed, paragraph inserted,
paragraph moved within the document and edited, paragraph moved to a new
document, fact changed from 30 days to 6 weeks), not its text.

Do not add any text from `data/` here unless its license allows redistribution.
