# M4 step 4: registry only (A) vs registry + local LLM fallback (B)

Model `qwen3.5:4b-q4_K_M` via ollama, prompt `mentions-v1#8756913ec91f`, num_ctx 2048, temperature 0.0, think False. Fallback on blocks with at most 0 non-hub registry entities. Hubs above 0.2, recomputed with LLM mentions. Offline: nothing written to Neo4j.

**Label source: ai** (an AI reviewer, not a person; does not count for a milestone's done check). Most pairs come from synthetic edits written by the same AI reviewer that labelled them.

## 1. Review pairs linked by a shared non-hub entity

| variant | group | th | en | all |
|---|---|---|---|---|
| A | states | 2/4 | 1/3 | 3/7 |
| A | depends | 1/1 | 2/8 | 3/9 |
| A | states + depends | 3/5 | 3/11 | 6/16 |
| A | historical | 6/6 | 0/0 | 6/6 |
| A | negatives | 261/1214 (21%) | 10/1591 (1%) | 271/2805 (10%) |
| B | states | 2/4 | 2/3 | 4/7 |
| B | depends | 1/1 | 2/8 | 3/9 |
| B | states + depends | 3/5 | 4/11 | 7/16 |
| B | historical | 6/6 | 0/0 | 6/6 |
| B | negatives | 261/1214 (21%) | 29/1591 (2%) | 290/2805 (10%) |

## 2. Initial corpus: body blocks still without any entity

| variant | th | en |
|---|---|---|
| A | 126/364 | 45/74 |
| B | 88/364 | 18/74 |

Hubs in B (initial corpus): 2; LLM-sourced entities over all stores: 191.

## 3. Output quality

- LLM calls on blocks / change texts (with repeats across stores, cached after the first): 962; failures after retries: 0.
- Unique texts sent to the model (first pass, from the cache): 254; JSON valid on the first attempt: 254/254; replies with thinking text: 0. Stability calls: 171, valid on the first attempt 171, with thinking text 0.
- Terms (counted over all 962 calls, repeats included) returned 1153: dropped as not in the block 114 (10%), type Other 0, linked to a registry entity 90, new LLM-sourced 949.

## 4. Stability (second run, cache off)

- th: 126 blocks, Jaccard of LLM entity sets mean 0.91, median 1.00.
- en: 45 blocks, Jaccard of LLM entity sets mean 0.98, median 1.00.

## 5. Cost

- Seconds per unique call (first pass, as recorded when the call was made): mean 2.9, median 2.6; 254 calls, 12 min in total.
- Tokens per call: in 456, out 26.
- Stability rerun: 171 calls, mean 2.8 s.
- This run's wall time for the first pass: 3 s (small when the answers come from the cache).
- GPU memory, whole card (display included, model already loaded by the warm-up): 4951 MiB at start, peak 4960 MiB of 6144. Before the model was loaded the card used about 1,340 MiB; `ollama ps` showed the model at 3.1 GB, 100% GPU, context 2048.

## 6. Mention precision / recall

Not reported: the person's sheet `m4_mentions_sample_human.csv` has 0 answered rows. No AI copy is made.

Not checked: whether each kept LLM term is a correct entity (needs the person's MENTIONS sheet); Gemma 4 E4B (dropped: does not fit 6 GB).