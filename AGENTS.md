# AGENTS.md

This repository is designed to be developed with Codex or similar agentic coding tools.

## Product direction

Build an open-source WhyWiki for small teams, labs, open-source projects, and messy software projects.

Do not turn it into:

- a generic RAG chatbot
- a GitHub/GitLab/Gitea replacement
- a Confluence/Notion/Feishu replacement
- an enterprise suite in the first version
- a graph visualization product

Core principle:

```text
Git remembers code changes.
WhyWiki remembers project knowledge and why the project changed.
```

## Current architecture

```text
local files / git repo / docs / code
  -> parsers
  -> source blocks
  -> deterministic or LLM-assisted facts
  -> conflicts, wiki pages, handover, ask
```

Markdown is a rendered output. Preserve evidence pointers to original files, pages, sheets, ranges, or code symbols.

## Coding standards

- Prefer small modules with clear boundaries.
- Avoid hidden global state except the configured data directory.
- Keep functions testable without FastAPI.
- Every user-facing conclusion should have an evidence pointer.
- Avoid overengineering enterprise features.
- Add tests when adding behavior.
- Use type hints where practical.
- Keep optional heavy dependencies imported lazily.

## Product-grade code discipline

Treat the repository as product code, not a prototype sandbox.

- Keep the codebase clean, direct, and easy to inspect.
- Every piece of code should be real, reachable, and useful. Do not leave dead code, duplicate paths, placeholder branches, or obsolete implementations beside the new implementation.
- When replacing or optimizing a feature, remove or migrate the old path instead of keeping old and new behavior in parallel unless there is an explicit compatibility requirement.
- Design fallback behavior from a product perspective. Before adding a fallback, decide whether the correct behavior is to fall back, guide the user to fix an invalid input or setup, or fail clearly with an actionable error.
- Do not add fallback code just to keep a flow appearing successful. A silent fallback that hides bad state, stale data, missing dependencies, or user mistakes is usually worse than a clear failure.
- If a fallback is necessary, keep it narrow, visible, testable, and documented through user-facing behavior or a focused test.

## Product development guardrails

These rules exist to keep fast, vibe-driven development from pushing WhyWiki away from a good product.

- Do not mark a feature as complete just because one happy path works. A complete feature needs a user entry point, real data flow, user-facing failure behavior, tests or local verification, and updated documentation.
- New features must strengthen the WhyWiki loop: choose a project, import materials, generate project memory, review conflicts, and use evidence-backed outputs. Features outside that loop are deferred by default.
- Every user-visible conclusion must be backed by evidence. If evidence is missing, the product should say that clearly or mark the item for review instead of presenting a confident answer.
- Schema and data model changes must include a migration strategy. Do not solve product problems by asking users to delete local data or recreate the data directory.
- Keep dependencies small and intentional. Heavy dependencies must solve a core product problem, stay optional when possible, and fail with actionable guidance.
- LLM features must enhance deterministic parsing, fact extraction, conflict detection, wiki generation, or ask flows. They must not replace the deterministic first-board path or make local verification impossible to reproduce.
- Organize UI around user tasks instead of storage entities. Primary surfaces should reflect daily work; export, settings, diagnostics, and rare actions should stay secondary.
- Product errors should explain what happened, why it matters, and what the user can do next. Technical details belong in logs unless they directly help the user act.
- Tests should protect user-visible product promises first, then internal implementation details.
- Documentation must not drift from the product. When behavior changes, check README, feature status, demo flow, and relevant design docs.
- `README.md` and `README.zh-CN.md` are a synchronized pair. When public setup, behavior, product positioning, or feature status changes, update both README files in the same change and keep their section structure aligned.

## UI / UX design discipline

Before any UI-related task, including creating or modifying a page, component, state, interaction, visual hierarchy, copy, empty state, loading state, error state, evidence view, conflict view, dashboard, ask view, handover view, or settings view, read and follow `docs/ui_ux_guidelines.md`.

That document is mandatory for UI work. In particular:

- UI must reduce user thinking cost, not just look polished.
- Every UI change must clarify page purpose, current system status, primary action, next step, and evidence / AI / conflict / user-confirmed state.
- Before modifying UI code, output the short UX plan required by `docs/ui_ux_guidelines.md`.
- After modifying UI code, run the self-check required by `docs/ui_ux_guidelines.md` and summarize what changed, why it changed, which confusion it solves, remaining UX risks, and the next UX improvement.
- Keep `docs/web_design.md` as the visual and startup direction, but treat `docs/ui_ux_guidelines.md` as the detailed review checklist and acceptance standard for UI implementation.

## Test commands

Run after each meaningful change:

```bash
python -m compileall whywiki
python -m pytest -q
```

## First-board priorities

1. Make the local project flow robust.
2. Support `whywiki init-db`, `create`, `ingest`, `build`, `ask`, `serve`.
3. Improve blocks and facts.
4. Improve conflict detection.
5. Improve Web UI.
6. Add LLM calls only after deterministic behavior is stable.
