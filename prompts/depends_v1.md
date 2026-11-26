You read two passages from workplace policy documents and labour laws (Thai or English). Decide whether one passage DEPENDS on a fact stated in the other: it uses that fact, rule or value without citing the passage, so that if the fact changed, the dependent passage could become wrong.

Examples of a dependency:
- B states a period, amount or condition ("sick leave of three working days needs a medical certificate"), and A relies on it without repeating or citing it ("employees who return after a short illness do not need to bring a certificate").
- B defines a right or procedure, and A describes how to use it, assuming B's rule.

Not a dependency:
- The passages only share a topic or words (employer, employee, leave).
- A cites B by section number or link (that is a citation, handled elsewhere).
- Both passages state the same rule independently (that is a repetition, handled elsewhere), unless one clearly builds on the other.

Answer:
- direction: "a_on_b" if A depends on B, "b_on_a" if B depends on A, "none" otherwise.
- fact: the fact the dependent passage relies on, in a few words (English). Empty for none.
- evidence_dependent: copy the exact words from the dependent passage that rely on the fact. Empty for none.
- evidence_source: copy the exact words from the other passage that state the fact. Empty for none.

Answer with JSON only: {"direction": "...", "fact": "...", "evidence_dependent": "...", "evidence_source": "..."}
