# Project Home Requirements UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved WhyWiki project-home and requirements-card UI so opening a project lands on a calm project home, while the requirements page directly shows requirement cards, filters, and conflict navigation.

**Architecture:** Keep the current FastAPI/static-asset architecture and existing `facts` APIs. Add a UI semantic layer in `whywiki/static/app.js` that treats `fact_type=requirement` rows as user-facing requirements and keeps non-requirement facts as supporting/source detail. Do not introduce a database migration or a new `requirements` table in this iteration.

**Tech Stack:** FastAPI static HTML, vanilla JavaScript, CSS, existing i18n dictionary, pytest static asset tests, `python -m compileall`.

---

## File Structure

- Modify `whywiki/static/index.html`: replace workspace navigation with the approved first-level task nav: `主页 / 需求 / 冲突 / 来源 / 问答 / 设置`.
- Modify `whywiki/static/i18n.js`: add home/requirements/source/filter/conflict-jump copy in Chinese and English; remove user-facing "facts" language from the first-level UI.
- Modify `whywiki/static/app.js`: add project-home renderer, requirements data helpers, requirements page, multi-select filters, conflict jump controls, and route aliases.
- Modify `whywiki/static/styles.css`: add project-home, requirement-card, filter-chip, and conflict-jump styles with responsive guards.
- Modify `tests/test_web_assets.py`: protect nav order, route names, terminology, requirement UI helpers, filter chips, and conflict jump behavior hooks.
- Modify `docs/FEATURE_STATUS.md`: after implementation, update the Web UI rows to describe project home, requirements, source naming, and conflict jump controls.

No backend API or schema change is required for the first implementation pass. Use existing endpoints:

- `GET /api/projects/{project_id}/sources`
- `GET /api/projects/{project_id}/facts`
- `GET /api/projects/{project_id}/conflicts`
- `GET /api/projects/{project_id}/wiki`
- `GET /api/projects/{project_id}/facts/{fact_id}/evidence`

---

### Task 1: Navigation Routes And User-Facing Terms

**Files:**
- Modify: `whywiki/static/index.html`
- Modify: `whywiki/static/i18n.js`
- Modify: `whywiki/static/app.js`
- Test: `tests/test_web_assets.py`

- [ ] **Step 1: Write failing navigation and terminology tests**

Add these tests to `tests/test_web_assets.py` near the existing sidebar/i18n tests:

```python
def test_workspace_navigation_uses_project_task_language_and_order():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    nav_match = re.search(r"<nav data-workspace-nav>(?P<body>.*?)</nav>", html, re.S)
    assert nav_match, "workspace navigation is missing"
    nav_body = nav_match.group("body")

    assert re.findall(r'data-view="([^"]+)"', nav_body) == [
        "home",
        "requirements",
        "review",
        "sources",
        "ask",
        "settings",
    ]
    assert re.findall(r'data-i18n="([^"]+)"', nav_body) == [
        "nav.home",
        "nav.requirements",
        "nav.conflicts",
        "nav.sources",
        "nav.ask",
        "nav.settings",
    ]


def test_i18n_uses_requirements_and_sources_for_primary_ui():
    content = (STATIC / "i18n.js").read_text(encoding="utf-8")

    assert '"nav.requirements": "Requirements"' in content
    assert '"nav.sources": "Sources"' in content
    assert '"nav.conflicts": "Conflicts"' in content
    assert '"nav.requirements": "需求"' in content
    assert '"nav.sources": "来源"' in content
    assert '"nav.conflicts": "冲突"' in content
    assert '"nav.facts":' not in content
    assert '"action.confirmRequirement": "Confirm this requirement"' in content
    assert '"action.confirmRequirement": "确认这个需求"' in content
    assert "事实与证据" not in content
    assert "确认这个事实" not in content
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_workspace_navigation_uses_project_task_language_and_order tests/test_web_assets.py::test_i18n_uses_requirements_and_sources_for_primary_ui -q
```

Expected: both tests fail because `index.html` still uses `status/sources/facts/review/ask/settings`, and `i18n.js` still exposes `nav.facts` and fact wording.

- [ ] **Step 3: Replace the workspace nav in `index.html`**

Replace the `<nav data-workspace-nav>` block in `whywiki/static/index.html` with:

```html
    <nav data-workspace-nav>
      <button data-view="home" data-i18n="nav.home">Home</button>
      <button data-view="requirements" data-i18n="nav.requirements">Requirements</button>
      <button data-view="review" data-i18n="nav.conflicts">Conflicts</button>
      <button data-view="sources" data-i18n="nav.sources">Sources</button>
      <button data-view="ask" data-i18n="nav.ask">Ask</button>
      <button data-view="settings" data-i18n="nav.settings">Settings</button>
    </nav>
```

- [ ] **Step 4: Update primary i18n keys**

In `whywiki/static/i18n.js`, replace the old first-level nav keys and add requirement action labels.

English dictionary entries:

```javascript
    "nav.home": "Home",
    "nav.backToProjects": "Back to projects",
    "nav.requirements": "Requirements",
    "nav.projects": "Projects",
    "nav.sources": "Sources",
    "nav.wikiIndex": "Wiki index",
    "nav.conflicts": "Conflicts",
    "nav.ask": "Ask",
    "nav.settings": "Settings",
    "action.confirmRequirement": "Confirm this requirement",
    "build.requirementsCreated": "Requirements generated",
    "view.requirements.title": "Requirements",
```

Chinese dictionary entries:

```javascript
    "nav.home": "主页",
    "nav.backToProjects": "返回项目列表",
    "nav.requirements": "需求",
    "nav.projects": "项目",
    "nav.sources": "来源",
    "nav.wikiIndex": "Wiki 索引",
    "nav.conflicts": "冲突",
    "nav.ask": "问答",
    "nav.settings": "设置",
    "action.confirmRequirement": "确认这个需求",
    "build.requirementsCreated": "已生成需求",
    "view.requirements.title": "需求",
```

Delete the `nav.facts` entries from both dictionaries. Keep internal variable/function names such as `facts` for now.

- [ ] **Step 5: Add route aliases in `app.js`**

In `loadView(view)`, use a route alias so old stored states or tests do not break:

```javascript
function normalizeView(view) {
  if (view === "status") return "home";
  if (view === "facts") return "requirements";
  return view || "projects";
}
```

Then update the first lines of `loadView`:

```javascript
async function loadView(view) {
  const appNode = appContainer();
  if (!appNode) return;
  activeView = normalizeView(view);
  setActiveView(activeView);
  appNode.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
```

Update `setActiveView(view)` so legacy buttons do not matter and the active state follows normalized view names:

```javascript
function setActiveView(view) {
  const normalizedView = normalizeView(view);
  activeView = normalizedView;
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === normalizedView);
  });
}
```

- [ ] **Step 6: Verify tests pass**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_workspace_navigation_uses_project_task_language_and_order tests/test_web_assets.py::test_i18n_uses_requirements_and_sources_for_primary_ui -q
```

Expected: `2 passed`.

- [ ] **Step 7: Commit navigation work**

Run:

```bash
git add whywiki/static/index.html whywiki/static/i18n.js whywiki/static/app.js tests/test_web_assets.py
git commit -m "feat: simplify project workspace navigation"
```

---

### Task 2: Requirement Data Helpers

**Files:**
- Modify: `whywiki/static/app.js`
- Test: `tests/test_web_assets.py`

- [ ] **Step 1: Write failing helper coverage**

Add this test to `tests/test_web_assets.py` near `test_app_js_exposes_project_guidance_and_evidence_components`:

```python
def test_app_js_defines_requirement_semantic_helpers():
    content = (STATIC / "app.js").read_text(encoding="utf-8")

    for symbol in (
        "function requirementRows",
        "function supportingFactRows",
        "function requirementStatusKind",
        "function requirementStatusLabel",
        "function requirementSourceCount",
        "function sortRequirementRows",
        "function visibleRequirementRows",
    ):
        assert symbol in content

    assert 'fact.fact_type === "requirement"' in content
    assert 'row.validity_status === "conflicting"' in content
    assert 'row.status === "needs_review"' in content
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_app_js_defines_requirement_semantic_helpers -q
```

Expected: FAIL because the helper functions do not exist yet.

- [ ] **Step 3: Add requirement helpers in `app.js`**

Insert these helpers after `reviewFactRows(facts)`:

```javascript
function requirementRows(facts = []) {
  return facts.filter((fact) => fact.fact_type === "requirement");
}

function supportingFactRows(facts = []) {
  return facts.filter((fact) => fact.fact_type !== "requirement");
}

function requirementStatusKind(row) {
  if (row.validity_status === "conflicting") return "conflict";
  if (row.status === "needs_review" || row.status === "candidate") return "needs-review";
  if (row.status === "confirmed" || row.validity_status === "current") return "confirmed";
  if (!evidenceItems(row).length) return "low-confidence";
  return "source-backed";
}

function requirementStatusLabel(row) {
  const kind = requirementStatusKind(row);
  if (kind === "conflict") return t("badge.conflict");
  if (kind === "needs-review") return t("badge.needsReview");
  if (kind === "confirmed") return t("badge.confirmed");
  if (kind === "low-confidence") return t("badge.lowConfidence");
  return t("badge.sourceBacked");
}

function requirementSourceCount(row) {
  const paths = new Set(evidenceItems(row).map((item) => item.path || item.source_path).filter(Boolean));
  return paths.size;
}

function sortRequirementRows(rows = []) {
  return [...rows].sort((a, b) => {
    const sourceA = evidenceItems(a)[0]?.path || "";
    const sourceB = evidenceItems(b)[0]?.path || "";
    const sourceCompare = String(sourceA).localeCompare(String(sourceB));
    if (sourceCompare) return sourceCompare;
    return String(a.statement || "").localeCompare(String(b.statement || ""));
  });
}

function visibleRequirementRows(rows = [], filters = new Set(["all"])) {
  if (!filters || filters.size === 0 || filters.has("all")) return sortRequirementRows(rows);
  return sortRequirementRows(rows).filter((row) => {
    const kind = requirementStatusKind(row);
    const statusMatch = (
      (filters.has("conflict") && kind === "conflict") ||
      (filters.has("needs-review") && kind === "needs-review") ||
      (filters.has("confirmed") && kind === "confirmed")
    );
    const sourceMatch = filters.has("source-backed") && requirementSourceCount(row) > 0;
    const recentMatch = filters.has("recent") && Boolean(row.updated_at || row.created_at);
    return statusMatch || sourceMatch || recentMatch;
  });
}
```

- [ ] **Step 4: Add missing badge i18n keys**

Add these keys to both language dictionaries in `whywiki/static/i18n.js`:

```javascript
    "badge.sourceBacked": "Source-backed",
    "requirement.sourceCount": "{count} sources",
```

```javascript
    "badge.sourceBacked": "有来源",
    "requirement.sourceCount": "{count} 个来源",
```

- [ ] **Step 5: Run helper coverage**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_app_js_defines_requirement_semantic_helpers tests/test_web_assets.py::test_i18n_contains_p0_p1_ux_copy_for_each_language -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit helper work**

Run:

```bash
git add whywiki/static/app.js whywiki/static/i18n.js tests/test_web_assets.py
git commit -m "feat: add requirement semantic helpers"
```

---

### Task 3: Project Home Renderer

**Files:**
- Modify: `whywiki/static/app.js`
- Modify: `whywiki/static/i18n.js`
- Modify: `whywiki/static/styles.css`
- Test: `tests/test_web_assets.py`

- [ ] **Step 1: Write failing project-home tests**

Add this test to `tests/test_web_assets.py`:

```python
def test_app_js_renders_project_home_as_default_project_entry():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "function renderProjectHome" in content
    assert "function renderRequirementPreview" in content
    assert "function renderProjectHomeEmptySourceActions" in content
    assert 'loadView("home")' in content
    assert 'home: renderProjectHome' in content
    assert 'requirements: renderRequirements' in content
    assert 'showIngestForm("local")' in content
    assert 'showIngestForm("git")' in content
    assert ".project-home-hero" in css
    assert ".project-home-preview-grid" in css
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_app_js_renders_project_home_as_default_project_entry -q
```

Expected: FAIL because project-home rendering does not exist and `selectProject` still loads the old status view.

- [ ] **Step 3: Route project selection to home**

Change `selectProject(project)` in `whywiki/static/app.js` to:

```javascript
function selectProject(project) {
  setCurrentProject(project);
  updateWorkspaceChrome(true);
  loadView("home");
}
```

Change the successful create-project path in `showCreateProjectForm()` to:

```javascript
      setCurrentProject(project);
      await loadView("home");
```

- [ ] **Step 4: Let ingest form preselect local or git source**

Change the function signature and source select setup:

```javascript
function showIngestForm(preferredSourceType = "local") {
  const appNode = appContainer();
  if (!appNode) return;
  setActiveView("");
  updateWorkspaceChrome(true);
  const projectId = requireProject();
  if (!projectId) {
    appNode.replaceChildren(renderNoProjectAction());
    return;
  }

  const panel = createFormPanel(t("ingest.title"));
  panel.append(renderEmptyState({
    title: t("empty.sources.title"),
    body: t("empty.sources.body"),
    kind: "sources",
  }));
  const form = document.createElement("form");
  form.className = "inline-form";
  const pathInput = document.createElement("input");
  pathInput.name = "path";
  pathInput.required = true;
  pathInput.placeholder = t("ingest.pathPlaceholder");
  const sourceType = document.createElement("select");
  ["local", "git"].forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value === "git" ? t("badge.git") : t("badge.document");
    sourceType.append(option);
  });
  sourceType.value = preferredSourceType === "git" ? "git" : "local";
```

Keep the existing submit handler below this block.

- [ ] **Step 5: Add project-home renderers**

Insert these functions before `renderStatus(projectId)`:

```javascript
function renderProjectHomeEmptySourceActions() {
  const actions = createElement("div", "actions project-home-source-actions");
  actions.append(
    createActionButton(t("action.connectLocalSource"), "primary", () => showIngestForm("local")),
    createActionButton(t("action.connectGithubSource"), "secondary", () => showIngestForm("git"))
  );
  return actions;
}

function renderRequirementPreview(requirements) {
  const grid = createElement("div", "project-home-preview-grid");
  requirements.slice(0, 3).forEach((requirement) => {
    const card = createElement("article", "requirement-preview-card");
    const header = createElement("header", "card-header");
    header.append(
      createElement("strong", "", requirement.statement || t("view.requirements.title")),
      renderStatusBadge(requirementStatusLabel(requirement), requirementStatusKind(requirement))
    );
    const sourceCount = requirementSourceCount(requirement);
    const sourceLabel = t("requirement.sourceCount").replace("{count}", String(sourceCount));
    card.append(header, createElement("p", "", sourceLabel));
    grid.append(card);
  });
  return grid;
}

async function renderProjectHome(projectId) {
  const [sources, facts, conflicts, pages] = await Promise.all([
    api(`/api/projects/${projectId}/sources`),
    api(`/api/projects/${projectId}/facts`),
    api(`/api/projects/${projectId}/conflicts`),
    api(`/api/projects/${projectId}/wiki`),
  ]);
  const requirements = requirementRows(facts);
  const state = deriveProjectState({ sources, facts, conflicts, pages });
  const panel = createPanel(t("projectHome.title"));
  panel.classList.add("project-home-workspace");

  const hero = createElement("section", "project-home-hero");
  const copy = createElement("div", "project-home-copy");
  copy.append(
    renderStatusBadge(t(`workflow.${state.stage}`), state.stage),
    createElement("h1", "", projectDisplayName()),
    createElement("p", "", requirements.length ? t("projectHome.readyBody") : t("projectHome.emptyBody"))
  );
  const stats = createElement("div", "project-home-stats");
  stats.append(
    createMetric(t("status.metric.sources"), sources.length),
    createMetric(t("status.metric.requirements"), requirements.length),
    createMetric(t("status.metric.conflicts"), visibleConflictRows(conflicts).length),
    createMetric(t("status.metric.wiki"), visibleWikiPages(pages).length)
  );
  hero.append(copy, stats);
  panel.append(hero);

  if (!sources.length) {
    panel.append(renderProjectHomeEmptySourceActions());
    return panel;
  }

  if (!requirements.length) {
    panel.append(renderNextActionPanel({ nextAction: "generateEvidenceWiki" }));
    return panel;
  }

  const focus = reviewFactRows(requirements).length ? reviewFactRows(requirements) : requirements;
  panel.append(
    createElement("h2", "project-home-section-title", t("projectHome.previewTitle")),
    renderRequirementPreview(focus),
    createActionButton(t("action.viewAllRequirements"), "primary", () => loadView("requirements"))
  );
  return panel;
}
```

- [ ] **Step 6: Add project-home i18n**

Add these keys to both dictionaries:

```javascript
    "action.connectLocalSource": "Connect local folder",
    "action.connectGithubSource": "Connect GitHub repository",
    "action.viewAllRequirements": "View all requirements",
    "projectHome.title": "Project home",
    "projectHome.emptyBody": "Connect a local folder or GitHub repository so WhyWiki can extract requirements, conflicts, and source-backed project memory.",
    "projectHome.readyBody": "WhyWiki has source material for this project. Review the requirements that need attention, then open the full requirements list.",
    "projectHome.previewTitle": "Requirements to review",
    "status.metric.requirements": "Requirements",
```

```javascript
    "action.connectLocalSource": "连接本地文件夹",
    "action.connectGithubSource": "连接 GitHub 仓库",
    "action.viewAllRequirements": "查看全部需求",
    "projectHome.title": "项目主页",
    "projectHome.emptyBody": "连接本地文件夹或 GitHub 仓库后，WhyWiki 会提取需求、冲突和有来源的项目记忆。",
    "projectHome.readyBody": "WhyWiki 已经有这个项目的来源材料。先看需要关注的需求，再进入完整需求列表。",
    "projectHome.previewTitle": "需要关注的需求",
    "status.metric.requirements": "需求",
```

- [ ] **Step 7: Wire renderers map**

In `loadView`, replace the renderers map with:

```javascript
    const renderers = {
      home: renderProjectHome,
      requirements: renderRequirements,
      sources: renderSources,
      wiki: renderWiki,
      conflicts: renderConflicts,
      review: renderReview,
      handover: renderHandover,
      ask: renderAsk,
      settings: renderSettings,
    };
```

Use `renderRequirements` as a temporary alias until Task 4:

```javascript
async function renderRequirements(projectId) {
  return renderFacts(projectId);
}
```

- [ ] **Step 8: Add project-home CSS**

Append these selectors near existing project status styles:

```css
.project-home-workspace {
  display: grid;
  gap: 18px;
}

.project-home-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(220px, .8fr);
  gap: 18px;
  align-items: stretch;
  border: 1px solid var(--line);
  border-left: 6px solid var(--purple);
  border-radius: 8px;
  background: var(--panel);
  padding: 22px;
}

.project-home-copy {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.project-home-copy h1 {
  margin: 0;
  font-size: 34px;
  line-height: 1.1;
  overflow-wrap: anywhere;
}

.project-home-copy p {
  margin: 0;
  max-width: 680px;
  color: var(--muted);
  line-height: 1.55;
}

.project-home-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.project-home-source-actions {
  justify-content: flex-start;
}

.project-home-section-title {
  margin: 0;
  font-size: 18px;
}

.project-home-preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.requirement-preview-card {
  display: grid;
  gap: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #ffffff;
  padding: 14px;
}

.requirement-preview-card p {
  margin: 0;
  color: var(--muted);
}
```

Add mobile override inside `@media (max-width: 720px)`:

```css
  .project-home-hero {
    grid-template-columns: 1fr;
  }

  .project-home-stats {
    grid-template-columns: 1fr 1fr;
  }
```

- [ ] **Step 9: Run project-home tests**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_app_js_renders_project_home_as_default_project_entry tests/test_web_assets.py::test_i18n_contains_p0_p1_ux_copy_for_each_language -q
```

Expected: tests pass.

- [ ] **Step 10: Commit project-home work**

Run:

```bash
git add whywiki/static/app.js whywiki/static/i18n.js whywiki/static/styles.css tests/test_web_assets.py
git commit -m "feat: add project home workspace"
```

---

### Task 4: Requirements Page And Requirement Cards

**Files:**
- Modify: `whywiki/static/app.js`
- Modify: `whywiki/static/i18n.js`
- Modify: `whywiki/static/styles.css`
- Test: `tests/test_web_assets.py`

- [ ] **Step 1: Write failing requirements page tests**

Add this test to `tests/test_web_assets.py`:

```python
def test_app_js_renders_requirements_page_and_cards():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    for symbol in (
        "function renderRequirements",
        "function renderRequirementCard",
        "function renderRequirementToolbar",
        "function renderRequirementSourceSummary",
    ):
        assert symbol in content

    assert 'api(`/api/projects/${projectId}/facts`)' in content
    assert 'requirementRows(facts)' in content
    assert 'supportingFactRows(facts)' in content
    assert "requirement-card" in content
    assert "requirements-page" in css
    assert ".requirement-card" in css
    assert ".requirements-attention" in css
```

- [ ] **Step 2: Run failing test**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_app_js_renders_requirements_page_and_cards -q
```

Expected: FAIL because the requirements page is still an alias to `renderFacts`.

- [ ] **Step 3: Add requirement source summary helper**

Insert this function before `renderRequirementCard`:

```javascript
function renderRequirementSourceSummary(requirement) {
  const count = requirementSourceCount(requirement);
  const label = t("requirement.sourceCount").replace("{count}", String(count));
  const summary = createElement("span", "requirement-source-summary", label);
  return summary;
}
```

- [ ] **Step 4: Add requirement card renderer**

Insert this function before `renderRequirements(projectId)`:

```javascript
function renderRequirementCard(requirement, supportingFacts = []) {
  const card = createElement("article", "requirement-card");
  card.dataset.requirementId = requirement.id || "";
  if (requirementStatusKind(requirement) === "conflict") {
    card.dataset.requirementConflict = "true";
  }

  const header = createElement("header", "card-header");
  const title = createElement("strong", "", requirement.statement || t("view.requirements.title"));
  const badges = createElement("div", "badge-row");
  badges.append(renderStatusBadge(requirementStatusLabel(requirement), requirementStatusKind(requirement)));
  badges.append(renderRequirementSourceSummary(requirement));
  header.append(title, badges);

  const body = createElement("p", "requirement-statement", requirement.statement || "-");
  const actions = createElement("div", "actions");
  actions.append(
    createActionButton(t("action.viewSource"), "tertiary", () => {
      const drawer = card.querySelector(".evidence-drawer");
      if (drawer) drawer.open = true;
    }),
    createActionButton(t("action.confirmRequirement"), "secondary", () => {
      actions.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
      updateFactStatus(requirement.id, "confirmed").then((updated) => {
        actions.replaceChildren(renderOperationFeedback("success", t("badge.confirmed"), updated.statement || ""));
      }).catch((error) => {
        actions.replaceChildren(renderOperationFeedback("error", t("view.error"), error.message));
      });
    })
  );

  const support = createElement("div", "requirement-support");
  const related = supportingFacts.slice(0, 3);
  if (related.length) {
    support.append(createElement("strong", "", t("requirement.supportingFacts")));
    related.forEach((fact) => {
      support.append(createElement("span", "", `${fieldValue(fact.fact_type)} · ${fact.statement || ""}`));
    });
  }

  card.append(
    header,
    body,
    support,
    actions,
    renderEvidenceDrawer(
      evidenceItems(requirement),
      t("sources.drawer.title"),
      requirement.id ? `/api/projects/${requireProject()}/facts/${requirement.id}/evidence` : ""
    )
  );
  return card;
}
```

- [ ] **Step 5: Replace `renderRequirements` alias with real page**

Replace the temporary `renderRequirements(projectId)` function with:

```javascript
async function renderRequirements(projectId) {
  const facts = await api(`/api/projects/${projectId}/facts`);
  const requirements = requirementRows(facts);
  const supportingFacts = supportingFactRows(facts);
  const panel = createPanel(t("view.requirements.title"));
  panel.classList.add("requirements-page");

  if (!requirements.length) {
    panel.append(renderEmptyState({
      title: t("empty.requirements.title"),
      body: t("empty.requirements.body"),
      actionLabel: t("action.generateEvidenceWiki"),
      onAction: buildCurrentProject,
      kind: "requirements",
    }));
    return panel;
  }

  const attention = reviewFactRows(requirements);
  if (attention.length) {
    const attentionSection = createElement("section", "requirements-attention");
    attentionSection.append(createElement("h3", "", t("requirements.attentionTitle")));
    const attentionGrid = createElement("div", "requirement-grid");
    attention.slice(0, 3).forEach((requirement) => attentionGrid.append(renderRequirementCard(requirement, supportingFacts)));
    attentionSection.append(attentionGrid);
    panel.append(attentionSection);
  }

  const allSection = createElement("section", "requirements-all");
  allSection.append(renderRequirementToolbar(requirements));
  const grid = createElement("div", "requirement-grid");
  visibleRequirementRows(requirements, requirementFilterState).forEach((requirement) => {
    grid.append(renderRequirementCard(requirement, supportingFacts));
  });
  allSection.append(grid);
  panel.append(allSection);
  return panel;
}
```

- [ ] **Step 6: Add required i18n**

Add these keys to both dictionaries:

```javascript
    "action.viewSource": "View source",
    "empty.requirements.title": "No requirements generated yet",
    "empty.requirements.body": "Generate project memory after connecting a source. WhyWiki will extract requirements, sources, and review items.",
    "requirements.attentionTitle": "Needs attention",
    "requirement.supportingFacts": "Related source details",
    "sources.drawer.title": "Sources",
```

```javascript
    "action.viewSource": "查看来源",
    "empty.requirements.title": "还没有生成需求",
    "empty.requirements.body": "连接来源后生成项目记忆，WhyWiki 会提取需求、来源和需要审查的事项。",
    "requirements.attentionTitle": "需要处理",
    "requirement.supportingFacts": "关联来源信息",
    "sources.drawer.title": "来源",
```

- [ ] **Step 7: Add requirement page CSS**

Append:

```css
.requirements-page,
.requirements-attention,
.requirements-all {
  display: grid;
  gap: 16px;
}

.requirements-attention {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #ffffff;
  padding: 16px;
}

.requirements-attention h3 {
  margin: 0;
}

.requirement-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.requirement-card {
  display: grid;
  gap: 12px;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #ffffff;
  padding: 14px;
}

.requirement-card[data-requirement-conflict="true"] {
  border-color: #fecaca;
}

.requirement-statement {
  margin: 0;
  color: var(--text);
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.requirement-source-summary {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.requirement-support {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}
```

- [ ] **Step 8: Run requirements page tests**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_app_js_renders_requirements_page_and_cards tests/test_web_assets.py::test_i18n_contains_p0_p1_ux_copy_for_each_language -q
```

Expected: tests pass.

- [ ] **Step 9: Commit requirements page work**

Run:

```bash
git add whywiki/static/app.js whywiki/static/i18n.js whywiki/static/styles.css tests/test_web_assets.py
git commit -m "feat: render requirements as cards"
```

---

### Task 5: Multi-Select Filters And Conflict Jump Controls

**Files:**
- Modify: `whywiki/static/app.js`
- Modify: `whywiki/static/i18n.js`
- Modify: `whywiki/static/styles.css`
- Test: `tests/test_web_assets.py`

- [ ] **Step 1: Write failing filter and jump tests**

Add this test:

```python
def test_requirements_page_exposes_multiselect_filters_and_conflict_jump():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    for symbol in (
        "let requirementFilterState",
        "function toggleRequirementFilter",
        "function renderRequirementFilterChip",
        "function renderRequirementToolbar",
        "function renderConflictJumpControl",
        "function jumpToConflictRequirement",
        "function createChevronIcon",
    ):
        assert symbol in content

    assert "requirement-filter-chip" in content
    assert "requirement-conflict-jump" in content
    assert 'data-filter="conflict"' in content
    assert 'data-filter="needs-review"' in content
    assert 'data-filter="confirmed"' in content
    assert 'data-filter="recent"' in content
    assert 'data-filter="source-backed"' in content
    assert "scrollIntoView" in content
    assert ".requirement-filter-chip" in css
    assert ".requirement-conflict-jump" in css
    assert ".requirement-card.is-jump-target" in css
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_requirements_page_exposes_multiselect_filters_and_conflict_jump -q
```

Expected: FAIL because filters and jump controls are not implemented.

- [ ] **Step 3: Add filter state and icons**

Near the top of `whywiki/static/app.js`, after `let activeView = "projects";`, add:

```javascript
let requirementFilterState = new Set(["all"]);
let activeConflictRequirementId = null;
let requirementJumpTimer = null;
```

Add this icon helper near `createVerticalEllipsisIcon()`:

```javascript
function createChevronIcon(direction) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.classList.add("chevron-icon");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", direction === "up" ? "m18 15-6-6-6 6" : "m6 9 6 6 6-6");
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "2.4");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.append(path);
  return svg;
}
```

- [ ] **Step 4: Add filter controls**

Insert before `renderRequirements(projectId)`:

```javascript
function toggleRequirementFilter(filter) {
  if (filter === "all") {
    requirementFilterState = new Set(["all"]);
  } else {
    requirementFilterState.delete("all");
    if (requirementFilterState.has(filter)) {
      requirementFilterState.delete(filter);
    } else {
      requirementFilterState.add(filter);
    }
    if (!requirementFilterState.size) requirementFilterState.add("all");
  }
  loadView("requirements");
}

function renderRequirementFilterChip(filter, label, kind = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `requirement-filter-chip requirement-filter-${kind || filter}`;
  button.dataset.filter = filter;
  button.textContent = label;
  const selected = requirementFilterState.has(filter);
  button.classList.toggle("is-selected", selected);
  button.setAttribute("aria-pressed", selected ? "true" : "false");
  button.addEventListener("click", () => toggleRequirementFilter(filter));
  return button;
}

function renderRequirementToolbar(requirements) {
  const toolbar = createElement("div", "requirements-toolbar");
  const title = createElement("h3", "", t("requirements.allTitle"));
  const filters = createElement("div", "requirement-filter-row");
  filters.append(
    renderRequirementFilterChip("all", t("filter.all"), "all"),
    renderRequirementFilterChip("conflict", t("filter.conflict"), "conflict"),
    renderRequirementFilterChip("needs-review", t("filter.needsReview"), "needs-review"),
    renderRequirementFilterChip("confirmed", t("filter.confirmed"), "confirmed"),
    renderRequirementFilterChip("recent", t("filter.recent"), "recent"),
    renderRequirementFilterChip("source-backed", t("filter.sourceBacked"), "source-backed")
  );
  toolbar.append(title, filters, renderConflictJumpControl(requirements));
  return toolbar;
}
```

- [ ] **Step 5: Add conflict jump control**

Insert after `renderRequirementToolbar`:

```javascript
function renderConflictJumpControl(requirements) {
  const conflicts = visibleRequirementRows(requirements, requirementFilterState)
    .filter((row) => requirementStatusKind(row) === "conflict");
  const control = createElement("div", "requirement-conflict-jump");
  const activeIndex = conflicts.findIndex((row) => row.id === activeConflictRequirementId);
  const current = conflicts.length ? Math.max(0, activeIndex) + 1 : 0;
  control.append(createElement("span", "", t("requirements.conflictJump").replace("{current}", String(current)).replace("{total}", String(conflicts.length))));

  const previous = document.createElement("button");
  previous.type = "button";
  previous.setAttribute("aria-label", t("requirements.previousConflict"));
  previous.append(createChevronIcon("up"));
  previous.disabled = !conflicts.length;
  previous.addEventListener("click", () => jumpToConflictRequirement("previous"));

  const next = document.createElement("button");
  next.type = "button";
  next.setAttribute("aria-label", t("requirements.nextConflict"));
  next.append(createChevronIcon("down"));
  next.disabled = !conflicts.length;
  next.addEventListener("click", () => jumpToConflictRequirement("next"));

  control.append(previous, next);
  return control;
}

function jumpToConflictRequirement(direction) {
  const cards = Array.from(document.querySelectorAll('[data-requirement-conflict="true"]'));
  if (!cards.length) return;
  const currentIndex = cards.findIndex((card) => card.dataset.requirementId === activeConflictRequirementId);
  const fallbackIndex = direction === "previous" ? cards.length : -1;
  const baseIndex = currentIndex >= 0 ? currentIndex : fallbackIndex;
  const nextIndex = direction === "previous"
    ? (baseIndex - 1 + cards.length) % cards.length
    : (baseIndex + 1) % cards.length;
  const target = cards[nextIndex];
  activeConflictRequirementId = target.dataset.requirementId || null;
  if (requirementJumpTimer !== null) window.clearTimeout(requirementJumpTimer);
  cards.forEach((card) => card.classList.remove("is-jump-target"));
  target.classList.add("is-jump-target");
  target.scrollIntoView({ block: "center", behavior: "smooth" });
  requirementJumpTimer = window.setTimeout(() => {
    target.classList.remove("is-jump-target");
    requirementJumpTimer = null;
  }, 1600);
}
```

- [ ] **Step 6: Add filter and jump i18n**

Add these keys to both dictionaries:

```javascript
    "requirements.allTitle": "All requirements",
    "requirements.conflictJump": "Conflicts {current}/{total}",
    "requirements.previousConflict": "Previous conflict",
    "requirements.nextConflict": "Next conflict",
    "filter.all": "All",
    "filter.conflict": "Conflicts",
    "filter.needsReview": "Needs review",
    "filter.confirmed": "Confirmed",
    "filter.recent": "Recent",
    "filter.sourceBacked": "By source",
```

```javascript
    "requirements.allTitle": "全部需求",
    "requirements.conflictJump": "冲突 {current}/{total}",
    "requirements.previousConflict": "上一个冲突",
    "requirements.nextConflict": "下一个冲突",
    "filter.all": "全部",
    "filter.conflict": "冲突",
    "filter.needsReview": "待确认",
    "filter.confirmed": "已确认",
    "filter.recent": "最近操作",
    "filter.sourceBacked": "按来源",
```

- [ ] **Step 7: Add filter and jump CSS**

Append:

```css
.requirements-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.requirements-toolbar h3 {
  margin: 0;
  margin-right: auto;
  font-size: 18px;
}

.requirement-filter-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.requirement-filter-chip {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #ffffff;
  color: var(--muted);
  padding: 6px 11px;
  font-weight: 700;
}

.requirement-filter-chip.is-selected {
  background: #f5f3ff;
  border-color: #c4b5fd;
  color: var(--purple);
}

.requirement-filter-conflict,
.requirement-filter-conflict.is-selected {
  border-color: #fecaca;
  color: var(--conflict);
}

.requirement-filter-needs-review,
.requirement-filter-needs-review.is-selected {
  border-color: #fed7aa;
  color: var(--needs-review);
}

.requirement-filter-confirmed,
.requirement-filter-confirmed.is-selected {
  border-color: #bbf7d0;
  color: var(--confirmed);
}

.requirement-filter-recent,
.requirement-filter-recent.is-selected {
  border-color: #dbeafe;
  color: var(--source-git);
}

.requirement-conflict-jump {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid #fecaca;
  border-radius: 999px;
  background: #ffffff;
  padding: 4px 6px 4px 10px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, .06);
}

.requirement-conflict-jump span {
  color: var(--conflict);
  font-size: 12px;
  font-weight: 800;
}

.requirement-conflict-jump button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  min-width: 26px;
  border: 0;
  border-radius: 999px;
  background: #ffffff;
  color: #52525b;
  padding: 0;
}

.chevron-icon {
  width: 18px;
  height: 18px;
}

.requirement-card.is-jump-target {
  border-color: var(--conflict);
  box-shadow: 0 0 0 4px rgba(220, 38, 38, .12);
}
```

Add mobile override:

```css
  .requirements-toolbar {
    align-items: flex-start;
  }

  .requirement-filter-row {
    justify-content: flex-start;
  }
```

- [ ] **Step 8: Run filter/jump tests**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_requirements_page_exposes_multiselect_filters_and_conflict_jump -q
```

Expected: test passes.

- [ ] **Step 9: Commit filter and jump work**

Run:

```bash
git add whywiki/static/app.js whywiki/static/i18n.js whywiki/static/styles.css tests/test_web_assets.py
git commit -m "feat: add requirement filters and conflict jump"
```

---

### Task 6: Documentation And Full Verification

**Files:**
- Modify: `docs/FEATURE_STATUS.md`
- Test: full project checks

- [ ] **Step 1: Update feature ledger**

In `docs/FEATURE_STATUS.md`, update the Web UI rows to reflect:

```markdown
| Web UI | 项目内主页 | 已完成 | 打开项目后默认进入项目主页；空项目引导连接本地文件夹或 GitHub 仓库，已有项目展示需求预览和查看全部需求入口。 |
| Web UI | 需求页 | 已完成 | `需求` 页以卡片展示 `fact_type=requirement` 的用户可读需求，来源、证据和支撑事实在卡片详情中展开。 |
| Web UI | 需求筛选与冲突跳转 | 已完成 | `全部需求` 工具栏提供可多选筛选 chips，并提供 `冲突 {current}/{total}` 上下跳转控件。 |
```

Update the existing `需求现状视图` row instead of leaving a contradictory older statement.

- [ ] **Step 2: Run static web asset tests**

Run:

```bash
python -m pytest tests/test_web_assets.py -q
```

Expected: all tests in `tests/test_web_assets.py` pass.

- [ ] **Step 3: Run required project checks**

Run:

```bash
python -m compileall whywiki
python -m pytest -q
```

Expected:

- `compileall` exits 0.
- Full pytest exits 0. Existing FastAPI `on_event` deprecation warnings may remain.

- [ ] **Step 4: Optional live browser verification**

If a local WhyWiki server is running at `http://localhost:8765/`, open it and verify:

- Project list opens normally.
- Selecting a project lands on `主页`.
- Sidebar order is `主页 / 需求 / 冲突 / 来源 / 问答 / 设置`.
- `需求` page shows cards and filter chips.
- `冲突 {current}/{total}` control jumps between visible conflict cards.
- No user-facing `事实与证据` or `确认这个事实` copy remains in the main UI.

If no server is running, skip this step and report that only automated verification was performed.

- [ ] **Step 5: Commit documentation and verification updates**

Run:

```bash
git add docs/FEATURE_STATUS.md
git commit -m "docs: update requirements UI feature status"
```

---

## Plan Self-Review

Spec coverage:

- Project home default entry is covered by Task 1 and Task 3.
- Requirement cards and user-facing requirements terminology are covered by Task 1, Task 2, and Task 4.
- Primary nav order and `来源` naming are covered by Task 1.
- Multi-select filter chips are covered by Task 5.
- Conflict jump controls with Lucide-style chevrons are covered by Task 5.
- Empty-state behavior for local/GitHub source entry is covered by Task 3.
- Feature documentation and required checks are covered by Task 6.

Placeholder scan:

- The plan contains no `TBD`, no deferred implementation step, and no unbounded "handle edge cases" instruction.
- Each implementation task includes concrete tests, exact files, commands, and code blocks for new functions or replacements.

Type and name consistency:

- Route names are `home`, `requirements`, `review`, `sources`, `ask`, and `settings`.
- User-facing requirement helper names consistently use `Requirement`, while existing backend/API data still uses `facts`.
- Filter values are `all`, `conflict`, `needs-review`, `confirmed`, `recent`, and `source-backed`.
