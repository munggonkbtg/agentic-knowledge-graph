# Review guide: impact results (M5, workflow step 14)

The review sheets in `data/labels/reviews/review_*.csv` come from
`kg impact --check --review`. Each row is one candidate block for one change.
Only changes where the system flagged something are included (the
broken-reference rule fired, or the LLM said `needs_update`), with that
change's top 10 candidates.

The system's judgement is shown on purpose (decided 2026-11-26). Your decisions
are recorded as label source **human_review**: a person who saw the system's
output. They are kept apart from blind labels (`_human`) and do not replace
them.

## What to read in a row

1. `changed_section`, `change_old_text`, `change_new_text`: what changed. A
   blank old text means the block was added; a blank new text means it was
   removed.
2. `file`, `block_id`, `lines`, `candidate_text`: the candidate block.
3. `signals`, `rule`, `llm_verdict`, `llm_reason`, `llm_evidence`: why the
   system proposed it. `historical = True` marks an amending act or a reason
   note.

## What to write

Column `decision`, one of:

| decision | when |
|---|---|
| `needs_update` | The candidate's text must change because of this change: it repeats the old value, describes the old rule, or links to a heading or section that no longer exists. |
| `review_only` | A person should look at it, but its text stays correct (for example it cites the changed section for a rule that did not change in substance, or it depends on the changed fact without stating it). |
| `not_affected` | The change does not concern it. Also use this for historical text (amending acts, reason notes), which records what an earlier law said and never needs editing. |

Leave `decision` blank for rows you did not review; they are skipped. Use
`note` for anything unclear.

## After filling a sheet

```powershell
uv run kg review-import data/labels/reviews/<sheet>.csv
```

The decisions are added to `data/labels/reviews/review_history.csv`. If you
change a decision and import again, the new decision is added and the latest
one counts. Run `uv run kg backup-labels` after a review session.
