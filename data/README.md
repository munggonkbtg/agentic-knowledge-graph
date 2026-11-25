# data/

Everything in this folder except this README is ignored by git, because the
English pilot files have no license and must not be redistributed.

Planned layout (filled in M1):

- `initial_corpus/` – the 8 files of the starting corpus
- `uploads/event1/`, `event2/`, `event3/` – files uploaded in each upload event
  (not present now: added when an upload event is run)
- `labels/` – human labels (gold edges, change test sets); not present now

Current state (2026-11-25): only `initial_corpus/` exists, and the Neo4j graph
holds only those 8 documents (`kg build --layer 0 --as-of 2024-01-01`).
