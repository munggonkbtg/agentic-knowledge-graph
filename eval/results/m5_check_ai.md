# M5 step 3: LLM check of the top candidates (offline)

Model `qwen3.5:4b-q4_K_M` (local, Ollama), prompt `impact-check-v1#ec05cc339469`, num_ctx 4096, temperature 0.0, think False. Top 10 candidates per change from the graph-first ranking (step 1). Nothing written to Neo4j.

**Label source: ai** (an AI reviewer, not a person; does not count for a milestone's done check). Most pairs come from synthetic edits written by the same AI reviewer. 'unjudged' candidates were never labelled, so their verdicts cannot be scored.

## Verdicts by label class

| class | checked | needs_update | unsure | not_affected | failed |
|---|---|---|---|---|---|
| positive | 45 | 21 | 0 | 24 | 0 |
| negative | 81 | 9 | 0 | 72 | 0 |
| historical | 9 | 9 | 0 | 0 | 0 |
| unjudged | 105 | 3 | 0 | 102 | 0 |

## Effect on the list

- Main needs_review pairs of these 24 changes: 50; in the top 10 before the check: 45 (0.90); kept by the check (needs_update or unsure): 21 (0.42); marked needs_update: 21 (0.42).
- needs_revision (yes / unsure) pairs: 12; checked 11, kept 8, needs_update 8.
- Kept per change: mean 1.8, median 1 of 10.
- Among kept candidates that were judged: 21/30 are labelled positive (judged negatives kept: 9).
- Evidence of kept candidates: found in the candidate 37/42, empty 0.

## Cost

- 240 checks, 235 uncached calls in 15 min; JSON valid on the first attempt 235/235; failures 0; thinking text in 0 replies.
- Per call: 3.7 s, tokens in 860, out 60.
- Tokens per change (in + out): 9007.

Not checked: verdicts on unjudged candidates; any human label; the check on the 116 changes of events 1-3 in the graph.