# kg-pipeline

Research prototype: build a knowledge graph over a Markdown document store
(Thai and English) and use it to find passages that need revision when a
document is updated. Everything runs locally from the command line.

Status: M0-M1 done; M2 (diff) and M3 (layer 1) built, **not verified**: their
label sheets were answered by an AI reviewer, and no person has labelled yet.
Plan, decisions, label provenance and open items: [docs/plan.md](docs/plan.md).

## 1. One-time setup

### Python environment

This project uses [uv](https://docs.astral.sh/uv/) to manage a *virtual
environment* (a private set of packages used only by this project).

```powershell
uv sync
```

This creates `.venv/` and installs everything listed in `pyproject.toml`.
Run project commands through uv so they use that environment:

```powershell
uv run kg --help
```

### Neo4j (graph database)

1. Install **Neo4j Desktop** from https://neo4j.com/download/ (it bundles its
   own Java, so you do not need to install Java separately).
2. In Neo4j Desktop, create a new local instance (any name), set a password,
   and start it.
3. Copy `.env.example` to `.env` and put the password you chose into
   `NEO4J_PASSWORD`. `.env` is ignored by git; never commit it.

```powershell
Copy-Item .env.example .env
```

4. Check the connection. This creates one test node, reads it back and
   deletes it:

```powershell
uv run kg ping
```

5. Create the constraints and indexes the pipeline relies on (safe to rerun):

```powershell
uv run kg init-schema
```

## 2. Commands

| Command | What it does |
|---|---|
| `kg ping` | Connects to Neo4j, creates/reads/deletes a test node |
| `kg init-schema` | Creates uniqueness constraints and indexes (idempotent) |
| `kg analyzers` | Lists the full-text analyzers Neo4j offers (checks for Thai support) |
| `kg build --layer 0 [--corpus DIR] [--as-of DATE]` | Parses every `.md` file in DIR (default `data/initial_corpus`) and writes Document → Version → Section → Block with `HAS_VERSION`, `CONTAINS`, `NEXT`. One transaction per file; rerunning changes nothing. |
| `kg stats` | Sections, blocks and `NEXT` edges per version, entities and open MENTIONS per language / type / hub, plus total counts |
| `kg show-blocks FILE` | Parses one file and prints each block's ID, lines and kind (writes nothing) |
| `kg upload --event DIR [--as-of DATE]` | Identifies each file (doc_key in front matter, else by text similarity; unsure files go to `data/labels/doc_identification_queue.csv` for a person). Then uploads new versions: diffs each file against its current version in the graph, writes the new version (one transaction per file), reuses the node of every unchanged block, adds `SUPERSEDES`, sets the old version's `valid_to` and updates `Document.title`. Files already uploaded are skipped. |
| `kg build --layer 1` | REFERENCES for the current version of every document in the graph: regex + document registry, one edge per cited section, stub documents for laws not in the store (rules in `docs/plan.md`). Rerunning changes nothing. |
| `kg build --layer 2` | Entity layer (M4): builds the entity registry from the current version of every document in the graph (Thai definitions, headings, regulation subjects, and `registry/entities_manual.yaml`), flags hubs (`layer2.hub_block_share`), and writes `Entity`, `Alias` -[`ALIAS_OF`]-> `Entity` and `Block` -[`MENTIONS`]-> `Entity` with provenance. Values (number + unit, `src/kg/values.py`) are lists on the MENTIONS edge of the nearest non-hub entity; values in a block without one are `unattached_*` on the Block. Rerunning changes nothing; a new `layer2.rule_version` closes older edges. |
| `kg embed` | Writes e5 embeddings (`embedding` in config.yaml) on the body blocks of every document's current version that lack one; `kg init-schema` creates the vector index. Needs the `embed` group: `uv run --group embed kg embed`. |
| `kg impact --doc KEY [--doc KEY ...]` | Impact analysis for the current version of uploaded documents: change items from the stored diff, candidates from the graph (valid REFERENCES, MENTIONS and values) and hybrid search (trigrams + e5 vector index), ranked by `impact.ranking`. Writes the top `impact.top_n` per change to a CSV in `data/reports/` (not in git). Needs the `embed` group. |
| `kg registry` | Lists the names and file names each document can be cited by (add reviewed extra names in `registry/aliases.yaml`) |
| `kg backup-labels` | Copies `data/labels/` (not in git) to a dated folder outside the repository: `~/kg_label_backups/labels-<date>-<time>`, or `KG_LABEL_BACKUP_DIR`. Every sheet generator in `eval/` does the same before writing. |
| `kg reset --yes` | Deletes all pipeline nodes (Document, Version, Section, Block, Alias, Entity). Constraints and indexes stay. Cannot be undone. |
| `kg diff --event DIR [--event DIR ...] [--review-out CSV]` | Matches uploaded files against their previous versions in `data/initial_corpus` (unchanged / edited / moved / removed / added) and optionally writes a review sheet for a person. Writes nothing to Neo4j. |

Evaluation scripts live in `eval/` and write counts (no document text) to `eval/results/`:

```powershell
uv run python eval/block_stability.py
```
```powershell
uv run python eval/diff_threshold.py
```
```powershell
uv run python eval/diff_agreement.py
```

Blind check of the diff (the person never sees the diff's answers). Answers
are kept apart by who gave them: `<sheet>_human.csv` (a person) and
`<sheet>_ai.csv` (an AI reviewer). Only a person's answers count for "done".
Scoring scripts take `--labels human | ai | both` (default both) and name the
source in each result file:

```powershell
uv run python eval/make_blind_sheet.py
```
```powershell
uv run python eval/blind_agreement.py
```

REFERENCES (M3), blind labels then precision / recall:

```powershell
uv run python eval/make_references_sheet.py
```
```powershell
uv run python eval/references_agreement.py
```

For the diff, the first writes `data/labels/m2_blind_sample.csv` (30 old blocks to answer;
copy it to `m2_blind_sample_human.csv` before answering),
`m2_blind_new_blocks.csv` (every block of the uploaded files, with refs) and
`m2_blind_key.json`. See the docstring of `eval/make_blind_sheet.py` for how
to fill in `answer` and `new_refs`.

### How blocks are identified (Layer 0)

- `block_id` = `doc_key::Heading > Subheading::b<position in section>`, for example
  `th-labour-protection-act-2541::หมวด 2 การใช้แรงงานทั่วไป > มาตรา 34::b0`.
  Headings are normalized: footnote markers like `[๔๒]` removed, Thai digits
  turned into Arabic. A single `#` title heading is left out of the path
  (`layer0.title_heading_in_path` in `config.yaml`).
- `content_hash` = SHA-256 of the normalized block text (same rules, plus
  whitespace collapsed). Original text is kept unchanged in `text`.
- `block_uid` = `block_id#<first 12 hex chars of content_hash>` is the node key,
  so the same text at the same position reuses one node across versions.
- A top-level list longer than `layer0.split_list_over_chars` (1,500) becomes
  one block per top-level item (`kind = list_item`); shorter lists stay one block.
- Blocks under a heading in `layer0.footnote_sections` (`เชิงอรรถ`) get
  `role = footnote`; all others get `role = body`. Later layers skip footnotes.
- Line ranges are 1-based, inclusive, and count the front matter. They are
  stored on the `Section-[:CONTAINS]->Block` relationship, because one Block
  node can belong to several versions.

## 3. Tests

```powershell
uv run pytest
```

Tests marked `neo4j` run only when `NEO4J_URI`, `NEO4J_USER` and
`NEO4J_PASSWORD` are set (for example from `.env`) and are skipped otherwise.

## 4. Data

Document files live in `data/` and are **not** committed: the English pilot
files have no license and must not be redistributed. See `data/README.md`.
