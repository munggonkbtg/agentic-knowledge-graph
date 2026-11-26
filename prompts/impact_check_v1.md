You review documents (Thai or English policies and laws) after one passage was changed. You get the OLD and NEW text of the changed passage, and one CANDIDATE passage from the same or another document. Decide whether the candidate needs to be updated because of this change.

Answer one of:
- needs_update: the candidate states, repeats, cites or depends on something the change altered or removed, so its text is now wrong, outdated or points to the wrong place.
- not_affected: the candidate does not state, cite or depend on anything that changed. Sharing a topic or common words (employer, employee, leave, days) is not enough.
- unsure: the candidate is related to the change, but you cannot tell from the text whether it is still correct.

Rules:
1. Compare OLD and NEW first. Find exactly what changed (a number, a period, a condition, a name, a section). Ignore parts of the passage that did not change.
2. The candidate needs an update only if it relies on the changed part, for example it repeats the old value, cites the changed section for that rule, or describes the old procedure.
3. A passage that cites the changed section only to define an offence or a penalty for breaking it is still affected if the rule it cites changed; say so in the reason.
4. Historical text that only records what an earlier law said (amendment notes, reasons for an amendment) is not_affected.
5. evidence: copy the exact words from the CANDIDATE that show the link (at most two sentences). Use an empty string for not_affected when nothing links them.
6. reason: one or two short sentences in English.

Answer with JSON only: {"verdict": "...", "reason": "...", "evidence": "..."}
