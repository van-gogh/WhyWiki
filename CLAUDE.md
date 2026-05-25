# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

WhyWiki is a local-first project memory tool that reads files, docs, code, and Git repos, then builds an evidence-backed wiki. The core loop: ingest materials → extract source blocks → derive facts with evidence pointers → detect conflicts → generate wiki pages / handover packs / evidence-backed answers.

Markdown is a rendered output format, not the internal source of truth. The internal truth is source-backed blocks and facts stored in SQLite.

## Development Commands

```bash
# Quick start (creates .venv, installs, restarts service on :8765)
./start.sh

# Manual setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Initialize database
whywiki init-db

# Run the web app (dev)
whywiki serve --host 127.0.0.1 --port 8765

# Verify after changes (run both)
python -m compileall whywiki
python -m pytest -q

# Run a single test
python -m pytest tests/test_basic_flow.py -q

# Run tests matching a keyword
python -m pytest -k "conflict" -q
```

## Architecture

### Data Flow

```
local files / git repo
  → connectors (local_files, git_repo)
  → parsers (markdown, code, csv, pdf, docx, xlsx, plaintext)
  → source blocks (stored in SQLite)
  → fact_extractor → facts with evidence pointers
  → conflict_detector → conflicts
  → wiki_engine → wiki pages
  → handover → handover packs
  → ask → evidence-backed Q&A
```

### Key Layers

- **`whywiki/connectors/`** — File discovery. `LocalFilesConnector` walks directories; `GitRepoConnector` walks git repos. Both yield file paths for parsers.
- **`whywiki/parsers/`** — Turn files into `ParsedBlock` objects. Each parser handles one format. Heavy deps (pypdf, python-docx, openpyxl) are imported at use time.
- **`whywiki/services/`** — Core business logic. `ingest` orchestrates connectors+parsers into SQLite. `fact_extractor`, `conflict_detector`, `wiki_engine`, `handover`, `ask` operate on stored blocks/facts.
- **`whywiki/collaboration/`** — Git provider integration (GitHub/Gitea OAuth, accounts, tokens, workspace artifacts). Workspace repos store project-memory artifacts, not source code copies.
- **`whywiki/app.py`** — FastAPI web API and static file serving.
- **`whywiki/cli.py`** — CLI entry point (`whywiki` command). Subcommands: `init-db`, `create`, `ingest`, `build`, `ask`, `serve`, `log`, `stop`, plus collaboration commands.
- **`whywiki/db.py`** — SQLite connection, schema creation, migrations via `apply_migrations()`.
- **`whywiki/config.py`** — Data directory resolution. Controlled by `WHYWIKI_DATA_DIR` env var (defaults to `.whywiki`).
- **`whywiki/runtime.py`** — Process lifecycle management (port selection, PID tracking, log tailing).
- **`whywiki/models.py`** — Core dataclasses: `ParsedBlock`, `EvidencePointer`.

### npm Package

The npm package (`npm/whywiki.js`) is a thin Node.js launcher that finds a system Python and runs `python -m whywiki.cli`. It sets `PYTHONPATH` to the package root so the bundled Python source is importable without pip install.

### Storage

- `WHYWIKI_DATA_DIR` (default `.whywiki/`) holds `whywiki.db`, project output dirs, auth state, and workspace artifacts.
- `whywiki.db` is a rebuildable cache — never commit it.
- The workspace repository (via git provider) is the durable collaboration layer.

## Environment Variables

- `WHYWIKI_DATA_DIR` — data directory path (default: `.whywiki`)
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` — optional LLM integration
- `WHYWIKI_GITHUB_CLIENT_ID` — GitHub OAuth device flow


## Key Conventions

- Every user-facing conclusion must have an evidence pointer back to a real file/block.
- Keep functions testable without FastAPI — services take `sqlite3.Connection` parameters.
- Heavy optional dependencies are imported lazily inside functions.
- `README.md` and `README.zh-CN.md` are a synchronized pair — update both when public-facing content changes.
- Update `docs/FEATURE_STATUS.md` when feature behavior changes.
- UI work must follow `docs/ui_ux_guidelines.md`.
- LLM features enhance deterministic paths, never replace them.
- Schema changes require migration strategy in `db.py:apply_migrations()` — never ask users to delete data.
