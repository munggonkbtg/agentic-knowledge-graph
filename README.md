# kg-pipeline

Research prototype: build a knowledge graph over a Markdown document store
(Thai and English) and use it to find passages that need revision when a
document is updated. Everything runs locally from the command line.

Status: **M1 (Layer 0: structure)** done; next is M2 (diff).

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
| `kg stats` | Sections, blocks and `NEXT` edges per version, plus total counts |
| `kg show-blocks FILE` | Parses one file and prints each block's ID, lines and kind (writes nothing) |

Evaluation scripts live in `eval/`:

```powershell
uv run python eval/block_stability.py
```

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
