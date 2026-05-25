const supportedLanguages = ["zh-CN", "en-US"];
const githubClientIdStorageKey = "whywiki.githubClientId";
let currentProjectId = storageGet("whywiki.currentProjectId");
let currentProject = null;
let activeView = "projects";
let languageBounceTimer = null;
let authFlowId = 0;
let githubPollTimer = null;
let githubCopyResetTimer = null;
let requirementFilterState = new Set(["all"]);
let activeConflictRequirementId = null;
let requirementJumpTimer = null;
let collaborationState = {
  accounts: [],
  workspace: { configured: false, workspace: null },
  loaded: false,
};
let authConnectionState = {
  sessionId: null,
  mode: "idle",
  busy: false,
  message: null,
  github: null,
  gitea: null,
};

function dictionary() {
  const dictionaries = window.WhyWikiI18n || {};
  const lang = normalizeLanguage(document.documentElement.lang);
  return dictionaries[lang] || dictionaries["en-US"] || {};
}

function t(key) {
  return dictionary()[key] || key;
}

function storageGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key, value) {
  try {
    if (value === null || value === undefined || value === "") {
      localStorage.removeItem(key);
      return;
    }
    localStorage.setItem(key, value);
  } catch {
    return;
  }
}

function normalizeLanguage(lang) {
  return supportedLanguages.includes(lang) ? lang : "en-US";
}

function initialLanguage() {
  const saved = storageGet("whywiki.language");
  if (supportedLanguages.includes(saved)) return saved;
  return typeof navigator !== "undefined" && navigator.language && navigator.language.startsWith("zh") ? "zh-CN" : "en-US";
}

function updateLanguageSwitch(lang) {
  const switcher = document.querySelector(".language-switch");
  if (!switcher) return;
  switcher.dataset.activeLang = lang;
  switcher.querySelectorAll("[data-lang]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.lang === lang));
  });
  switcher.classList.remove("is-bouncing");
  window.requestAnimationFrame(() => {
    switcher.classList.add("is-bouncing");
    clearTimeout(languageBounceTimer);
    languageBounceTimer = setTimeout(() => switcher.classList.remove("is-bouncing"), 360);
  });
}

function translate(lang, { rerender = false } = {}) {
  const normalizedLang = normalizeLanguage(lang);
  const dictionaries = window.WhyWikiI18n || {};
  const dict = dictionaries[normalizedLang] || dictionaries["en-US"] || {};
  document.documentElement.lang = normalizedLang;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = dict[node.dataset.i18n] || node.dataset.i18n;
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.placeholder = dict[node.dataset.i18nPlaceholder] || node.dataset.i18nPlaceholder;
  });
  updateLanguageSwitch(normalizedLang);
  renderHomeNavigationLabels();
  storageSet("whywiki.language", normalizedLang);
  if (collaborationState.loaded) {
    renderAccountStatus(collaborationState.accounts);
    renderWorkspaceStatus(collaborationState.workspace);
    renderAuthConnectionPanel();
  }
  if (rerender) {
    rerenderActiveViewAfterLanguageChange();
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      detail = response.statusText;
    }
    throw new Error(detail);
  }
  return response.json();
}

async function apiText(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      detail = response.statusText;
    }
    throw new Error(detail);
  }
  return response.text();
}

function authPanel() {
  return document.querySelector("#authConnectionPanel");
}

function renderAuthMessage(kind, title, body = "") {
  const message = createElement("div", `auth-message auth-message-${kind}`);
  message.append(createElement("strong", "", title));
  if (body) message.append(createElement("p", "", body));
  return message;
}

function isTokenStorageError(error) {
  return Boolean(error?.message && error.message.toLowerCase().includes("token storage"));
}

function authErrorTitle(error, fallbackKey = "auth.failed") {
  return isTokenStorageError(error) ? t("auth.tokenStorageUnavailable") : t(fallbackKey);
}

function authErrorBody(error, fallbackKey = "auth.failed") {
  return isTokenStorageError(error) ? t("auth.tokenStorageUnavailableBody") : (error.message || t(fallbackKey));
}

function nextAuthSessionId() {
  authFlowId += 1;
  return authFlowId;
}

function clearGithubPollTimer() {
  if (githubPollTimer !== null) {
    window.clearTimeout(githubPollTimer);
    githubPollTimer = null;
  }
}

function clearGithubCopyResetTimer() {
  if (githubCopyResetTimer !== null) {
    window.clearTimeout(githubCopyResetTimer);
    githubCopyResetTimer = null;
  }
}

function isCurrentGithubSession(sessionId, deviceCode) {
  if (sessionId !== authConnectionState.sessionId) return false;
  if (authConnectionState.mode !== "github_waiting") return false;
  if (deviceCode !== authConnectionState.github?.deviceCode) return false;
  return true;
}

function savedGithubClientId() {
  return storageGet(githubClientIdStorageKey) || "";
}

function showGithubConfiguration(message = null) {
  clearGithubPollTimer();
  authConnectionState = {
    sessionId: nextAuthSessionId(),
    mode: "github_form",
    busy: false,
    message: message || { kind: "info", title: t("auth.githubSetupTitle"), body: t("auth.githubClientIdHelp") },
    github: { clientId: savedGithubClientId() },
    gitea: null,
  };
  renderAuthConnectionPanel();
}

async function startGithubLogin() {
  if (authConnectionState.busy) return;
  if (authConnectionState.mode === "github_waiting") return;
  const clientId = savedGithubClientId();
  if (!clientId) {
    showGithubConfiguration();
    return;
  }
  startGithubDeviceLogin(clientId);
}

async function startGithubDeviceLogin(clientIdInput = "") {
  const clientId = String(clientIdInput || "").trim();
  if (!clientId) {
    showGithubConfiguration({
      kind: "info",
      title: t("auth.githubSetupTitle"),
      body: t("auth.githubClientIdRequired"),
    });
    return;
  }
  clearGithubPollTimer();
  const sessionId = nextAuthSessionId();
  authConnectionState = {
    sessionId,
    mode: "github_waiting",
    busy: true,
    message: { kind: "loading", title: t("auth.waiting"), body: t("auth.githubOpening") },
    github: { clientId },
    gitea: null,
  };
  renderAuthConnectionPanel();

  try {
    const result = await api("/api/auth/github/device/start", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId }),
    });
    if (sessionId !== authConnectionState.sessionId || authConnectionState.mode !== "github_waiting") return;
    if (!result.device_code) throw new Error(result.error_description || result.error || t("auth.failed"));
    storageSet(githubClientIdStorageKey, clientId);
    const deviceCode = result.device_code;
    authConnectionState = {
      sessionId,
      mode: "github_waiting",
      busy: false,
      message: null,
      github: {
        clientId,
        deviceCode,
        userCode: result.user_code,
        verificationUri: result.verification_uri,
        interval: result.interval || result.poll_after_seconds || 5,
      },
      gitea: null,
    };
    renderAuthConnectionPanel();
    pollGithubDevice(sessionId, deviceCode);
  } catch (error) {
    if (sessionId !== authConnectionState.sessionId) return;
    clearGithubPollTimer();
    const needsClientId = error.message && /client id/i.test(error.message);
    if (needsClientId) {
      showGithubConfiguration({
        kind: "info",
        title: t("auth.githubSetupTitle"),
        body: t("auth.githubClientIdRequired"),
      });
      return;
    }
    authConnectionState = {
      ...authConnectionState,
      mode: "github_form",
      busy: false,
      message: {
        kind: "error",
        title: authErrorTitle(error, "auth.setupNeeded"),
        body: authErrorBody(error, "auth.failed"),
      },
      github: { clientId },
    };
    renderAuthConnectionPanel();
  }
}

async function pollGithubDevice(sessionId, deviceCode) {
  const github = authConnectionState.github;
  if (!github?.deviceCode || !isCurrentGithubSession(sessionId, deviceCode)) return;

  try {
    const clientId = github.clientId || "";
    if (!clientId) {
      showGithubConfiguration({
        kind: "info",
        title: t("auth.githubSetupTitle"),
        body: t("auth.githubClientIdRequired"),
      });
      return;
    }
    const pollBody = {
      device_code: github.deviceCode,
      current_interval: github.interval,
      client_id: clientId,
    };
    const result = await api("/api/auth/github/device/poll", {
      method: "POST",
      body: JSON.stringify(pollBody),
    });
    if (!isCurrentGithubSession(sessionId, deviceCode)) return;

    if (result.status === "connected") {
      clearGithubPollTimer();
      authConnectionState = {
        sessionId,
        mode: "connected",
        busy: false,
        message: { kind: "success", title: t("auth.connected"), body: providerAccountLabel(result.identity || {}) },
        github: null,
        gitea: null,
      };
      renderAuthConnectionPanel();
      await loadCollaborationStatus();
      return;
    }

    const nextInterval = result.poll_after_seconds || result.interval || github.interval;
    authConnectionState.github = { ...github, interval: nextInterval };
    authConnectionState.message = { kind: "loading", title: t("auth.waiting"), body: t("auth.githubOpening") };
    renderAuthConnectionPanel();
    clearGithubPollTimer();
    githubPollTimer = window.setTimeout(() => pollGithubDevice(sessionId, deviceCode), Math.max(1, nextInterval) * 1000);
  } catch (error) {
    if (!isCurrentGithubSession(sessionId, deviceCode)) return;
    clearGithubPollTimer();
    clearGithubCopyResetTimer();
    authConnectionState = {
      ...authConnectionState,
      mode: "github_failed",
      busy: false,
      message: {
        kind: "error",
        title: authErrorTitle(error),
        body: authErrorBody(error),
      },
      github: null,
    };
    renderAuthConnectionPanel();
  }
}

async function copyGithubUserCode(userCode) {
  const code = String(userCode || "").trim();
  if (!code || authConnectionState.busy) return;
  clearGithubCopyResetTimer();
  try {
    await navigator.clipboard.writeText(code);
    authConnectionState.github = { ...authConnectionState.github, copyState: "copied" };
    renderAuthConnectionPanel();
    githubCopyResetTimer = window.setTimeout(() => {
      if (authConnectionState.github?.userCode === code) {
        authConnectionState.github = { ...authConnectionState.github, copyState: null };
        renderAuthConnectionPanel();
      }
      githubCopyResetTimer = null;
    }, 1800);
  } catch {
    authConnectionState.message = {
      kind: "error",
      title: t("auth.failed"),
      body: t("auth.copyCodeFailed"),
    };
    authConnectionState.github = { ...authConnectionState.github, copyState: "failed" };
    renderAuthConnectionPanel();
  }
}

function renderGithubUserCode(userCode) {
  const row = createElement("div", "auth-code-row");
  const code = createElement("code", "auth-code", userCode);
  const copy = createActionButton(
    authConnectionState.github?.copyState === "copied" ? t("auth.codeCopied") : t("auth.copyCode"),
    "secondary",
    () => copyGithubUserCode(userCode),
  );
  copy.classList.add("auth-copy-button");
  copy.disabled = authConnectionState.busy || !userCode;
  row.append(code, copy);
  return row;
}

function renderGithubForm() {
  const form = createElement("form", "auth-form");
  const hint = createElement("p", "auth-form-hint", t("auth.githubClientIdHelp"));
  const clientIdInput = document.createElement("input");
  clientIdInput.name = "client_id";
  clientIdInput.type = "text";
  clientIdInput.autocomplete = "off";
  clientIdInput.required = true;
  clientIdInput.value = authConnectionState.github?.clientId || savedGithubClientId();
  clientIdInput.placeholder = "Ov23li...";

  appendLabeledControl(form, t("auth.clientId"), clientIdInput);
  form.append(hint);
  form.append(renderGithubClientIdGuide());
  const submit = createActionButton(t("auth.openGithubConfigured"), "primary");
  submit.type = "submit";
  submit.disabled = authConnectionState.busy;
  form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const clientId = String(formData.get("client_id") || "").trim();
    if (!clientId) {
      showGithubConfiguration({
        kind: "error",
        title: t("auth.setupNeeded"),
        body: t("auth.githubClientIdRequired"),
      });
      return;
    }
    startGithubDeviceLogin(clientId);
  });
  return form;
}

function renderGithubClientIdGuide() {
  const guide = createElement("div", "auth-guide");
  guide.append(
    createElement("strong", "", t("auth.githubGuideTitle")),
    createElement("p", "auth-form-hint", t("auth.githubGuideBody")),
    createExternalLink("https://github.com/settings/applications/new", t("auth.githubGuideOpen"), "secondary"),
  );

  const values = createElement("div", "auth-guide-values");
  appendGuideValue(values, t("auth.githubGuideAppName"), "WhyWiki Local");
  appendGuideValue(values, t("auth.githubGuideHomepage"), "http://127.0.0.1:8765/");
  appendGuideValue(values, t("auth.githubGuideCallback"), "http://127.0.0.1:8765/");

  const steps = createElement("ol", "auth-guide-steps");
  [
    t("auth.githubGuideStepCreate"),
    t("auth.githubGuideStepDeviceFlow"),
    t("auth.githubGuideStepCopy"),
  ].forEach((stepText) => {
    steps.append(createElement("li", "", stepText));
  });

  guide.append(values, steps, createElement("p", "auth-form-hint", t("auth.githubGuideNoSecret")));
  return guide;
}

function appendGuideValue(parent, labelText, valueText) {
  const row = createElement("div", "auth-guide-value");
  row.append(createElement("span", "", labelText), createElement("code", "", valueText));
  parent.append(row);
}

function renderGiteaForm() {
  const form = createElement("form", "auth-form");
  const baseUrlInput = document.createElement("input");
  baseUrlInput.name = "base_url";
  baseUrlInput.type = "url";
  baseUrlInput.placeholder = "https://git.example.test";
  baseUrlInput.required = true;
  baseUrlInput.value = authConnectionState.gitea?.baseUrl || "";

  const clientIdInput = document.createElement("input");
  clientIdInput.name = "client_id";
  clientIdInput.type = "text";
  clientIdInput.autocomplete = "off";
  clientIdInput.required = true;
  clientIdInput.value = authConnectionState.gitea?.clientId || "";

  appendLabeledControl(form, t("auth.giteaBaseUrl"), baseUrlInput);
  appendLabeledControl(form, t("auth.clientId"), clientIdInput);
  const submit = createActionButton(t("auth.openGitea"), "primary");
  submit.type = "submit";
  submit.disabled = authConnectionState.busy;
  form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    startGiteaLogin(new FormData(form));
  });
  return form;
}

async function startGiteaLogin(formData) {
  if (authConnectionState.busy) return;
  clearGithubPollTimer();
  const sessionId = nextAuthSessionId();
  const baseUrl = String(formData.get("base_url") || "").trim();
  const clientId = String(formData.get("client_id") || "").trim();
  authConnectionState = {
    sessionId,
    mode: "gitea_form",
    busy: true,
    message: { kind: "loading", title: t("auth.waiting"), body: t("auth.giteaReturn") },
    github: null,
    gitea: { baseUrl, clientId },
  };
  renderAuthConnectionPanel();

  try {
    const result = await api("/api/auth/gitea/start", {
      method: "POST",
      body: JSON.stringify({ base_url: baseUrl, client_id: clientId }),
    });
    if (sessionId !== authConnectionState.sessionId || authConnectionState.mode !== "gitea_form") return;
    authConnectionState = {
      sessionId,
      mode: "gitea_redirect",
      busy: false,
      message: { kind: "loading", title: t("auth.waiting"), body: t("auth.giteaReturn") },
      github: null,
      gitea: {
        baseUrl,
        clientId,
        authorizationUrl: result.authorization_url,
      },
    };
    renderAuthConnectionPanel();
  } catch (error) {
    if (sessionId !== authConnectionState.sessionId) return;
    authConnectionState = {
      ...authConnectionState,
      busy: false,
      message: {
        kind: "error",
        title: authErrorTitle(error),
        body: authErrorBody(error),
      },
    };
    renderAuthConnectionPanel();
  }
}

async function disconnectAccount(identityKey) {
  if (!identityKey) return;
  clearGithubPollTimer();
  const sessionId = nextAuthSessionId();
  authConnectionState = {
    ...authConnectionState,
    sessionId,
    busy: true,
    message: { kind: "loading", title: t("auth.waiting"), body: "" },
  };
  renderAuthConnectionPanel();
  try {
    await api(`/api/auth/accounts/${encodeURIComponent(identityKey)}`, { method: "DELETE" });
    authConnectionState = { sessionId, mode: "idle", busy: false, message: null, github: null, gitea: null };
    await loadCollaborationStatus();
  } catch (error) {
    authConnectionState = {
      ...authConnectionState,
      busy: false,
      message: {
        kind: "error",
        title: authErrorTitle(error),
        body: authErrorBody(error),
      },
    };
    renderAuthConnectionPanel();
  }
}

function accountIdentityKey(identity) {
  if (identity.identity_key) return identity.identity_key;
  if (identity.provider === "github" && identity.provider_user_id) return `github:${identity.provider_user_id}`;
  if (identity.provider === "gitea" && identity.base_url && identity.provider_user_id) {
    return `gitea:${identity.base_url}:${identity.provider_user_id}`;
  }
  return "";
}

function renderAuthConnectionPanel() {
  const panel = authPanel();
  if (!panel) return;
  const githubLoginButton = document.querySelector("#loginGithubButton");
  if (githubLoginButton) githubLoginButton.disabled = authConnectionState.busy;
  if (githubLoginButton && authConnectionState.mode === "github_waiting") githubLoginButton.disabled = true;
  const giteaLoginButton = document.querySelector("#loginGiteaButton");
  if (giteaLoginButton) giteaLoginButton.disabled = authConnectionState.busy;

  const children = [];
  if (authConnectionState.message) {
    children.push(renderAuthMessage(authConnectionState.message.kind, authConnectionState.message.title, authConnectionState.message.body));
  }

  if (authConnectionState.github?.deviceCode) {
    const githubBox = createElement("div", "auth-flow auth-flow-github");
    githubBox.append(createElement("strong", "", t("auth.githubTitle")));
    if (authConnectionState.github.userCode) {
      githubBox.append(renderGithubUserCode(authConnectionState.github.userCode));
    }
    if (authConnectionState.github.verificationUri) {
      const open = createExternalLink(authConnectionState.github.verificationUri, t("auth.openGithub"), "secondary");
      githubBox.append(open);
    }
    children.push(githubBox);
  }

  if (authConnectionState.mode === "github_form") {
    const githubFormBox = createElement("div", "auth-flow auth-flow-github");
    githubFormBox.append(createElement("strong", "", t("auth.githubSetupTitle")), renderGithubForm());
    children.push(githubFormBox);
  }

  if (authConnectionState.mode === "gitea_form") {
    const giteaBox = createElement("div", "auth-flow auth-flow-gitea");
    giteaBox.append(createElement("strong", "", t("auth.giteaTitle")), renderGiteaForm());
    children.push(giteaBox);
  }

  if (authConnectionState.gitea?.authorizationUrl) {
    const open = createExternalLink(authConnectionState.gitea.authorizationUrl, t("auth.openGitea"), "secondary");
    const hint = renderAuthMessage("loading", t("auth.waiting"), t("auth.giteaReturn"));
    children.push(hint, open);
  }

  const accounts = Array.isArray(collaborationState.accounts) ? collaborationState.accounts : [];
  if (accounts.length) {
    const list = createElement("div", "auth-account-list");
    accounts.forEach((identity) => {
      const row = createElement("div", "auth-account-row");
      const meta = createElement("span", "auth-account-meta", providerAccountLabel(identity));
      if (identity.base_url) meta.title = identity.base_url;
      const identityKey = accountIdentityKey(identity);
      const disconnect = createActionButton(t("auth.disconnect"), "tertiary", () => disconnectAccount(identityKey));
      disconnect.disabled = !identityKey || authConnectionState.busy;
      row.append(meta, disconnect);
      list.append(row);
    });
    children.push(list);
  }

  panel.replaceChildren(...children);
}

function providerAccountLabel(identity) {
  const provider = identity.provider || "provider";
  const account = identity.account || identity.provider_user_id || "";
  return account ? `${provider}:${account}` : provider;
}

function renderAccountStatus(accounts) {
  const status = document.querySelector("#accountStatus");
  if (!status) return;

  const accountList = Array.isArray(accounts) ? accounts : [];
  if (!accountList.length) {
    status.className = "status-pill muted";
    status.textContent = t("notConnected");
    return;
  }

  status.className = "status-pill ok";
  status.textContent = accountList.map(providerAccountLabel).join(", ");
}

function missingLinkedRepoPermissions(workspace) {
  const access = workspace?.access || workspace;
  if (Array.isArray(access?.missing_required_linked_repo_permissions)) {
    return access.missing_required_linked_repo_permissions;
  }
  if (Array.isArray(access?.linked_repos)) {
    return access.linked_repos.filter((permission) => permission && permission.can_read === false);
  }
  return [];
}

function renderWorkspaceStatus(workspace) {
  const status = document.querySelector("#workspaceStatus");
  const linkedRepoStatus = document.querySelector("#linkedRepoStatus");
  if (!status) return;

  if (!workspace?.configured || !workspace.workspace) {
    status.className = "status-pill muted";
    status.textContent = t("notConfigured");
    if (linkedRepoStatus) {
      linkedRepoStatus.textContent = "";
      linkedRepoStatus.classList.remove("is-warning");
    }
    return;
  }

  const access = workspace.access || null;
  if (access && !access.can_enter_workspace) {
    status.className = "status-pill warning";
    status.textContent = t("workspaceAccessDenied");
    if (linkedRepoStatus) {
      linkedRepoStatus.textContent = access.workspace?.repo_key || workspace.workspace.repo || "";
      linkedRepoStatus.classList.add("is-warning");
    }
    return;
  }

  if (access && !access.can_review) {
    status.className = "status-pill muted";
    status.textContent = t("workspaceReadOnly");
  } else {
    status.className = "status-pill ok";
    status.textContent = workspace.workspace.repo || t("workspaceReady");
  }

  if (!linkedRepoStatus) return;
  const missingPermissions = missingLinkedRepoPermissions(workspace);
  if (access?.missing_required_linked_repo_access || workspace.missing_required_linked_repo_access || missingPermissions.length) {
    const repos = missingPermissions.map((permission) => permission.repo_key).filter(Boolean).join(", ");
    linkedRepoStatus.textContent = repos ? `${t("missingLinkedRepoAccess")}: ${repos}` : t("missingLinkedRepoAccess");
    linkedRepoStatus.classList.add("is-warning");
    return;
  }
  linkedRepoStatus.textContent = "";
  linkedRepoStatus.classList.remove("is-warning");
}

function workspaceStatusPath() {
  if (!currentProjectId) return "/api/workspace/status";
  return `/api/workspace/status?project_slug=${encodeURIComponent(currentProjectId)}`;
}

async function loadCollaborationStatus() {
  const fallbackWorkspace = { configured: false, workspace: null };
  try {
    const [accountsResult, workspaceResult] = await Promise.allSettled([
      api("/api/auth/accounts"),
      api(workspaceStatusPath()),
    ]);
    const accountsPayload = accountsResult.status === "fulfilled" ? accountsResult.value : { connected_accounts: [] };
    collaborationState.accounts = Array.isArray(accountsPayload.connected_accounts) ? accountsPayload.connected_accounts : [];
    collaborationState.workspace = workspaceResult.status === "fulfilled" ? workspaceResult.value : fallbackWorkspace;
  } catch {
    collaborationState.accounts = [];
    collaborationState.workspace = fallbackWorkspace;
  } finally {
    collaborationState.loaded = true;
    renderAccountStatus(collaborationState.accounts);
    renderWorkspaceStatus(collaborationState.workspace);
    renderAuthConnectionPanel();
  }
}

function setCurrentProjectId(projectId) {
  currentProjectId = projectId;
  storageSet("whywiki.currentProjectId", projectId);
  if (collaborationState.loaded) {
    loadCollaborationStatus();
  }
}

function setCurrentProject(project) {
  currentProject = project || null;
  setCurrentProjectId(currentProject ? currentProject.id : null);
}

function projectDisplayName() {
  return currentProject ? currentProject.name : "";
}

function updateWorkspaceChrome(showWorkspace = Boolean(currentProjectId)) {
  document.body.classList.toggle("has-current-project", Boolean(showWorkspace && currentProjectId));
  const projectNameNode = document.querySelector("#current-project-name");
  if (projectNameNode) {
    projectNameNode.textContent = showWorkspace ? projectDisplayName() : "";
    projectNameNode.title = showWorkspace ? projectDisplayName() : "";
  }
}

function returnToProjectsHome() {
  setCurrentProject(null);
  updateWorkspaceChrome(false);
  loadView("projects");
}

function renderHomeNavigationLabels() {
  const homeBrandButton = document.querySelector("#homeBrandButton");
  if (homeBrandButton) {
    homeBrandButton.setAttribute("aria-label", t("nav.home"));
    homeBrandButton.title = t("nav.home");
  }
  const backToProjectsButton = document.querySelector("#backToProjectsButton");
  if (backToProjectsButton) {
    backToProjectsButton.setAttribute("aria-label", t("nav.backToProjects"));
    backToProjectsButton.title = t("nav.backToProjects");
  }
}

async function ensureCurrentProject() {
  const projectId = requireProject();
  if (!projectId) return null;
  if (currentProject && currentProject.id === projectId) return currentProject;
  const project = await api(`/api/projects/${projectId}`);
  setCurrentProject(project);
  return project;
}

function selectProject(project) {
  setCurrentProject(project);
  updateWorkspaceChrome(true);
  loadView("home");
}

async function deleteProject(project) {
  const projectId = project?.id;
  if (!projectId) return;
  const projectName = project.name || projectId;
  if (!window.confirm(t("projects.deleteConfirm").replace("{name}", projectName))) return;
  try {
    await api(`/api/projects/${project.id}`, { method: "DELETE" });
    if (currentProjectId === projectId) {
      setCurrentProject(null);
      updateWorkspaceChrome(false);
    }
    await loadView("projects");
    await loadCollaborationStatus();
  } catch (error) {
    const appNode = appContainer();
    if (appNode) {
      appNode.prepend(renderOperationFeedback("error", t("projects.deleteFailed"), `${error.message} ${t("operation.error.recovery")}`));
    }
  }
}

function closeProjectCardMenus() {
  document.querySelectorAll(".project-card-menu-wrap.is-open").forEach((wrap) => {
    wrap.classList.remove("is-open");
    const button = wrap.querySelector(".project-card-menu-button");
    const menu = wrap.querySelector(".project-card-menu");
    if (button) button.setAttribute("aria-expanded", "false");
    if (menu) menu.hidden = true;
  });
}

function toggleProjectCardMenu(wrap) {
  const willOpen = !wrap.classList.contains("is-open");
  closeProjectCardMenus();
  if (!willOpen) return;
  wrap.classList.add("is-open");
  const button = wrap.querySelector(".project-card-menu-button");
  const menu = wrap.querySelector(".project-card-menu");
  if (button) button.setAttribute("aria-expanded", "true");
  if (menu) menu.hidden = false;
}

function createVerticalEllipsisIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.classList.add("project-card-menu-icon");
  [4, 8, 12].forEach((cy) => {
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", "8");
    circle.setAttribute("cy", String(cy));
    circle.setAttribute("r", "1.35");
    svg.append(circle);
  });
  return svg;
}

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

function createProjectIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("project-home-create-icon");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const horizontal = document.createElementNS("http://www.w3.org/2000/svg", "path");
  horizontal.setAttribute("d", "M4 8h8");
  horizontal.setAttribute("fill", "none");
  horizontal.setAttribute("stroke", "currentColor");
  horizontal.setAttribute("stroke-width", "1.8");
  horizontal.setAttribute("stroke-linecap", "round");
  const vertical = document.createElementNS("http://www.w3.org/2000/svg", "path");
  vertical.setAttribute("d", "M8 4v8");
  vertical.setAttribute("fill", "none");
  vertical.setAttribute("stroke", "currentColor");
  vertical.setAttribute("stroke-width", "1.8");
  vertical.setAttribute("stroke-linecap", "round");
  svg.append(horizontal, vertical);
  return svg;
}

function appendField(list, label, value) {
  const row = document.createElement("div");
  const labelNode = document.createElement("strong");
  const valueNode = document.createElement("span");
  labelNode.textContent = `${label}: `;
  valueNode.textContent = String(value);
  row.append(labelNode, valueNode);
  list.append(row);
}

function appContainer() {
  return document.querySelector("#app");
}

function rerenderActiveViewAfterLanguageChange() {
  if (!appContainer()) return;
  loadView(activeView).catch((error) => {
    const appNode = appContainer();
    if (appNode) appNode.textContent = `${t("view.error")}: ${error.message}`;
  });
}

function normalizeView(view) {
  if (view === "status") return "home";
  if (view === "facts") return "requirements";
  return view || "projects";
}

function setActiveView(view) {
  const normalizedView = normalizeView(view);
  activeView = normalizedView;
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === normalizedView);
  });
}

function fieldValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function appendPre(parent, value) {
  const pre = document.createElement("pre");
  pre.textContent = fieldValue(value);
  parent.append(pre);
}

function parseJsonList(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [parsed];
  } catch {
    return [value];
  }
}

function createPanel(titleText) {
  const panel = document.createElement("div");
  panel.className = "panel output-panel";
  const title = document.createElement("h2");
  title.textContent = titleText;
  panel.append(title);
  return panel;
}

function createFormPanel(titleText) {
  const panel = createPanel(titleText);
  panel.classList.add("form-panel");
  return panel;
}

function appendLabeledControl(form, labelText, control) {
  const label = document.createElement("label");
  const text = document.createElement("span");
  text.textContent = labelText;
  label.append(text, control);
  form.append(label);
  return control;
}

function requireProject() {
  if (currentProjectId) return currentProjectId;
  return null;
}

function appendChip(parent, label, kind = "") {
  const chip = document.createElement("span");
  chip.className = `status-chip ${kind}`.trim();
  chip.textContent = label;
  parent.append(chip);
  return chip;
}

function createElement(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function createActionButton(label, kind = "secondary", onClick = null) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `action-${kind}`;
  button.textContent = label;
  if (onClick) button.addEventListener("click", onClick);
  return button;
}

function createExternalLink(href, label, kind = "secondary") {
  const link = document.createElement("a");
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.className = `action-${kind}`;
  link.textContent = label;
  return link;
}

function visibleConflictRows(conflicts) {
  return conflicts.filter((conflict) => conflict.status !== "resolved" && conflict.status !== "ignored");
}

function reviewFactRows(facts) {
  return facts.filter((fact) => fact.status === "needs_review" || fact.status === "candidate" || fact.validity_status === "conflicting");
}

function requirementRows(facts = []) {
  return facts.filter((fact) => fact.fact_type === "requirement");
}

function supportingFactRows(facts = []) {
  return facts.filter((fact) => fact.fact_type !== "requirement");
}

function requirementStatusKind(row) {
  if (row.validity_status === "conflicting") return "conflict";
  if (!evidenceItems(row).length) return "low-confidence";
  if (row.status === "needs_review" || row.status === "candidate") return "needs-review";
  if (row.status === "confirmed" || row.validity_status === "current") return "confirmed";
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
    const sourceMatch = filters.has("source-backed") && kind === "source-backed";
    const recentMatch = filters.has("recent") && Boolean(row.updated_at || row.recent || row.recently_touched);
    return statusMatch || sourceMatch || recentMatch;
  });
}

function evidenceItems(row) {
  if (!row || !("evidence_json" in row)) return [];
  return parseJsonList(row.evidence_json).filter((item) => item && typeof item === "object");
}

function sourceKindFromPath(source) {
  const type = String(source.source_type || "").toLowerCase();
  const path = String(source.path || "").toLowerCase();
  if (type === "git" || path.includes(".git")) return "git";
  if (/\.(py|js|ts|tsx|jsx|go|rs|java|rb|php|cs|cpp|c|h)$/.test(path)) return "code";
  return "document";
}

function sourceKindLabel(source) {
  const kind = typeof source === "string" ? source : sourceKindFromPath(source || {});
  if (kind === "git") return t("badge.git");
  if (kind === "code") return t("badge.code");
  return t("badge.document");
}

function evidenceConfidenceLabel(row) {
  const evidence = evidenceItems(row);
  const uniquePaths = new Set(evidence.map((item) => item.path).filter(Boolean));
  if (row && (row.status === "candidate" || row.confidence < 0.7)) return t("evidence.confidence.aiInferred");
  if (uniquePaths.size > 1) return t("evidence.confidence.multiSource");
  if (uniquePaths.size === 1) return t("evidence.confidence.singleSource");
  return t("badge.lowConfidence");
}

function deriveProjectState({ sources = [], facts = [], conflicts = [], pages = [] } = {}) {
  const wikiPages = visibleWikiPages(pages);
  const openConflicts = visibleConflictRows(conflicts);
  const reviewFacts = reviewFactRows(facts);
  const metrics = {
    sources: sources.length,
    facts: facts.length,
    conflicts: openConflicts.length,
    wiki: wikiPages.length,
    reviewFacts: reviewFacts.length,
  };
  let stage = "connectSource";
  let nextAction = "connectSource";
  if (metrics.sources > 0 && (!metrics.facts || !metrics.wiki)) {
    stage = "generateWiki";
    nextAction = "generateEvidenceWiki";
  } else if (metrics.conflicts || metrics.reviewFacts) {
    stage = "reviewEvidence";
    nextAction = "reviewConflicts";
  } else if (metrics.wiki) {
    stage = "askHandover";
    nextAction = "askWithEvidence";
  }
  return { stage, nextAction, metrics };
}

function renderStatusBadge(label, kind = "neutral") {
  const badge = createElement("span", `status-badge status-badge-${kind}`);
  badge.textContent = label;
  return badge;
}

function renderSourceBadge(source) {
  const kind = typeof source === "string" ? source : sourceKindFromPath(source || {});
  const badge = createElement("span", `source-badge source-badge-${kind}`);
  badge.textContent = sourceKindLabel(kind);
  return badge;
}

function renderEvidenceBadge(row) {
  const evidence = evidenceItems(row);
  const kind = evidence.length ? "evidence" : "low-confidence";
  const label = evidence.length ? t("badge.evidenceBacked") : t("badge.lowConfidence");
  const badge = createElement("span", `evidence-badge evidence-badge-${kind}`);
  badge.textContent = label;
  badge.title = evidence.length ? evidenceConfidenceLabel(row) : t("empty.evidence.body");
  return badge;
}

function renderEmptyState({ title, body, actionLabel = "", onAction = null, kind = "default" }) {
  const empty = createElement("div", `empty-state empty-state-${kind}`);
  const icon = createElement("div", "empty-state-icon", "!");
  const heading = createElement("h3", "", title);
  const copy = createElement("p", "", body);
  empty.append(icon, heading, copy);
  if (actionLabel && onAction) {
    empty.append(createActionButton(actionLabel, "primary", onAction));
  }
  return empty;
}

function renderOperationFeedback(kind, title, body = "") {
  const feedback = createElement("div", `operation-feedback operation-feedback-${kind}`);
  feedback.setAttribute("role", kind === "error" ? "alert" : "status");
  const label = createElement("strong", "", title);
  feedback.append(label);
  if (body) feedback.append(createElement("p", "", body));
  return feedback;
}

function renderEvidenceDetailItem(item) {
  const card = createElement("article", "evidence-item");
  const path = createElement("strong", "", item.path || item.source_path || item.id || "unknown");
  card.append(path);
  const meta = createElement("div", "card-meta");
  if (item.source_type) meta.append(renderSourceBadge(item.source_type));
  if (item.location && Object.keys(item.location).length) {
    meta.append(createElement("span", "muted", fieldValue(item.location)));
  }
  if (item.kind || item.score !== undefined) {
    meta.append(createElement("span", "muted", [item.kind, item.score !== undefined ? `${t("field.confidence")}: ${item.score}` : ""].filter(Boolean).join(" · ")));
  }
  if (meta.childNodes.length) card.append(meta);
  if (item.block_text) {
    card.append(createElement("span", "evidence-block-label", t("evidence.blockText")));
    const block = document.createElement("pre");
    block.className = "evidence-block-text";
    block.textContent = item.block_text;
    card.append(block);
  }
  return card;
}

async function loadEvidenceDetails(detailsPath, list) {
  list.replaceChildren(renderOperationFeedback("loading", t("evidence.drawer.loading")));
  const items = await api(detailsPath);
  if (!items.length) {
    list.replaceChildren(renderEmptyState({
      title: t("empty.evidence.title"),
      body: t("empty.evidence.body"),
      kind: "evidence",
    }));
    return;
  }
  list.replaceChildren(...items.map(renderEvidenceDetailItem));
}

function renderEvidenceDrawer(evidence, titleText = t("evidence.drawer.title"), detailsPath = "") {
  const wrapper = createElement("details", "evidence-drawer");
  const summary = createElement("summary", "", titleText);
  wrapper.append(summary);
  const items = Array.isArray(evidence) ? evidence : parseJsonList(evidence);
  if (!items.length) {
    wrapper.append(renderEmptyState({
      title: t("empty.evidence.title"),
      body: t("empty.evidence.body"),
      kind: "evidence",
    }));
    return wrapper;
  }
  const list = createElement("div", "evidence-list");
  items.forEach((item) => list.append(renderEvidenceDetailItem(item)));
  if (detailsPath) {
    const load = createActionButton(t("evidence.drawer.openOriginal"), "tertiary", () => {
      loadEvidenceDetails(detailsPath, list).catch((error) => {
        list.replaceChildren(renderOperationFeedback("error", t("view.error"), error.message));
      });
    });
    wrapper.append(load);
    wrapper.addEventListener("toggle", () => {
      if (wrapper.open && !wrapper.dataset.loadedDetails) {
        wrapper.dataset.loadedDetails = "true";
        load.click();
      }
    });
  }
  wrapper.append(list);
  return wrapper;
}

function renderJobProgress(job) {
  const wrapper = createElement("div", "job-progress");
  const label = createElement("strong", "", job.message || t(`operation.job.${job.status}`));
  const track = createElement("div", "progress-track");
  const value = createElement("div", "progress-value");
  value.style.width = `${Math.max(0, Math.min(100, Number(job.progress || 0)))}%`;
  track.append(value);
  wrapper.append(label, track, createElement("span", "muted", `${job.progress || 0}% · ${t(`operation.job.${job.status}`)}`));
  return wrapper;
}

async function startProjectJob(operation, payload = {}) {
  const projectId = requireProject();
  const endpoint = operation === "build" ? `/api/projects/${projectId}/build-jobs` : `/api/projects/${projectId}/ingest-jobs`;
  return api(endpoint, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

async function pollProjectJob(jobId, onUpdate) {
  let job = await api(`/api/jobs/${jobId}`);
  onUpdate(job);
  while (!["succeeded", "failed"].includes(job.status)) {
    await new Promise((resolve) => setTimeout(resolve, 350));
    job = await api(`/api/jobs/${jobId}`);
    onUpdate(job);
  }
  return job;
}

function nextActionConfig(action) {
  const configs = {
    connectSource: {
      label: t("action.connectSource"),
      body: t("empty.sources.body"),
      handler: showIngestForm,
      kind: "primary",
    },
    scanProject: {
      label: t("action.scanProject"),
      body: t("empty.sources.body"),
      handler: showIngestForm,
      kind: "primary",
    },
    generateEvidenceWiki: {
      label: t("action.generateEvidenceWiki"),
      body: t("empty.wiki.body"),
      handler: buildCurrentProject,
      kind: "primary",
    },
    reviewConflicts: {
      label: t("action.reviewConflicts"),
      body: t("review.subtitle"),
      handler: () => loadView("review"),
      kind: "primary",
    },
    askWithEvidence: {
      label: t("action.askWithEvidence"),
      body: t("ask.noEvidence.body"),
      handler: () => loadView("ask"),
      kind: "ai",
    },
    generateHandover: {
      label: t("action.generateHandover"),
      body: t("empty.wiki.body"),
      handler: () => loadView("settings"),
      kind: "secondary",
    },
  };
  return configs[action] || configs.connectSource;
}

function renderProjectStatusHero(project, state) {
  const hero = createElement("section", "project-status-hero");
  const copy = createElement("div", "project-status-copy");
  copy.append(
    renderStatusBadge(t(`workflow.${state.stage}`), state.stage),
    createElement("h1", "", project ? project.name : t("projects.title")),
    createElement("p", "", t("dashboard.statusHero.subtitle"))
  );
  const stats = createElement("div", "project-status-stats");
  stats.append(
    createMetric(t("status.metric.sources"), state.metrics.sources),
    createMetric(t("status.metric.facts"), state.metrics.facts),
    createMetric(t("status.metric.conflicts"), state.metrics.conflicts),
    createMetric(t("status.metric.wiki"), state.metrics.wiki)
  );
  hero.append(copy, stats);
  return hero;
}

function renderOnboardingSteps(state) {
  const steps = [
    ["createProject", t("workflow.createProject")],
    ["connectSource", t("workflow.connectSource")],
    ["scanProject", t("workflow.scanProject")],
    ["generateWiki", t("workflow.generateWiki")],
    ["reviewEvidence", t("workflow.reviewEvidence")],
    ["askHandover", t("workflow.askHandover")],
  ];
  const order = steps.map(([key]) => key);
  const currentIndex = order.indexOf(state.stage);
  const panel = createElement("section", "onboarding-steps");
  panel.append(createElement("h2", "", t("dashboard.onboarding.title")));
  const list = createElement("ol", "");
  steps.forEach(([key, label], index) => {
    const item = createElement("li", "");
    item.className = index < currentIndex || (state.stage === "askHandover" && key !== "askHandover") ? "is-complete" : "";
    if (key === state.stage) item.className = `${item.className} is-current`.trim();
    item.append(createElement("span", "step-index", String(index + 1)), createElement("span", "", label));
    list.append(item);
  });
  panel.append(list);
  return panel;
}

function renderNextActionPanel(state) {
  const config = nextActionConfig(state.nextAction);
  const panel = createElement("section", "next-action-panel");
  const copy = createElement("div", "");
  copy.append(createElement("h2", "", t("dashboard.nextAction.title")), createElement("p", "", config.body));
  panel.append(copy, createActionButton(config.label, config.kind, config.handler));
  return panel;
}

function createMetric(label, value) {
  const card = document.createElement("div");
  card.className = "metric-card";
  const number = document.createElement("strong");
  number.textContent = String(value);
  const text = document.createElement("span");
  text.textContent = label;
  card.append(number, text);
  return card;
}

function createWorkspaceActions() {
  const actions = document.createElement("div");
  actions.className = "actions project-actions";
  const ingest = document.createElement("button");
  ingest.type = "button";
  ingest.dataset.action = "ingest";
  ingest.className = "action-secondary";
  ingest.textContent = t("action.connectSource");
  ingest.addEventListener("click", showIngestForm);
  const build = document.createElement("button");
  build.type = "button";
  build.dataset.action = "buildWiki";
  build.className = "action-primary action-ai";
  build.textContent = t("action.generateEvidenceWiki");
  build.addEventListener("click", buildCurrentProject);
  actions.append(ingest, build);
  return actions;
}

function createProjectCard(project) {
  const card = document.createElement("article");
  card.className = "project-card";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-label", t("projects.openCard").replace("{name}", project.name));
  card.addEventListener("click", () => selectProject(project));
  card.addEventListener("keydown", (event) => {
    if (event.target !== card) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectProject(project);
    }
  });
  const header = createElement("div", "project-card-header");
  const title = document.createElement("h2");
  title.textContent = project.name;
  const menuWrap = createElement("div", "project-card-menu-wrap");
  menuWrap.addEventListener("click", (event) => event.stopPropagation());
  const menuButton = createActionButton("", "tertiary", (event) => {
    event.stopPropagation();
    toggleProjectCardMenu(menuWrap);
  });
  menuButton.classList.add("project-card-menu-button");
  menuButton.setAttribute("aria-label", t("projects.moreActions"));
  menuButton.setAttribute("aria-haspopup", "menu");
  menuButton.setAttribute("aria-expanded", "false");
  menuButton.append(createVerticalEllipsisIcon());
  const menu = createElement("div", "project-card-menu");
  menu.hidden = true;
  menu.setAttribute("role", "menu");
  const remove = createActionButton(t("projects.delete"), "destructive", (event) => {
    event.stopPropagation();
    closeProjectCardMenus();
    deleteProject(project);
  });
  remove.classList.add("project-card-delete", "action-destructive");
  remove.setAttribute("role", "menuitem");
  menu.append(remove);
  menuWrap.append(menuButton, menu);
  header.append(title, menuWrap);
  const description = document.createElement("p");
  description.textContent = project.description || t("projects.noDescription");
  const meta = document.createElement("span");
  meta.className = "muted";
  meta.textContent = project.created_at || "";
  card.append(header, description, meta);
  return card;
}

async function renderProjectsHome() {
  updateWorkspaceChrome(false);
  setActiveView("projects");
  const projects = await api("/api/projects");
  const panel = createPanel(t("projects.title"));
  panel.classList.add("projects-home");
  const title = panel.querySelector("h2");
  const header = document.createElement("div");
  header.className = "project-home-header";
  if (title) title.classList.add("project-home-title");
  const createButton = document.createElement("button");
  createButton.type = "button";
  createButton.className = "action-secondary project-home-create-button";
  createButton.textContent = t("action.createProject");
  createButton.prepend(createProjectIcon());
  createButton.addEventListener("click", showCreateProjectForm);
  header.append(title, createButton);
  panel.prepend(header);

  if (!projects.length) {
    panel.append(renderEmptyState({
      title: t("projects.empty"),
      body: t("dashboard.statusHero.subtitle"),
      actionLabel: t("action.createProject"),
      onAction: showCreateProjectForm,
      kind: "project",
    }));
    panel.append(renderOnboardingSteps({ stage: "createProject" }));
    return panel;
  }

  const list = document.createElement("div");
  list.className = "project-list";
  projects.forEach((project) => list.append(createProjectCard(project)));
  panel.append(list);
  return panel;
}

function showCreateProjectForm() {
  const appNode = appContainer();
  if (!appNode) return;
  setActiveView("projects");
  updateWorkspaceChrome(false);

  const panel = createFormPanel(t("project.create.title"));
  const form = document.createElement("form");
  form.className = "inline-form";
  const nameInput = document.createElement("input");
  nameInput.name = "name";
  nameInput.required = true;
  nameInput.placeholder = t("project.create.namePlaceholder");
  const descriptionInput = document.createElement("textarea");
  descriptionInput.name = "description";
  descriptionInput.placeholder = t("project.create.descriptionPlaceholder");
  const status = document.createElement("p");
  status.className = "status-line";
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "action-primary";
  submit.textContent = t("project.create.submit");

  appendLabeledControl(form, t("project.create.name"), nameInput);
  appendLabeledControl(form, t("project.create.description"), descriptionInput);
  form.append(submit, status);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    status.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
    try {
      const project = await api("/api/projects", {
        method: "POST",
        body: JSON.stringify({
          name: nameInput.value.trim(),
          description: descriptionInput.value.trim(),
        }),
      });
      setCurrentProject(project);
      await loadView("home");
    } catch (error) {
      status.replaceChildren(renderOperationFeedback("error", t("view.error"), `${error.message} ${t("operation.error.recovery")}`));
      submit.disabled = false;
    }
  });

  panel.append(form);
  appNode.replaceChildren(panel);
  nameInput.focus();
}

function renderNoProjectAction() {
  updateWorkspaceChrome(false);
  setActiveView("projects");
  const panel = createPanel(t("projects.title"));
  const message = document.createElement("p");
  message.textContent = t("view.noProject");
  const actions = document.createElement("div");
  actions.className = "actions";
  const projectsButton = document.createElement("button");
  projectsButton.type = "button";
  projectsButton.className = "action-secondary";
  projectsButton.textContent = t("nav.projects");
  projectsButton.addEventListener("click", () => loadView("projects"));
  const createButton = document.createElement("button");
  createButton.type = "button";
  createButton.className = "action-primary";
  createButton.textContent = t("action.createProject");
  createButton.addEventListener("click", showCreateProjectForm);
  actions.append(projectsButton, createButton);
  panel.append(message, actions);
  return panel;
}

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
  const status = document.createElement("p");
  status.className = "status-line";
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "action-primary";
  submit.textContent = t("action.scanProject");

  appendLabeledControl(form, t("ingest.path"), pathInput);
  appendLabeledControl(form, t("ingest.sourceType"), sourceType);
  form.append(submit, status);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    status.replaceChildren(renderOperationFeedback("loading", t("operation.ingest.loading"), pathInput.value.trim()));
    try {
      const started = await startProjectJob("ingest", {
        path: pathInput.value.trim(),
        source_type: sourceType.value,
      });
      status.replaceChildren(renderJobProgress(started));
      const completed = await pollProjectJob(started.id, (job) => {
        status.replaceChildren(renderJobProgress(job));
      });
      if (completed.status === "failed") {
        throw new Error(completed.error || completed.message);
      }
      const result = completed.result;
      const resultPanel = createPanel(t("ingest.ready"));
      resultPanel.append(renderOperationFeedback("success", t("operation.ingest.success"), t("empty.wiki.body")));
      appendField(resultPanel, t("field.filesSeen"), result.files_seen);
      appendField(resultPanel, t("field.sourcesCreated"), result.created_sources);
      appendField(resultPanel, t("field.blocksCreated"), result.created_blocks);
      appendField(resultPanel, t("field.skippedFiles"), result.skipped_files);
      if (result.errors && result.errors.length) {
        resultPanel.append(renderOperationFeedback("error", t("view.error"), t("operation.error.recovery")));
        appendField(resultPanel, t("view.error"), result.errors.length);
        appendPre(resultPanel, result.errors);
      }
      const actions = createElement("div", "actions");
      actions.append(
        createActionButton(t("action.generateEvidenceWiki"), "primary", buildCurrentProject),
        createActionButton(t("nav.sources"), "secondary", () => loadView("sources"))
      );
      resultPanel.append(actions);
      appNode.replaceChildren(resultPanel);
    } catch (error) {
      status.replaceChildren(renderOperationFeedback("error", t("view.error"), `${error.message} ${t("operation.error.recovery")}`));
      submit.disabled = false;
    }
  });

  panel.append(form);
  appNode.replaceChildren(panel);
  pathInput.focus();
}

async function buildCurrentProject() {
  const appNode = appContainer();
  if (!appNode) return;
  setActiveView("");
  updateWorkspaceChrome(true);
  const projectId = requireProject();
  if (!projectId) {
    appNode.replaceChildren(renderNoProjectAction());
    return;
  }

  const progressPanel = createPanel(t("operation.build.loading"));
  progressPanel.append(renderOperationFeedback("loading", t("operation.build.loading"), t("dashboard.statusHero.subtitle")));
  appNode.replaceChildren(progressPanel);
  try {
    const started = await startProjectJob("build");
    progressPanel.replaceChildren(renderJobProgress(started));
    const completed = await pollProjectJob(started.id, (job) => {
      progressPanel.replaceChildren(renderJobProgress(job));
    });
    if (completed.status === "failed") {
      throw new Error(completed.error || completed.message);
    }
    const result = completed.result;
    const panel = createPanel(t("build.ready"));
    panel.append(renderOperationFeedback("success", t("operation.build.success"), t("dashboard.nextAction.title")));
    appendField(panel, t("build.requirementsCreated"), result.facts_created);
    appendField(panel, t("build.conflictsCreated"), result.conflicts_created);
    appendField(panel, t("build.pagesCreated"), result.wiki_pages.length);
    const actions = createElement("div", "actions");
    actions.append(
      createActionButton(t("nav.wikiIndex"), "primary", () => loadView("wiki")),
      createActionButton(t("action.reviewConflicts"), result.conflicts_created ? "secondary" : "tertiary", () => loadView("review")),
      createActionButton(t("action.askWithEvidence"), "ai", () => loadView("ask"))
    );
    panel.append(actions);
    appNode.replaceChildren(panel);
  } catch (error) {
    const panel = createPanel(t("view.error"));
    panel.append(
      renderOperationFeedback("error", t("view.error"), `${error.message} ${t("operation.error.recovery")}`),
      createActionButton(t("action.retry"), "primary", buildCurrentProject)
    );
    appNode.replaceChildren(panel);
  }
}

async function renderSources(projectId) {
  const sources = await api(`/api/projects/${projectId}/sources`);
  const panel = createPanel(t("view.sources.title"));
  panel.append(createElement("p", "status-intro", t("empty.sources.body")));
  if (!sources.length) {
    panel.append(renderEmptyState({
      title: t("empty.sources.title"),
      body: t("empty.sources.body"),
      actionLabel: t("action.connectSource"),
      onAction: showIngestForm,
      kind: "sources",
    }));
    return panel;
  }
  const grid = createElement("div", "record-grid source-grid");
  sources.forEach((source) => {
    const card = createElement("article", "record-card source-card");
    const header = createElement("header", "card-header");
    header.append(createElement("strong", "", source.title || source.path), renderSourceBadge(source));
    card.append(header, createElement("p", "source-path", source.path));
    const meta = createElement("div", "card-meta");
    meta.append(createElement("span", "", `${t("field.updatedAt")}: ${fieldValue(source.updated_at)}`));
    if (source.version_hint) meta.append(createElement("span", "", source.version_hint));
    card.append(meta);
    grid.append(card);
  });
  panel.append(grid);
  return panel;
}

async function renderFacts(projectId) {
  const facts = await api(`/api/projects/${projectId}/facts`);
  const panel = createPanel(t("view.requirements.title"));
  panel.append(createElement("p", "status-intro", t("empty.facts.body")));
  if (!facts.length) {
    panel.append(renderEmptyState({
      title: t("empty.facts.title"),
      body: t("empty.facts.body"),
      actionLabel: t("action.generateEvidenceWiki"),
      onAction: buildCurrentProject,
      kind: "facts",
    }));
    return panel;
  }
  const grid = createElement("div", "fact-grid");
  facts.forEach((fact) => grid.append(renderFactCard(fact)));
  panel.append(grid);
  return panel;
}

function renderRequirementSourceSummary(requirement) {
  const count = requirementSourceCount(requirement);
  const label = t("requirement.sourceCount").replace("{count}", String(count));
  const summary = createElement("span", "requirement-source-summary", label);
  return summary;
}

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
  activeConflictRequirementId = null;
  loadView("requirements");
}

function renderRequirementFilterChip(filter, label, kind = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `requirement-filter-chip requirement-filter-${kind || filter}`;
  button.setAttribute("data-filter", filter);
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

function renderConflictJumpControl(requirements) {
  const conflicts = visibleRequirementRows(requirements, requirementFilterState)
    .filter((row) => requirementStatusKind(row) === "conflict");
  const control = createElement("div", "requirement-conflict-jump");
  const activeIndex = conflicts.findIndex((row) => row.id === activeConflictRequirementId);
  const current = activeIndex >= 0 ? activeIndex + 1 : 0;
  const count = createElement("span", "", t("requirements.conflictJump").replace("{current}", String(current)).replace("{total}", String(conflicts.length)));

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

  control.append(count, previous, next);
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
  const count = document.querySelector(".requirement-conflict-jump span");
  if (count) {
    count.textContent = t("requirements.conflictJump").replace("{current}", String(nextIndex + 1)).replace("{total}", String(cards.length));
  }
  requirementJumpTimer = window.setTimeout(() => {
    target.classList.remove("is-jump-target");
    requirementJumpTimer = null;
  }, 1600);
}

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

function factStatusKind(fact) {
  if (fact.validity_status === "conflicting" || fact.status === "needs_review") return "review";
  if (fact.validity_status === "current" || fact.status === "confirmed") return "evidence";
  return "";
}

function factStatusLabel(fact) {
  if (fact.validity_status === "conflicting" || fact.status === "needs_review") return t("status.needsReview");
  if (fact.validity_status === "current" || fact.status === "confirmed") return t("status.evidence");
  return t("status.stable");
}

async function updateFactStatus(factId, status) {
  const projectId = requireProject();
  if (!projectId) return null;
  return api(`/api/projects/${projectId}/facts/${factId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

function renderFactCard(fact) {
  const card = createElement("article", "fact-card");
  const projectId = requireProject();
  const factId = fact.id;
  const header = createElement("header", "card-header");
  const title = createElement("strong", "", fact.fact_type || t("view.requirements.title"));
  const badges = createElement("div", "badge-row");
  badges.append(renderStatusBadge(factStatusLabel(fact), factStatusKind(fact) || "candidate"));
  badges.append(renderEvidenceBadge(fact));
  if (fact.status === "candidate") badges.append(renderStatusBadge(t("badge.aiInference"), "ai"));
  if (fact.status === "confirmed") badges.append(renderStatusBadge(t("badge.confirmed"), "confirmed"));
  if (fact.validity_status === "conflicting") badges.append(renderStatusBadge(t("badge.conflict"), "conflict"));
  header.append(title, badges);

  const statement = createElement("p", "fact-statement", fact.statement || "-");
  const meta = createElement("div", "card-meta");
  meta.append(
    createElement("span", "", `${t("field.confidence")}: ${fieldValue(fact.confidence)}`),
    createElement("span", "", evidenceConfidenceLabel(fact))
  );
  const actions = createElement("div", "actions");
  actions.append(
    createActionButton(t("action.viewEvidence"), "tertiary", () => {
      const drawer = card.querySelector(".evidence-drawer");
      if (drawer) drawer.open = true;
    }),
    createActionButton(t("action.confirmRequirement"), "secondary", () => {
      actions.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
      updateFactStatus(factId, "confirmed").then((updated) => {
        actions.replaceChildren(renderOperationFeedback("success", t("badge.confirmed"), updated.statement || ""));
      }).catch((error) => {
        actions.replaceChildren(renderOperationFeedback("error", t("view.error"), error.message));
      });
    })
  );
  card.append(
    header,
    statement,
    meta,
    actions,
    renderEvidenceDrawer(
      evidenceItems(fact),
      t("evidence.drawer.title"),
      projectId && factId ? `/api/projects/${projectId}/facts/${factId}/evidence` : ""
    )
  );
  return card;
}

function renderStateCards(rows, limit = 8) {
  const grid = document.createElement("div");
  grid.className = "state-grid";
  rows.slice(0, limit).forEach((row) => {
    if ("statement" in row) {
      grid.append(renderFactCard(row));
      return;
    }
    const card = document.createElement("article");
    card.className = "state-card";
    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = row.fact_type || row.title || row.path || row.id;
    header.append(title);
    appendChip(header, factStatusLabel(row), factStatusKind(row));
    const statement = document.createElement("p");
    statement.textContent = row.statement || row.description || row.path || "-";
    card.append(header, statement);
    if (row.evidence_json) {
      appendChip(card, t("status.evidence"), "evidence");
    }
    grid.append(card);
  });
  return grid;
}

function renderRecentSources(sources) {
  const sorted = [...sources].sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
  const grid = document.createElement("div");
  grid.className = "state-grid";
  sorted.slice(0, 6).forEach((source) => {
    const card = document.createElement("article");
    card.className = "state-card";
    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = source.title || source.path;
    header.append(title);
    header.append(renderSourceBadge(source), renderStatusBadge(t("status.changed"), "changed"));
    const path = document.createElement("p");
    path.textContent = source.path;
    card.append(header, path);
    grid.append(card);
  });
  return grid;
}

function appendSection(parent, titleText, child) {
  const section = document.createElement("section");
  section.className = "state-section";
  const title = document.createElement("h3");
  title.textContent = titleText;
  section.append(title, child);
  parent.append(section);
  return section;
}

function visibleWikiPages(pages) {
  return pages.filter((page) => page.slug !== "handover");
}

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

function projectHomeBodyKey({ sources = [], facts = [], requirements = [], pages = [] } = {}) {
  if (!sources.length) return "projectHome.emptyBody";
  if (requirements.length) return "projectHome.readyBody";
  const hasGeneratedMaterial = Boolean(facts.length || visibleWikiPages(pages).length);
  return hasGeneratedMaterial ? "projectHome.noRequirementsBody" : "projectHome.generateBody";
}

async function renderProjectHome(projectId) {
  const [sources, facts, conflicts, pages] = await Promise.all([
    api(`/api/projects/${projectId}/sources`),
    api(`/api/projects/${projectId}/facts`),
    api(`/api/projects/${projectId}/conflicts`),
    api(`/api/projects/${projectId}/wiki`),
  ]);
  const requirements = requirementRows(facts);
  const wikiPages = visibleWikiPages(pages);
  const state = deriveProjectState({ sources, facts, conflicts, pages });
  const bodyKey = projectHomeBodyKey({ sources, facts, requirements, pages });
  const panel = createElement("section", "panel output-panel project-home-workspace");
  panel.setAttribute("aria-label", t("projectHome.title"));

  const hero = createElement("section", "project-home-hero");
  const copy = createElement("div", "project-home-copy");
  copy.append(
    renderStatusBadge(t(`workflow.${state.stage}`), state.stage),
    createElement("h1", "", projectDisplayName()),
    createElement("p", "", t(bodyKey))
  );
  const stats = createElement("div", "project-home-stats");
  stats.append(
    createMetric(t("status.metric.sources"), sources.length),
    createMetric(t("status.metric.requirements"), requirements.length),
    createMetric(t("status.metric.conflicts"), visibleConflictRows(conflicts).length),
    createMetric(t("status.metric.wiki"), wikiPages.length)
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

async function renderStatus(projectId) {
  const [sources, facts, conflicts, pages] = await Promise.all([
    api(`/api/projects/${projectId}/sources`),
    api(`/api/projects/${projectId}/facts`),
    api(`/api/projects/${projectId}/conflicts`),
    api(`/api/projects/${projectId}/wiki`),
  ]);
  const state = deriveProjectState({ sources, facts, conflicts, pages });
  const panel = createPanel(t("status.title"));
  panel.prepend(renderProjectStatusHero(currentProject, state));
  panel.append(renderNextActionPanel(state), renderOnboardingSteps(state), createWorkspaceActions());

  if (facts.length) {
    appendSection(panel, t("status.current"), renderStateCards(facts, 8));
  } else {
    appendSection(panel, t("status.current"), renderEmptyState({
      title: t("empty.facts.title"),
      body: t("empty.facts.body"),
      actionLabel: sources.length ? t("action.generateEvidenceWiki") : t("action.connectSource"),
      onAction: sources.length ? buildCurrentProject : showIngestForm,
      kind: "facts",
    }));
  }
  if (sources.length) {
    appendSection(panel, t("status.recent"), renderRecentSources(sources));
  } else {
    appendSection(panel, t("status.recent"), renderEmptyState({
      title: t("empty.sources.title"),
      body: t("empty.sources.body"),
      actionLabel: t("action.connectSource"),
      onAction: showIngestForm,
      kind: "sources",
    }));
  }
  if (conflicts.length) {
    const reviewGrid = document.createElement("div");
    reviewGrid.className = "state-grid";
    conflicts.slice(0, 4).forEach((conflict) => {
      reviewGrid.append(renderConflictCard(conflict));
    });
    appendSection(panel, t("status.review"), reviewGrid);
  } else {
    appendSection(panel, t("status.review"), renderEmptyState({
      title: t("empty.conflicts.title"),
      body: t("empty.conflicts.body"),
      kind: "conflicts",
    }));
  }
  return panel;
}

async function renderConflicts(projectId) {
  const conflicts = await api(`/api/projects/${projectId}/conflicts`);
  const panel = createPanel(t("view.conflicts.title"));
  if (!conflicts.length) {
    panel.append(renderEmptyState({
      title: t("empty.conflicts.title"),
      body: t("empty.conflicts.body"),
      kind: "conflicts",
    }));
    return panel;
  }
  const grid = createElement("div", "conflict-grid");
  conflicts.forEach((conflict) => grid.append(renderConflictCard(conflict)));
  panel.append(grid);
  return panel;
}

async function updateConflictStatus(conflictId, status) {
  const projectId = requireProject();
  if (!projectId) return;
  await api(`/api/projects/${projectId}/conflicts/${conflictId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
  await loadView("review");
}

function renderConflictCard(conflict) {
  const card = createElement("article", `conflict-card conflict-card-${conflict.severity || "medium"}`);
  const projectId = requireProject();
  const conflictId = conflict.id;
  const header = createElement("header", "card-header");
  const title = createElement("strong", "", conflict.title || t("view.conflicts.title"));
  const badges = createElement("div", "badge-row");
  badges.append(
    renderStatusBadge(t("badge.conflict"), "conflict"),
    renderStatusBadge(fieldValue(conflict.severity), conflict.severity || "medium"),
    renderStatusBadge(fieldValue(conflict.status), conflict.status || "open")
  );
  header.append(title, badges);
  const description = createElement("p", "", conflict.description || "-");
  const evidence = evidenceItems(conflict);
  const actions = createElement("div", "actions");
  const resolve = createActionButton(t("action.resolveConflict"), "primary", () => {
    actions.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
    updateConflictStatus(conflict.id, "resolved").catch((error) => {
      actions.replaceChildren(renderOperationFeedback("error", t("view.error"), error.message));
    });
  });
  const ignore = createActionButton(t("action.ignoreConflict"), "tertiary", () => {
    actions.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
    updateConflictStatus(conflict.id, "ignored").catch((error) => {
      actions.replaceChildren(renderOperationFeedback("error", t("view.error"), error.message));
    });
  });
  if (conflict.status === "resolved" || conflict.status === "ignored") {
    resolve.disabled = true;
    ignore.disabled = true;
  }
  actions.append(resolve, ignore);
  card.append(
    header,
    description,
    renderEvidenceDrawer(
      evidence,
      t("evidence.drawer.title"),
      projectId && conflictId ? `/api/projects/${projectId}/conflicts/${conflictId}/evidence` : ""
    ),
    actions
  );
  return card;
}

async function renderReview(projectId) {
  const [conflicts, facts] = await Promise.all([
    api(`/api/projects/${projectId}/conflicts`),
    api(`/api/projects/${projectId}/facts`),
  ]);
  const panel = createPanel(t("review.title"));
  const intro = document.createElement("p");
  intro.className = "status-intro";
  intro.textContent = t("review.subtitle");
  panel.append(intro);

  if (conflicts.length) {
    const grid = createElement("div", "conflict-grid");
    conflicts.forEach((conflict) => grid.append(renderConflictCard(conflict)));
    appendSection(panel, t("view.conflicts.title"), grid);
  } else {
    appendSection(panel, t("view.conflicts.title"), renderEmptyState({
      title: t("empty.conflicts.title"),
      body: t("empty.conflicts.body"),
      kind: "conflicts",
    }));
  }

  const reviewFacts = facts.filter((fact) => fact.status === "needs_review" || fact.validity_status === "conflicting");
  appendSection(
    panel,
    t("view.requirements.title"),
    reviewFacts.length ? renderStateCards(reviewFacts, 8) : renderEmptyState({
      title: t("empty.facts.title"),
      body: t("empty.facts.body"),
      kind: "facts",
    })
  );
  return panel;
}

async function renderWiki(projectId) {
  const pages = visibleWikiPages(await api(`/api/projects/${projectId}/wiki`));
  const panel = createPanel(t("view.wiki.title"));
  if (!pages.length) {
    panel.append(renderEmptyState({
      title: t("empty.wiki.title"),
      body: t("empty.wiki.body"),
      actionLabel: t("action.generateEvidenceWiki"),
      onAction: buildCurrentProject,
      kind: "wiki",
    }));
    return panel;
  }
  panel.append(await renderWikiReader(projectId, pages));
  return panel;
}

async function renderWikiReader(projectId, pages) {
  const reader = createElement("section", "wiki-reader");
  const nav = createElement("div", "wiki-page-list");
  const content = createElement("article", "wiki-page-content");

  async function openPage(page) {
    nav.querySelectorAll("button").forEach((button) => {
      button.classList.toggle("active", button.dataset.slug === page.slug);
    });
    content.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
    try {
      const slug = encodeURIComponent(page.slug);
      const text = await apiText(`/api/projects/${projectId}/wiki/${slug}`);
      const heading = createElement("h3", "", page.title || page.slug);
      const meta = createElement("div", "card-meta");
      meta.append(renderEvidenceBadge({ evidence_json: JSON.stringify([{ path: `${page.slug}.md` }]) }));
      meta.append(createElement("span", "", `${t("field.updatedAt")}: ${fieldValue(page.updated_at)}`));
      const pre = document.createElement("pre");
      pre.textContent = text;
      content.replaceChildren(heading, meta, pre);
    } catch (error) {
      content.replaceChildren(renderOperationFeedback("error", t("view.error"), `${error.message} ${t("operation.error.recovery")}`));
    }
  }

  pages.forEach((page) => {
    const button = createActionButton(page.title || page.slug, "tertiary", () => openPage(page));
    button.dataset.slug = page.slug;
    nav.append(button);
  });
  reader.append(nav, content);
  openPage(pages[0]);
  return reader;
}

async function renderHandover(projectId) {
  const panel = createPanel(t("view.handover.title"));
  try {
    const handover = await apiText(`/api/projects/${projectId}/handover`);
    appendPre(panel, handover);
  } catch (error) {
    panel.append(renderEmptyState({
      title: t("empty.wiki.title"),
      body: `${t("empty.wiki.body")} ${error.message}`,
      actionLabel: t("action.generateHandover"),
      onAction: buildCurrentProject,
      kind: "wiki",
    }));
  }
  return panel;
}

async function renderAsk(projectId) {
  const panel = createPanel(t("view.ask.title"));
  panel.append(createElement("p", "status-intro", t("ask.noEvidence.body")));
  const form = document.createElement("form");
  form.className = "ask-form";
  const input = document.createElement("input");
  input.name = "question";
  input.value = t("ask.defaultQuestion");
  const button = document.createElement("button");
  button.type = "submit";
  button.className = "action-ai";
  button.textContent = t("action.askWithEvidence");
  const output = document.createElement("div");
  output.className = "ask-output";

  async function ask(question) {
    button.disabled = true;
    output.replaceChildren(renderOperationFeedback("loading", t("operation.ask.loading"), question));
    const result = await api(`/api/projects/${projectId}/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    button.disabled = false;
    const answer = createElement("article", "answer-card");
    answer.append(createElement("h3", "", result.question), createElement("p", "", result.answer));
    output.replaceChildren(answer);
    if (result.evidence && result.evidence.length) {
      const evidenceTitle = document.createElement("h3");
      evidenceTitle.textContent = t("field.evidence");
      output.append(evidenceTitle);
      output.append(renderEvidenceDrawer(result.evidence, t("action.viewEvidence")));
    } else {
      output.append(renderEmptyState({
        title: t("ask.noEvidence.title"),
        body: t("ask.noEvidence.body"),
        actionLabel: t("action.connectSource"),
        onAction: showIngestForm,
        kind: "evidence",
      }));
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    ask(input.value || t("ask.defaultQuestion")).catch((error) => {
      button.disabled = false;
      output.replaceChildren(renderOperationFeedback("error", t("view.error"), `${error.message} ${t("operation.error.recovery")}`));
    });
  });

  form.append(input, button);
  panel.append(form, output);
  output.append(renderEmptyState({
    title: t("action.askWithEvidence"),
    body: t("ask.noEvidence.body"),
    kind: "evidence",
  }));
  return panel;
}

async function renderSettings() {
  const panel = createPanel(t("view.settings.title"));
  const projectId = requireProject();
  panel.append(createElement("p", "status-intro", t("settings.subtitle")));
  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.className = "action-secondary";
  exportButton.textContent = t("action.generateHandover");
  const output = document.createElement("div");
  output.className = "wiki-page";
  exportButton.addEventListener("click", async () => {
    if (!projectId) {
      output.replaceChildren(renderEmptyState({
        title: t("projects.title"),
        body: t("view.noProject"),
        actionLabel: t("action.createProject"),
        onAction: showCreateProjectForm,
      }));
      return;
    }
    output.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
    try {
      const handover = await apiText(`/api/projects/${projectId}/handover`);
      const title = document.createElement("h3");
      title.textContent = t("settings.handover");
      const content = document.createElement("div");
      appendPre(content, handover);
      output.replaceChildren(title, content);
    } catch (error) {
      output.replaceChildren(renderEmptyState({
        title: t("empty.wiki.title"),
        body: `${t("empty.wiki.body")} ${error.message}`,
        actionLabel: t("action.generateEvidenceWiki"),
        onAction: buildCurrentProject,
        kind: "wiki",
      }));
    }
  });
  const diagnostics = createElement("div", "settings-grid");
  const logs = createElement("article", "record-card");
  logs.append(createElement("h3", "", t("settings.diagnostics")), createElement("p", "muted", t("error.readLogs")));
  const handover = createElement("article", "record-card");
  handover.append(createElement("h3", "", t("view.handover.title")), createElement("p", "muted", t("settings.export")), exportButton);
  diagnostics.append(handover, logs);
  panel.append(diagnostics, output);
  return panel;
}

async function loadView(view) {
  const appNode = appContainer();
  if (!appNode) return;
  activeView = normalizeView(view);
  setActiveView(activeView);
  appNode.replaceChildren(renderOperationFeedback("loading", t("view.loading")));

  try {
    if (activeView === "projects") {
      appNode.replaceChildren(await renderProjectsHome());
      return;
    }

    const projectId = requireProject();
    if (!projectId) {
      appNode.replaceChildren(renderNoProjectAction());
      return;
    }

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
    await ensureCurrentProject();
    updateWorkspaceChrome(true);
    const renderer = renderers[activeView] || renderStatus;
    appNode.replaceChildren(await renderer(projectId));
  } catch (error) {
    appNode.replaceChildren(renderOperationFeedback("error", t("view.error"), `${error.message} ${t("operation.error.recovery")}`));
  }
}

document.querySelectorAll("[data-lang]").forEach((button) => {
  button.addEventListener("click", () => translate(button.dataset.lang, { rerender: true }));
});

const actionHandlers = {
  createProject: showCreateProjectForm,
  ingest: showIngestForm,
  buildWiki: buildCurrentProject,
};

document.querySelectorAll("[data-action]").forEach((button) => {
  const handler = actionHandlers[button.dataset.action];
  if (handler) {
    button.addEventListener("click", handler);
  }
});

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => loadView(button.dataset.view));
});

const homeBrandButton = document.querySelector("#homeBrandButton");
if (homeBrandButton) {
  homeBrandButton.addEventListener("click", returnToProjectsHome);
}

const backToProjectsButton = document.querySelector("#backToProjectsButton");
if (backToProjectsButton) {
  backToProjectsButton.addEventListener("click", returnToProjectsHome);
}

document.addEventListener("click", (event) => {
  if (!event.target.closest(".project-card-menu-wrap")) closeProjectCardMenus();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeProjectCardMenus();
});

const githubLoginButton = document.querySelector("#loginGithubButton");
if (githubLoginButton) {
  githubLoginButton.addEventListener("click", startGithubLogin);
}

const giteaLoginButton = document.querySelector("#loginGiteaButton");
if (giteaLoginButton) {
  giteaLoginButton.addEventListener("click", () => {
    clearGithubPollTimer();
    const sessionId = nextAuthSessionId();
    authConnectionState = {
      sessionId,
      mode: "gitea_form",
      busy: false,
      message: null,
      github: null,
      gitea: authConnectionState.gitea || {},
    };
    renderAuthConnectionPanel();
  });
}

renderAuthConnectionPanel();
translate(initialLanguage());
loadCollaborationStatus();
loadView("projects");
