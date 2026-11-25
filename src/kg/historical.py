"""Historical text: blocks that restate earlier wording and never need editing.

Decided 2026-11-25 (docs/plan.md): such blocks are not counted as needs_review
in the main numbers, and are reported as their own row.

Rules (plain text rules, no model):
* document: an amending act, i.e. a Thai act whose title carries "(ฉบับที่ N)"
  (T2, พระราชบัญญัติคุ้มครองแรงงาน (ฉบับที่ 7) พ.ศ. 2562). It quotes the wording
  it replaces and inserts.
* block: a reason note appended to a consolidated act, starting with
  "หมายเหตุ :- เหตุผลในการประกาศใช้" (one per amending act at the end of T1).
"""

from __future__ import annotations

import re
import unicodedata

AMENDING_ACT = re.compile(r"^พระราชบัญญัติ.*\(ฉบับที่\s*[0-9๐-๙]+\)")
REASON_NOTE = re.compile(r"^หมายเหตุ\s*:?-?\s*เหตุผลในการประกาศใช้")


def historical_reason(document_title: str, block_text: str) -> str | None:
    """'amending_act', 'reason_note' or None."""
    if AMENDING_ACT.search(unicodedata.normalize("NFC", document_title.strip())):
        return "amending_act"
    if REASON_NOTE.search(unicodedata.normalize("NFC", block_text.strip())):
        return "reason_note"
    return None
