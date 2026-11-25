# kg-pipeline

Research prototype: build a knowledge graph over a Markdown document store
(Thai and English) and use it to find passages that need revision when a
document is updated. Everything runs locally from the command line.

Status: **M0 (setup)**.

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

## 3. Tests

```powershell
uv run pytest
```

Tests marked `neo4j` run only when `NEO4J_URI`, `NEO4J_USER` and
`NEO4J_PASSWORD` are set (for example from `.env`) and are skipped otherwise.

## 4. Data

Document files live in `data/` and are **not** committed: the English pilot
files have no license and must not be redistributed. See `data/README.md`.
