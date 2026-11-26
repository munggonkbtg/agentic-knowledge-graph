# Labelling guide: DEPENDS (M7) — DRAFT

Draft written 2026-11-26 for the user's review. It matches the instruction the
local LLM gets (`prompts/depends_v1.md`), so labels and the system judge the
same question.

## The question

For two passages A and B: does one of them **use a fact stated in the other
without citing it**, so that if the fact changed, the dependent passage could
become wrong?

## Label

| label | when |
|---|---|
| `a_on_b` | A relies on a fact, rule or value stated in B, without citing B. |
| `b_on_a` | The other way round. |
| `none` | No dependency (see below). |

With `a_on_b` or `b_on_a`, also copy:

- `fact`: the fact in a few words;
- `evidence_dependent`: the exact words of the dependent passage that rely on it;
- `evidence_source`: the exact words of the other passage that state it.

## It is a dependency when

- B states a period, amount or condition, and A relies on it without
  repeating or citing it. Example: B "sick leave of three working days or more
  needs a medical certificate"; A "after a short illness you do not need to
  bring a certificate".
- B defines a right or procedure, and A explains how to use it assuming B's
  rule.

## It is not a dependency when

- The passages only share a topic or common words (employer, employee, leave).
- A cites B by section number or link. That is a citation (REFERENCES).
- Both passages state the same rule. That is a repetition, found through
  shared entities and values. Label `none` unless one clearly builds on the
  other.
- One passage is historical text (amending act, reason note).

## Questions for the user

1. Should a dependency inside the same document count, or only across
   documents? The system currently allows both.
2. Is a repetition of the same value (states) ever a dependency, or always
   `none`?
