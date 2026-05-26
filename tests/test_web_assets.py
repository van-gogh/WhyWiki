from pathlib import Path
from html.parser import HTMLParser
import re


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "whywiki" / "static"


class DashboardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.i18n_keys = set()
        self.placeholder_keys = set()
        self.stylesheets = []
        self.icons = []
        self.scripts = []
        self.button_stack = []
        self.i18n_buttons = []
        self.action_buttons = set()
        self.language_switches = []
        self.workspace_navs = 0

    def handle_starttag(self, tag, attrs):
        attr_map = dict(attrs)
        if "data-i18n" in attr_map:
            self.i18n_keys.add(attr_map["data-i18n"])
        if "data-i18n-placeholder" in attr_map:
            self.placeholder_keys.add(attr_map["data-i18n-placeholder"])
        if tag == "link" and attr_map.get("rel") == "stylesheet":
            self.stylesheets.append(attr_map["href"])
        if tag == "link" and attr_map.get("rel") == "icon":
            self.icons.append(attr_map["href"])
        if tag == "script" and "src" in attr_map:
            self.scripts.append(attr_map["src"])
        if "data-action" in attr_map:
            self.action_buttons.add(attr_map["data-action"])
        if "data-active-lang" in attr_map:
            self.language_switches.append(attr_map["data-active-lang"])
        if "data-workspace-nav" in attr_map:
            self.workspace_navs += 1
        if tag == "button":
            self.button_stack.append(
                {
                    "data_i18n": attr_map.get("data-i18n"),
                    "data_view": attr_map.get("data-view"),
                    "data_action": attr_map.get("data-action"),
                    "text": "",
                }
            )

    def handle_data(self, data):
        if self.button_stack:
            self.button_stack[-1]["text"] += data

    def handle_endtag(self, tag):
        if tag == "button" and self.button_stack:
            button = self.button_stack.pop()
            if button["data_i18n"]:
                self.i18n_buttons.append(button)


def parse_dashboard():
    parser = DashboardParser()
    parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    return parser


def parse_i18n_keys():
    content = (STATIC / "i18n.js").read_text(encoding="utf-8")
    languages = {}
    for language in ("zh-CN", "en-US"):
        match = re.search(rf'"{re.escape(language)}":\s*\{{(?P<body>.*?)\n  \}}', content, re.S)
        assert match, f"Missing {language} dictionary"
        languages[language] = set(re.findall(r'"([^"]+)":', match.group("body")))
    return languages


def static_url_exists(url):
    assert url.startswith("/static/")
    return (STATIC / url.removeprefix("/static/")).exists()


def test_dashboard_asset_references_exist():
    parser = parse_dashboard()

    assert (STATIC / "index.html").exists()
    assert (STATIC / "styles.css").exists()
    assert (STATIC / "app.js").exists()
    assert (STATIC / "i18n.js").exists()
    assert parser.icons == ["data:,"]
    assert parser.stylesheets == ["/static/styles.css"]
    assert parser.scripts == ["/static/i18n.js", "/static/app.js"]
    for href in parser.stylesheets:
        assert static_url_exists(href)
    for src in parser.scripts:
        assert static_url_exists(src)


def test_i18n_contains_all_dashboard_keys_for_each_language():
    parser = parse_dashboard()
    keys = parser.i18n_keys | parser.placeholder_keys
    languages = parse_i18n_keys()

    assert "nav.home" in keys
    assert "nav.conflicts" in keys
    assert "nav.wikiIndex" in keys
    assert "search.placeholder" in keys
    for language, language_keys in languages.items():
        assert not keys - language_keys, f"{language} missing keys: {sorted(keys - language_keys)}"


def test_sidebar_buttons_expose_view_hooks():
    parser = parse_dashboard()
    views = {
        button["data_view"]
        for button in parser.i18n_buttons
        if button["data_i18n"] and button["data_i18n"].startswith("nav.")
    }

    assert parser.workspace_navs == 1
    assert {"home", "requirements", "review", "sources", "ask", "settings", "wiki"} <= views
    assert "start" not in views
    assert "handover" not in views


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


def test_static_shell_does_not_expose_home_action_buttons():
    parser = parse_dashboard()

    assert not parser.action_buttons
    assert "useDemo" not in parser.action_buttons


def test_i18n_contains_chinese_and_english_dictionaries():
    content = (STATIC / "i18n.js").read_text(encoding="utf-8")

    assert "zh-CN" in content
    assert "en-US" in content
    assert "error.readLogs" in content


def test_sidebar_exposes_collaboration_status_targets():
    content = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="accountStatus"' in content
    assert 'id="loginGithubButton"' in content
    assert 'id="loginGiteaButton"' in content
    assert 'id="workspaceStatus"' in content
    assert 'id="linkedRepoStatus"' in content


def test_static_shell_exposes_clean_left_home_navigation():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'class="sidebar-home"' in html
    assert 'id="backToProjectsButton"' in html
    assert 'class="sidebar-back-button"' in html
    assert 'class="back-icon"' in html
    assert 'id="homeBrandButton"' in html
    assert 'class="brand-button"' in html
    assert 'class="brand-icon"' not in html
    assert '<button class="tool-button" data-view="projects"' not in html


def test_login_provider_buttons_are_real_actions():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    for button_id in ("loginGithubButton", "loginGiteaButton"):
        pattern = rf'<button(?P<tag>[^>]*)id="{button_id}"(?P<tag_after>[^>]*)>'
        match = re.search(pattern, html)
        assert match, f"Missing {button_id}"
        tag = f'{match.group("tag")} {match.group("tag_after")}'
        assert "disabled" not in tag
    assert 'id="authConnectionPanel"' in html


def test_i18n_includes_git_provider_collaboration_copy():
    content = (STATIC / "i18n.js").read_text(encoding="utf-8")

    assert "Connect GitHub account" in content
    assert "Connect Gitea account" in content
    assert "No workspace access" in content
    assert "Workspace read-only" in content
    assert "缺少代码仓库访问权限" in content


def test_app_js_fetches_collaboration_status_endpoints():
    content = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "/api/auth/accounts" in content
    assert "/api/workspace/status" in content
    assert "workspaceStatusPath" in content
    assert "project_slug=" in content
    assert "encodeURIComponent(currentProjectId)" in content


def test_app_js_contains_real_auth_flow_hooks():
    content = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "startGithubLogin" in content
    assert "renderGithubForm" in content
    assert "renderGithubClientIdGuide" in content
    assert "whywiki.githubClientId" in content
    assert "https://github.com/settings/applications/new" in content
    assert "/api/auth/github/device/start" in content
    assert "/api/auth/github/device/poll" in content
    assert 'client_id: clientId' in content
    assert "clientId ? { client_id: clientId } : {}" not in content
    assert "startGiteaLogin" in content
    assert "/api/auth/gitea/start" in content
    assert "createExternalLink" in content
    assert "disconnectAccount" in content
    assert "renderAuthConnectionPanel" in content
    assert "authErrorBody" in content
    assert "auth.tokenStorageUnavailableBody" in content


def test_app_js_renders_copyable_github_user_code():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "copyGithubUserCode" in content
    assert "renderGithubUserCode" in content
    assert "navigator.clipboard.writeText" in content
    assert "auth.copyCode" in content
    assert "auth.codeCopied" in content
    assert "auth.copyCodeFailed" in content
    assert "auth-copy-button" in content
    assert ".auth-code-row" in css
    assert ".auth-panel .auth-code-row .auth-copy-button" in css


def test_project_card_menu_uses_elliptical_tool_shape():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert 'createElementNS("http://www.w3.org/2000/svg", "svg")' in content
    assert 'svg.setAttribute("viewBox", "0 0 16 16")' in content
    assert 'circle.setAttribute("cy", String(cy))' in content
    assert "project-card-menu-icon" in content
    assert 'menuButton.append(createVerticalEllipsisIcon())' in content
    assert ".project-card .project-card-menu-button" in css
    assert "width: 34px" in css
    assert "height: 28px" in css
    assert "min-height: 28px" in css
    assert "border-radius: 16px" in css
    assert "min-width: 116px" in css
    assert "border-radius: 22px" in css
    assert "font-size: 12px" in css
    assert "justify-content: center" in css
    assert "text-align: center" in css


def test_auth_external_links_open_new_tab_without_replacing_current_tab():
    content = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "function createExternalLink" in content
    assert 'link.target = "_blank"' in content
    assert 'link.rel = "noopener noreferrer"' in content
    assert "window.location.href = href" not in content


def test_app_js_guards_github_polling_session_state():
    content = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "authFlowId" in content
    assert "githubPollTimer" in content
    assert "clearGithubPollTimer" in content
    assert "nextAuthSessionId" in content
    assert "isCurrentGithubSession" in content
    assert "if (authConnectionState.busy) return;" in content
    assert "authConnectionState.sessionId" in content
    assert "sessionId !== authConnectionState.sessionId" in content
    assert "deviceCode !== authConnectionState.github?.deviceCode" in content
    assert "githubPollTimer = window.setTimeout" in content
    assert "githubLoginButton.disabled = authConnectionState.busy" in content
    assert "giteaLoginButton.disabled = authConnectionState.busy" in content


def test_i18n_contains_real_auth_states():
    content = (STATIC / "i18n.js").read_text(encoding="utf-8")

    assert "Connect GitHub account" in content
    assert "Configure GitHub login" in content
    assert "Get Client ID from GitHub" in content
    assert "Enable Device Flow" in content
    assert "Save and open GitHub authorization" in content
    assert "Connect Gitea account" in content
    assert "Waiting for authorization" in content
    assert "Token storage unavailable" in content
    assert "Run pip install -e . from the WhyWiki checkout, restart whywiki serve, then retry authorization." in content
    assert '"auth.copyCode": "Copy"' in content
    assert "Copied" in content
    assert "Could not copy. Copy the code manually." in content
    assert "打开 GitHub 授权" in content
    assert "配置 GitHub 登录" in content
    assert "去 GitHub 获取 Client ID" in content
    assert "勾选 Enable Device Flow" in content
    assert "保存并打开 GitHub 授权" in content
    assert "WHYWIKI_GITHUB_CLIENT_ID" not in content
    assert "令牌存储不可用" in content
    assert "在 WhyWiki 仓库运行 pip install -e .，重启 whywiki serve 后重新授权。" in content
    assert '"auth.copyCode": "复制"' in content
    assert "已复制" in content
    assert "复制失败，请手动复制验证码。" in content


def test_app_js_renders_workspace_access_report():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "workspace.access" in content
    assert "can_enter_workspace" in content
    assert "can_review" in content
    assert "workspaceAccessDenied" in content
    assert "workspaceReadOnly" in content
    assert ".status-pill.warning" in css


def test_app_js_rerenders_active_view_after_language_change():
    content = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "activeView" in content
    assert "rerenderActiveViewAfterLanguageChange" in content
    assert "function translate(lang, { rerender = false } = {})" in content
    assert 'translate(button.dataset.lang, { rerender: true })' in content


def test_i18n_buttons_have_english_fallback_labels():
    parser = parse_dashboard()

    assert parser.i18n_buttons
    for button in parser.i18n_buttons:
        assert button["text"].strip(), f"Missing fallback label for {button['data_i18n']}"


def test_app_js_handles_unavailable_storage_and_bad_language_data():
    content = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "function storageGet" in content
    assert "function storageSet" in content
    assert "try {" in content
    assert "catch" in content
    assert "function normalizeLanguage" in content
    assert 'dictionaries["en-US"] || {}' in content
    assert "data-i18n-placeholder" in content


def test_app_js_persists_current_project_and_wires_dashboard_endpoints():
    content = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "currentProjectId" in content
    assert 'storageSet("whywiki.currentProjectId"' in content
    assert 'storageGet("whywiki.currentProjectId")' in content
    assert "function returnToProjectsHome" in content
    assert "function renderHomeNavigationLabels" in content
    assert "setCurrentProject(null)" in content
    assert 'document.querySelector("#homeBrandButton")' in content
    assert 'document.querySelector("#backToProjectsButton")' in content
    assert 'addEventListener("click", returnToProjectsHome)' in content
    assert "function renderProjectsHome" in content
    assert "function selectProject" in content
    assert "function deleteProject" in content
    assert "function createVerticalEllipsisIcon" in content
    assert "function closeProjectCardMenus" in content
    assert "function toggleProjectCardMenu" in content
    assert 'method: "DELETE"' in content
    assert 'confirm(t("projects.deleteConfirm"' in content
    assert "project-card-header" in content
    assert "project-card-menu-wrap" in content
    assert "project-card-menu-button" in content
    assert "project-card-menu-icon" in content
    assert "project-card-menu" in content
    assert "action-destructive" in content
    assert 'card.setAttribute("role", "button")' in content
    assert "card.tabIndex = 0" in content
    assert 'card.setAttribute("aria-label", t("projects.openCard").replace("{name}", project.name))' in content
    assert 'card.addEventListener("click", () => selectProject(project))' in content
    assert 'card.addEventListener("keydown", (event) => {' in content
    assert 'event.key === "Enter" || event.key === " "' in content
    assert "event.stopPropagation();" in content
    assert 't("projects.moreActions")' in content
    assert 't("projects.open")' not in content
    assert "project-card-open" not in content
    assert 'createActionButton("...", "tertiary"' not in content
    assert 'actions.append(open, remove)' not in content
    assert "function updateWorkspaceChrome" in content
    assert "useDemoProject" not in content
    assert "/api/demo" not in content
    assert "function visibleWikiPages" in content
    assert 'page.slug !== "handover"' in content
    assert 'document.querySelectorAll("[data-view]")' in content
    assert 'document.querySelectorAll("[data-action]")' in content
    for endpoint in (
        "/api/projects",
        "/api/projects/${projectId}",
        "/api/projects/${projectId}/conflicts",
        "/api/projects/${projectId}/wiki",
        "/api/projects/${projectId}/wiki/${slug}",
        "/api/projects/${projectId}/handover",
        "/api/projects/${projectId}/ask",
        "/api/projects/${projectId}/sources",
        "/api/projects/${projectId}/facts",
    ):
        assert endpoint in content
    assert "/api/projects/${project.id}" in content


def test_i18n_contains_dynamic_dashboard_keys_for_each_language():
    languages = parse_i18n_keys()
    dynamic_keys = {
        "projects.title",
        "projects.empty",
        "projects.openCard",
        "projects.moreActions",
        "projects.delete",
        "projects.deleteConfirm",
        "projects.deleteFailed",
        "projects.noDescription",
        "nav.home",
        "nav.backToProjects",
        "status.title",
        "status.subtitle",
        "status.current",
        "status.recent",
        "status.review",
        "status.stable",
        "status.changed",
        "status.evidence",
        "status.needsReview",
        "review.title",
        "review.subtitle",
        "settings.export",
        "settings.handover",
        "project.create.title",
        "project.create.name",
        "project.create.description",
        "project.create.submit",
        "ingest.title",
        "ingest.path",
        "ingest.sourceType",
        "ingest.submit",
        "ingest.ready",
        "build.loading",
        "build.ready",
        "build.requirementsCreated",
        "build.conflictsCreated",
        "build.pagesCreated",
        "view.noProject",
        "view.loading",
        "view.error",
        "view.sources.title",
        "view.requirements.title",
        "view.wiki.title",
        "view.conflicts.title",
        "view.handover.title",
        "view.ask.title",
        "view.empty",
        "ask.defaultQuestion",
        "ask.submit",
        "field.path",
        "field.title",
        "field.type",
        "field.statement",
        "field.confidence",
        "field.status",
        "field.severity",
        "field.evidence",
        "field.sourcesCreated",
        "field.blocksCreated",
        "field.filesSeen",
        "field.skippedFiles",
    }

    for language, language_keys in languages.items():
        assert not dynamic_keys - language_keys, f"{language} missing keys: {sorted(dynamic_keys - language_keys)}"


def test_projects_home_does_not_render_redundant_subtitle_copy():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    i18n = (STATIC / "i18n.js").read_text(encoding="utf-8")

    assert "projects.subtitle" not in content
    assert "projects.subtitle" not in i18n
    assert "Open a saved project, or create a new one for this repository." not in i18n
    assert "打开当前仓库已经维护的项目" not in i18n


def test_projects_home_header_balances_title_and_create_action():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "function createProjectIcon" in content
    assert 'title.classList.add("project-home-title")' in content
    assert 'createButton.className = "action-secondary project-home-create-button"' in content
    assert "createButton.prepend(createProjectIcon())" in content
    assert "header.append(title, createButton)" in content
    assert "panel.prepend(header)" in content
    assert "header.append(createButton)" not in content
    assert "panel.append(header)" not in content
    assert ".project-home-title" in css
    assert ".project-home-create-button" in css
    assert ".project-home-create-icon" in css


def test_projects_home_supports_multi_select_project_tags():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    i18n = (STATIC / "i18n.js").read_text(encoding="utf-8")

    for symbol in (
        "let selectedProjectTags",
        "function projectTags",
        "function projectMatchesTags",
        "function renderProjectTagFilters",
        "function toggleProjectTagFilter",
        "function renderProjectTags",
        "function showBatchAddProjectTagModal",
        "function showEditProjectTagsModal",
        "function saveProjectTags",
        "function closeProjectTagModal",
        "function renderSelectableProjectCards",
    ):
        assert symbol in content

    assert 'project.tags || parseJsonList(project.tags_json)' in content
    assert 'selectedProjectTags.every((tag) => tags.includes(tag))' in content
    assert 'api(`/api/projects/${project.id}`, {' in content
    assert 'method: "PATCH"' in content
    assert '"projects.tags.title": "Tags"' in i18n
    assert '"projects.tags.title": "标签"' in i18n
    assert '"projects.tags.add": "Add tag"' in i18n
    assert '"projects.tags.add": "新增标签"' in i18n
    assert '"projects.tags.batchTitle": "Add tag to projects"' in i18n
    assert '"projects.tags.batchTitle": "新增标签"' in i18n
    assert '"projects.tags.clear": "Clear filters"' in i18n
    assert '"projects.tags.clear": "清除筛选"' in i18n
    assert ".project-tag-filter-bar" in css
    assert ".project-tag-chip" in css
    assert ".project-card-tags" in css
    assert ".project-tag-modal-backdrop" in css
    assert ".project-tag-modal-panel" in css
    assert ".project-select-card" in css


def test_chinese_navigation_uses_demand_workspace_terms():
    content = (STATIC / "i18n.js").read_text(encoding="utf-8")

    assert '"nav.home": "主页"' in content
    assert '"nav.requirements": "需求"' in content
    assert '"nav.conflicts": "冲突"' in content
    assert '"nav.sources": "来源"' in content
    assert '"nav.ask": "问答"' in content


def test_i18n_does_not_expose_demo_product_copy():
    languages = parse_i18n_keys()

    for language, language_keys in languages.items():
        assert not {key for key in language_keys if key.startswith("demo.")}
        assert "action.useDemo" not in language_keys
        assert "start.demo" not in language_keys
        assert "nav.start" not in language_keys
        assert "project.create.ready" not in language_keys
        assert "field.projectId" not in language_keys


def test_styles_include_mobile_overflow_guards():
    content = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "@media (max-width: 720px)" in content
    assert "min-width: 0;" in content
    assert "flex-wrap: wrap;" in content
    assert "display: block;" in content


def test_language_switch_has_bouncing_bubble_state():
    parser = parse_dashboard()
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert parser.language_switches == ["en-US"]
    assert ".language-switch::before" in css
    assert "language-bubble-hop" in css
    assert "[data-active-lang=\"en-US\"]" in css
    assert "function updateLanguageSwitch" in js
    assert "aria-pressed" in js
    assert "is-bouncing" in js


def test_app_js_exposes_project_guidance_and_evidence_components():
    content = (STATIC / "app.js").read_text(encoding="utf-8")

    for symbol in (
        "function deriveProjectState",
        "function renderProjectStatusHero",
        "function renderOnboardingSteps",
        "function renderNextActionPanel",
        "function renderEmptyState",
        "function renderOperationFeedback",
        "function renderStatusBadge",
        "function renderSourceBadge",
        "function renderEvidenceBadge",
        "function renderEvidenceDrawer",
        "function loadEvidenceDetails",
        "function renderFactCard",
        "function renderConflictCard",
        "function renderWikiReader",
        "function updateConflictStatus",
        "function updateFactStatus",
        "function startProjectJob",
        "function pollProjectJob",
        "function renderJobProgress",
    ):
        assert symbol in content

    for action in (
        "connectSource",
        "scanProject",
        "generateEvidenceWiki",
        "reviewConflicts",
        "askWithEvidence",
        "generateHandover",
    ):
        assert action in content

    for endpoint in (
        "/api/projects/${projectId}/facts/${factId}",
        "/api/projects/${projectId}/facts/${factId}/evidence",
        "/api/projects/${projectId}/conflicts/${conflictId}/evidence",
        "/api/projects/${projectId}/ingest-jobs",
        "/api/projects/${projectId}/build-jobs",
        "/api/jobs/${jobId}",
    ):
        assert endpoint in content


def test_app_js_defines_requirement_semantic_helpers():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    review_start = content.index("function reviewFactRows")
    requirement_start = content.index("function requirementRows")
    review_body = content[review_start:requirement_start]

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
    assert 'fact.status === "candidate"' in review_body


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
    assert 'button.setAttribute("data-filter", filter)' in content
    assert 'renderRequirementFilterChip("conflict"' in content
    assert 'renderRequirementFilterChip("needs-review"' in content
    assert 'renderRequirementFilterChip("confirmed"' in content
    assert 'renderRequirementFilterChip("recent"' in content
    assert 'renderRequirementFilterChip("source-backed"' in content
    assert "scrollIntoView" in content
    assert "'.requirements-all [data-requirement-conflict=\"true\"]'" in content
    assert ".requirement-filter-chip" in css
    assert ".requirement-conflict-jump" in css
    assert ".requirement-card.is-jump-target" in css


def test_project_home_body_and_preview_badges_track_project_state():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    languages = parse_i18n_keys()
    render_start = content.index("async function renderProjectHome")
    status_start = content.index("async function renderStatus")
    render_body = content[render_start:status_start]

    required_keys = {
        "projectHome.emptyBody",
        "projectHome.generateBody",
        "projectHome.noRequirementsBody",
        "projectHome.readyBody",
    }
    for language, language_keys in languages.items():
        assert not required_keys - language_keys, f"{language} missing keys: {sorted(required_keys - language_keys)}"

    assert "function projectHomeBodyKey" in content
    assert 'if (!sources.length) return "projectHome.emptyBody";' in content
    assert 'if (requirements.length) return "projectHome.readyBody";' in content
    assert "facts.length || visibleWikiPages(pages).length" in content
    assert 'return hasGeneratedMaterial ? "projectHome.noRequirementsBody" : "projectHome.generateBody";' in content
    assert 'requirements.length ? t("projectHome.readyBody") : t("projectHome.emptyBody")' not in render_body
    assert 'createPanel(t("projectHome.title"))' not in render_body
    assert 'panel.setAttribute("aria-label", t("projectHome.title"))' in render_body

    for selector in (
        ".status-badge-conflict",
        ".status-badge-low-confidence",
        ".status-badge-needs-review",
        ".status-badge-confirmed",
        ".status-badge-source-backed",
    ):
        assert selector in css


def test_requirement_semantic_helpers_prioritize_evidence_gaps():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    status_start = content.index("function requirementStatusKind")
    label_start = content.index("function requirementStatusLabel")
    status_body = content[status_start:label_start]
    visible_start = content.index("function visibleRequirementRows")
    evidence_start = content.index("function evidenceItems")
    visible_body = content[visible_start:evidence_start]

    conflict_pos = status_body.index('row.validity_status === "conflicting"')
    low_confidence_pos = status_body.index('!evidenceItems(row).length')
    needs_review_pos = status_body.index('row.status === "needs_review"')
    confirmed_pos = status_body.index('row.status === "confirmed"')

    assert conflict_pos < low_confidence_pos < needs_review_pos < confirmed_pos
    assert 'filters.has("source-backed") && kind === "source-backed"' in content
    assert 'filters.has("source-backed") && requirementSourceCount(row) > 0' not in content
    assert "row.updated_at || row.recent || row.recently_touched" in visible_body
    assert "row.created_at" not in visible_body


def test_styles_define_whywiki_visual_language_and_states():
    content = (STATIC / "styles.css").read_text(encoding="utf-8")

    for token in (
        "--source-git",
        "--source-doc",
        "--source-code",
        "--ai",
        "--confirmed",
        "--conflict",
        "--stale",
        "--needs-review",
    ):
        assert token in content

    for selector in (
        ".project-status-hero",
        ".next-action-panel",
        ".onboarding-steps",
        ".empty-state",
        ".sidebar-home",
        ".brand-button",
        ".sidebar .brand-button:hover",
        ".sidebar-back-button",
        ".back-icon",
        "body.has-current-project .sidebar-back-button",
        '.project-card[role="button"]',
        '.project-card[role="button"]:hover',
        '.project-card[role="button"]:focus-visible',
        ".project-card-header",
        ".project-card-menu-wrap",
        ".project-card-menu-button",
        ".project-card-menu-icon",
        ".project-card-menu",
        ".operation-feedback",
        ".job-progress",
        ".progress-track",
        ".status-badge",
        ".source-badge",
        ".evidence-badge",
        ".evidence-drawer",
        ".fact-card",
        ".conflict-card",
        ".wiki-reader",
        ".action-secondary",
        ".action-tertiary",
        ".action-destructive",
        ".action-ai",
        "button:disabled",
        "button:focus-visible",
    ):
        assert selector in content
    assert ".sidebar .brand-button:hover,\n.sidebar .sidebar-back-button:hover" not in content


def test_i18n_contains_p0_p1_ux_copy_for_each_language():
    languages = parse_i18n_keys()
    required_keys = {
        "dashboard.statusHero.title",
        "dashboard.statusHero.subtitle",
        "dashboard.nextAction.title",
        "dashboard.onboarding.title",
        "workflow.createProject",
        "workflow.connectSource",
        "workflow.scanProject",
        "workflow.generateWiki",
        "workflow.reviewEvidence",
        "workflow.askHandover",
        "empty.sources.title",
        "empty.sources.body",
        "empty.facts.title",
        "empty.facts.body",
        "empty.wiki.title",
        "empty.wiki.body",
        "empty.conflicts.title",
        "empty.conflicts.body",
        "empty.evidence.title",
        "empty.evidence.body",
        "operation.ingest.loading",
        "operation.ingest.success",
        "operation.build.loading",
        "operation.build.success",
        "operation.ask.loading",
        "operation.job.running",
        "operation.job.succeeded",
        "operation.job.failed",
        "operation.error.recovery",
        "badge.git",
        "badge.document",
        "badge.code",
        "badge.aiInference",
        "badge.evidenceBacked",
        "badge.needsReview",
        "badge.confirmed",
        "badge.conflict",
        "badge.lowConfidence",
        "action.connectSource",
        "action.scanProject",
        "action.generateEvidenceWiki",
        "action.reviewConflicts",
        "action.askWithEvidence",
        "action.generateHandover",
        "action.viewEvidence",
        "action.viewSource",
        "action.confirmRequirement",
        "action.resolveConflict",
        "action.ignoreConflict",
        "action.retry",
        "empty.requirements.title",
        "empty.requirements.body",
        "requirements.attentionTitle",
        "requirement.supportingFacts",
        "sources.drawer.title",
        "evidence.drawer.title",
        "evidence.drawer.loading",
        "evidence.drawer.openOriginal",
        "evidence.blockText",
        "evidence.confidence.multiSource",
        "evidence.confidence.singleSource",
        "evidence.confidence.aiInferred",
        "ask.noEvidence.title",
        "ask.noEvidence.body",
    }

    for language, language_keys in languages.items():
        assert not required_keys - language_keys, f"{language} missing keys: {sorted(required_keys - language_keys)}"


def test_i18n_contains_requirement_lifecycle_terms_for_each_language():
    languages = parse_i18n_keys()
    keys = {
        "requirement.status.current",
        "requirement.status.candidate",
        "requirement.status.needsReview",
        "requirement.status.confirmed",
        "requirement.status.superseded",
        "requirement.status.rejected",
        "requirement.status.historical",
        "requirement.status.conflicting",
        "conflict.severity.high",
        "conflict.severity.medium",
        "conflict.severity.low",
        "conflict.severity.unknown",
        "conflict.status.open",
        "conflict.status.resolved",
        "conflict.status.ignored",
        "conflict.status.unknown",
        "source.status.active",
        "source.status.partiallyOutdated",
        "source.status.outdated",
        "source.status.conflicting",
        "source.status.referenceOnly",
        "action.acceptAsCurrent",
        "action.mergeRequirement",
        "action.markOutdated",
        "action.leaveForLater",
        "action.ignoreThisConflict",
        "decision.reasonPlaceholder",
        "decision.createdStatementPlaceholder",
    }
    for language, language_keys in languages.items():
        assert not keys - language_keys, f"{language} missing keys: {sorted(keys - language_keys)}"

    content = (STATIC / "i18n.js").read_text(encoding="utf-8")
    assert '"requirement.status.current": "当前有效"' in content
    assert '"requirement.status.superseded": "已被替代"' in content
    assert '"requirement.status.current": "Current"' in content
    assert '"requirement.status.superseded": "Superseded"' in content
    assert '"conflict.severity.medium": "中风险"' in content
    assert '"conflict.status.open": "待处理"' in content
    assert '"conflict.severity.medium": "Medium"' in content
    assert '"conflict.status.open": "Open"' in content


def test_app_js_uses_snapshot_and_localized_lifecycle_labels():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    for symbol in (
        "function requirementLifecycleStatus",
        "function requirementStatusLabel",
        "function conflictSeverityLabel",
        "function conflictStatusLabel",
        "function snapshotSourceStatuses",
        "function renderSourceStatusCards",
        "function requirementsForConflict",
        "function isRequirementConflict",
        "function renderLegacyConflictActions",
        "function renderRequirementSnapshot",
        "function submitRequirementDecision",
        "/api/projects/${projectId}/requirements/snapshot",
        "/api/projects/${projectId}/conflicts/${conflictId}/decision",
    ):
        assert symbol in content
    assert "fact.lifecycleStatus" in content
    assert "fact.validityStatus" in content
    assert "Object.values(snapshot.source_statuses || {})" in content
    assert "const facts = await api(`/api/projects/${projectId}/facts`);" in content
    assert "const [sources, facts, conflicts, pages, snapshot] = await Promise.all" in content
    assert "const currentRequirements = snapshot.current || [];" in content
    assert 'appendSection(panel, t("status.current"), renderStateCards(facts, 8));' not in content
    assert "fieldValue(conflict.status)" not in content
    assert "fieldValue(conflict.severity)" not in content
    assert "const known = new Set([\"high\", \"medium\", \"low\"]);" in content
    assert "const known = new Set([\"open\", \"resolved\", \"ignored\"]);" in content
    assert "t(`conflict.severity.${normalized}`)" in content
    assert "t(`conflict.status.${normalized}`)" in content
    assert 'return t("action.ignoreThisConflict")' not in content
    assert 'return t("action.resolveConflict")' not in content
    assert 'action: "merge_requirement"' in content
    assert 'action: "mark_outdated"' in content
    assert "rejected_fact_ids: targets" in content
    assert "requirementsForConflict(conflict, requirements)" in content
    assert '["requirement", "requirement_conflict"].includes(conflict.conflict_type)' in content
    assert "renderLegacyConflictActions(conflict, actions)" in content
    assert "actions.append(...renderLegacyConflictActions(conflict, actions));" in content
    assert ".status-badge-current" in css
    assert ".status-badge-superseded" in css
    assert ".source-status-partially_outdated" in css
