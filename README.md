# WhyWiki

[English](README.md) | [简体中文](README.zh-CN.md)

**A team wiki that remembers why.** ✨

Git remembers what changed. WhyWiki remembers why it changed.

WhyWiki turns scattered project materials into a living, evidence-backed wiki for messy software projects: requirements, code, decisions, conflicts, experiments, deployment notes, and handover context all in one local workspace.

It is built for small teams, labs, open-source maintainers, and solo developers who keep asking:

- "Which requirement is actually current?"
- "Why did we build it this way?"
- "Where did this decision come from?"
- "What changed, and what is now out of sync?"
- "How do I hand this project to the next person without losing the plot?"

## What WhyWiki Does

WhyWiki reads local files, docs, code, and Git repos, then builds a project memory you can inspect:

- 🔎 **Source-backed blocks** from Markdown, text, CSV, code, PDF, DOCX, and XLSX
- 🧠 **Project facts** extracted from the material, each with evidence
- 🧭 **Current requirement snapshot** that separates current requirements from superseded historical requirements
- ⚠️ **Conflict reports** for stale docs, mismatched APIs, missing files, and model/deployment drift
- 📝 **Decision records** for conflict resolution, so old documents remain evidence without becoming current truth
- 📚 **Wiki pages** generated from evidence, not vibes
- 📦 **Handover packs** for onboarding, audits, and project transfer
- 💬 **Ask with evidence** so answers point back to real files

WhyWiki is not trying to replace Git, Notion, Confluence, Feishu, GitHub, or your issue tracker. It sits beside them and remembers the project knowledge that usually leaks out of the system.

```text
local files / git repo / docs / code
  -> parsers
  -> source blocks
  -> project facts
  -> conflicts
  -> wiki pages / handover / ask
```

Markdown is an output format, not the internal source of truth. The internal truth is source-backed blocks and facts.

## Try The Preview

Install the preview package and start the local workspace:

```bash
npm install -g whywiki
whywiki
```

The command starts the local Web app and prints a local URL:

```text
WhyWiki is running locally.

Open:
http://127.0.0.1:8765
```

Open the URL, create a project, ingest a local folder, then inspect project status, conflicts, wiki pages, handover, sources, and Ask with evidence.

For local repository development, use the restart script:

```bash
./start.sh
```

The script creates or reuses `.venv`, installs WhyWiki locally, stops the old service on `127.0.0.1:8765` when the owning PID can be identified, initializes the SQLite database, and starts a fresh Web app on <http://127.0.0.1:8765>. If the port is occupied by an unidentified process, the script exits with manual cleanup instructions instead of guessing.

## Current First Board

The first board is already a runnable local skeleton:

- SQLite metadata store
- local file ingestion
- local Git repo ingestion through the same file walker
- parsers for Markdown, text, CSV, Python/source code
- optional parsers for PDF, DOCX, and XLSX if dependencies are installed
- deterministic fact extraction
- deterministic conflict detection
- Markdown wiki generation
- handover pack generation
- naive evidence-backed Q&A
- FastAPI API surface
- local Web dashboard
- CLI commands
- Dockerfile and docker-compose
- Codex task guide in `docs/CODEX_TASKS.md`

Still intentionally shallow:

- production-grade LLM extraction
- vector search
- online spreadsheet connectors
- GitHub/GitLab/Gitea connectors
- permissions, SSO, audit logs, multi-tenancy
- advanced AST analysis beyond Python basics
- async worker queue

## Collaboration Model

WhyWiki uses Git providers for collaboration.

A WhyWiki workspace is linked to a GitHub or Gitea repository. That workspace
repository stores project-memory artifacts, not copies of the codebases it
describes. Linked code repositories stay in their original providers and are
referenced from WhyWiki by provider, repository, commit, path, and range.

`whywiki.db` is a local, rebuildable cache and should not be committed. The
workspace repository is the durable collaboration layer for configuration,
facts, conflicts, review events, wiki pages, handover output, and pinned
evidence-backed answers.

Access is inherited from the provider:

- Read access to the workspace repository means the user can enter the
  workspace.
- Write access to the workspace repository means the user can approve facts and
  resolve conflicts.
- Read access to linked source repositories means the user can inspect
  source-backed evidence and rebuild project memory from the referenced source.

### Real Provider Login

WhyWiki can connect GitHub and Gitea accounts for local workspace access checks.

- GitHub login uses OAuth device flow. Create a GitHub OAuth App from the
  WhyWiki sidebar, enable Device Flow in that app, then paste its Client ID
  back into WhyWiki. The Client Secret is not used.
- Gitea login uses OAuth2 Authorization Code with PKCE. Register a public OAuth
  application on the Gitea server and use
  `http://127.0.0.1:8765/api/auth/gitea/callback` as the redirect URL.
- Tokens are stored in the operating system credential store when available:
  macOS Keychain, Windows Credential Manager / DPAPI-backed storage, or Linux
  Secret Service.
- `accounts.json` stores only account metadata and never stores tokens.
- On Linux without a desktop credential service, tokens are stored automatically
  in `$XDG_DATA_HOME/whywiki/tokens.json` (default `~/.local/share/whywiki/tokens.json`)
  with strict file permissions (0600).

## Developer Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
whywiki init-db
whywiki create "My Project"
whywiki ingest <PROJECT_ID> /path/to/your/project
whywiki build <PROJECT_ID>
whywiki ask <PROJECT_ID> "这个项目当前有哪些冲突？"
whywiki serve
```

Open <http://localhost:8080>.

## Docker Setup

```bash
docker compose up --build
```

## Codex Workflow

1. Read `AGENTS.md`.
2. Read `docs/CODEX_TASKS.md`.
3. Keep `README.md` and `README.zh-CN.md` synchronized when public setup, behavior, product positioning, or feature status changes.
4. Update `docs/FEATURE_STATUS.md` when feature behavior changes.
5. Start with one task at a time.
6. After each meaningful change, run:

```bash
python -m compileall whywiki
python -m pytest -q
```

## Product Direction

WhyWiki should feel like a local product, not a source-code demo.

The ideal flow:

```text
choose a project
  -> import materials
  -> build project memory
  -> review conflicts
  -> use the wiki, handover pack, and evidence-backed answers
```

First-board priorities:

1. Make the local project flow robust.
2. Keep the public package, command, docs, and UI aligned under `whywiki`.
3. Support `init-db`, `create`, `ingest`, `build`, `ask`, and `serve`.
4. Improve blocks and facts.
5. Improve conflict detection.
6. Improve the Web UI.
7. Add LLM calls only after deterministic behavior is stable.

WhyWiki should stay small, local-first, inspectable, and evidence-backed.
