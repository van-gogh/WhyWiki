# WhyWiki Web and Startup Design

WhyWiki should feel like a local product, not a source-code demo. The first-run experience should lead users into the Web dashboard with one command, then keep all normal work inside the browser.

## Startup Experience

Target first-board product flow:

```bash
npm install -g whywiki
whywiki
```

The `whywiki` command starts the local Web server quietly on the default local URL, initializes the data directory, and prints a clickable link:

```text
WhyWiki is running locally.

Open:
http://127.0.0.1:8765

Data:
~/.whywiki
```

The command should be idempotent and explicit:

- If WhyWiki is already running on the port, show the current port, process id, startup metadata, and let the user choose whether to continue using it or restart WhyWiki.
- If another process is using the port, show the process information and let the user choose whether to kill that process and start WhyWiki or cancel startup.
- The launcher must not silently choose a random fallback port.

## Launcher Commands

The npm package should expose a small local-app launcher:

```bash
whywiki          # start quietly, print the local Web URL
whywiki open     # open the current Web UI
whywiki status   # show running state, port, version, and data directory
whywiki stop     # stop the local background service
```

Developer and support builds may keep commands such as `whywiki log` or `whywiki doctor`, but they should not appear in the normal browser UI or first-run path. Product failures should explain the next user action directly instead of asking users to inspect backend logs.

## Installation Strategy

Use npm as the first public install path because it matches modern CLI product expectations and avoids asking users to clone the repository.

Phase 1:

- Publish a lightweight npm launcher package.
- The launcher starts the local Python/FastAPI server using the installed project runtime.
- Python, Docker, and source checkout remain developer setup paths.

Phase 2:

- Move toward standalone platform artifacts downloaded by the npm launcher.
- Users should not need to understand Python virtual environments, pip, uvicorn, or Docker.

## Web UI Direction

The Web UI should be a dashboard-style workspace, similar in density and tone to Airtable/Equals rather than a landing page.

Reference:

```bash
npx getdesign@latest add airtable
```

Use that family of visual choices as guidance:

- left sidebar navigation
- top search bar
- light neutral background
- thin borders
- compact cards with small radius
- restrained shadows
- purple primary action
- colorful functional icons
- clear empty states
- SaaS dashboard typography

Avoid a marketing hero as the first screen. The first screen should be the actual product workspace.

## Dashboard Structure

Primary layout:

- Project home: a list of existing projects, a create-project action, and clear empty states.
- Project workspace: project-scoped navigation appears only after selecting a project.
- Project navigation: demand status, original files, demand conflict points, demand Q&A, and settings.
- Top bar: project name, search, status, and local server indicator.
- Main dashboard: project health, recent files, conflict summary, wiki pages, and handover shortcut.
- Flow-level recovery: startup, ingest, and build failures should explain the user action to retry or fix permissions; developer logs stay out of the default product UI.

First-run dashboard:

- `Create project` action
- project cards when local projects already exist
- `Ingest local folder` action after a project is selected
- visible explanation that all conclusions are evidence-backed
- no large text-only onboarding page
- no packaged demo project path in the product UI

## Product Principle

The CLI starts and maintains the local app. The Web UI is where users work.

Normal users should only need:

```bash
whywiki
```

Support and developer troubleshooting can still use:

```bash
whywiki log
```
