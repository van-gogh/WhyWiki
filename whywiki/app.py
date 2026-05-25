from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .collaboration.accounts import AccountStore
from .collaboration.artifacts import (
    WorkspaceArtifactPaths,
    load_workspace_config,
    save_workspace_config,
)
from .collaboration.env import static_provider_registry_from_env
from .collaboration.models import RepoRef, WorkspaceConfig
from .collaboration.oauth import AuthSessionStore, GitHubDeviceFlowClient, GiteaOAuthClient
from .collaboration.providers import GitHubProviderClient, GiteaProviderClient
from .collaboration.registry import provider_registry_from_accounts
from .collaboration.tokens import TokenStoreUnavailable, default_token_store
from .config import get_data_dir
from .db import connect, init_db, rows_to_dicts
from .services.ask import ask_project
from .services.collaboration import CollaborationService
from .services.evidence import conflict_evidence, fact_evidence
from .services.ingest import ingest_path
from .services.jobs import create_job, get_job, start_background_job
from .services.wiki_engine import build_project
from .services.workspace import create_project, delete_project, get_project, list_projects

app = FastAPI(title="WhyWiki", version="0.1.0")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
auth_sessions = AuthSessionStore()


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""


class IngestRequest(BaseModel):
    path: str
    source_type: str = "local"


class AskRequest(BaseModel):
    question: str


class ConflictStatusRequest(BaseModel):
    status: str


class FactStatusRequest(BaseModel):
    status: str


class ConnectWorkspaceRequest(BaseModel):
    provider: str
    repo: str
    base_url: str | None = None


class GitHubDevicePollRequest(BaseModel):
    device_code: str
    current_interval: float = 5
    client_id: str | None = None


class GitHubDeviceStartRequest(BaseModel):
    client_id: str | None = None


class GiteaStartRequest(BaseModel):
    base_url: str
    client_id: str


def account_store() -> AccountStore:
    return AccountStore(get_data_dir() / "auth" / "accounts.json")


def require_token_store():
    try:
        return default_token_store()
    except TokenStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Token storage is unavailable: {exc}",
        ) from exc


def github_client_id(client_id: str | None = None) -> str:
    value = (client_id or "").strip()
    if not value:
        raise HTTPException(
            status_code=400,
            detail=(
                "GitHub Client ID is required for GitHub login. "
                "Enter it in WhyWiki before opening GitHub authorization."
            ),
        )
    return value


def workspace_paths() -> WorkspaceArtifactPaths:
    return WorkspaceArtifactPaths(get_data_dir() / "workspace")


def provider_registry():
    identities = account_store().list_identities()
    try:
        return provider_registry_from_accounts(
            identities,
            default_token_store(),
            os.environ,
        )
    except TokenStoreUnavailable as exc:
        if identities:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Token storage is unavailable for connected provider accounts: {exc}"
                ),
            ) from exc
        return static_provider_registry_from_env()


def collaboration_service_or_none() -> CollaborationService | None:
    paths = workspace_paths()
    if not paths.workspace_config_path.exists():
        return None
    return CollaborationService(
        load_workspace_config(paths),
        provider_registry(),
    )


def workspace_status_payload(project_slug: str | None = None) -> dict:
    paths = workspace_paths()
    if not paths.workspace_config_path.exists():
        return {"configured": False, "workspace": None, "projects": {}, "access": None}
    config = load_workspace_config(paths)
    report = CollaborationService(config, provider_registry()).check_workspace(project_slug)
    return {"configured": True, **config.to_dict(), "access": report.to_dict()}


def validate_gitea_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    parsed = urlparse(value)
    if not value or parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise HTTPException(status_code=400, detail="base_url must be an http(s) URL with a host.")
    return value


def require_workspace_read_if_configured(project_slug: str | None = None) -> None:
    service = collaboration_service_or_none()
    if service is None:
        return
    try:
        service.require_workspace_read(project_slug=project_slug)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def require_review_access_if_configured(project_slug: str | None = None) -> None:
    service = collaboration_service_or_none()
    if service is None:
        return
    try:
        service.require_review_access(project_slug=project_slug)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    for asset_name in ("styles.css", "i18n.js", "app.js"):
        version = (static_dir / asset_name).stat().st_mtime_ns
        html = html.replace(f'/static/{asset_name}"', f'/static/{asset_name}?v={version}"')
    return html


@app.post("/api/projects")
def api_create_project(req: CreateProjectRequest) -> dict:
    require_workspace_read_if_configured()
    return create_project(req.name, req.description)


@app.get("/api/projects")
def api_list_projects() -> list[dict]:
    require_workspace_read_if_configured()
    return list_projects()


@app.get("/api/auth/accounts")
def api_auth_accounts() -> dict:
    return {
        "connected_accounts": [
            identity.to_dict()
            for identity in account_store().list_identities()
        ]
    }


@app.delete("/api/auth/accounts/{identity_key:path}")
def api_delete_auth_account(identity_key: str) -> dict:
    decoded_identity_key = unquote(identity_key)
    store = account_store()
    identity = next(
        (
            stored_identity
            for stored_identity in store.list_identities()
            if stored_identity.identity_key == decoded_identity_key
        ),
        None,
    )
    if identity is None:
        return {"deleted": False}

    require_token_store().delete(identity)
    return {"deleted": store.delete_identity(decoded_identity_key)}


@app.post("/api/auth/github/device/start")
def api_github_device_start(req: GitHubDeviceStartRequest | None = None) -> dict:
    result = GitHubDeviceFlowClient(github_client_id(req.client_id if req else None)).start()
    result.setdefault("interval", result.get("poll_after_seconds", 5))
    return result


@app.post("/api/auth/github/device/poll")
def api_github_device_poll(req: GitHubDevicePollRequest) -> dict:
    result = GitHubDeviceFlowClient(github_client_id(req.client_id)).poll(
        req.device_code,
        current_interval=req.current_interval,
    )
    if result.get("status") != "authorized":
        return result

    token = result["token"]
    identity = GitHubProviderClient(token.access_token).authenticated_identity()
    require_token_store().save(identity, token)
    account_store().save_identity(identity)
    return {"status": "connected", "provider": "github", "identity": identity.to_dict()}


@app.post("/api/auth/gitea/start")
def api_gitea_start(req: GiteaStartRequest) -> dict:
    base_url = req.base_url.strip()
    client_id = req.client_id.strip()
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required for Gitea login.")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required for Gitea login.")
    base_url = validate_gitea_base_url(base_url)

    redirect_uri = "http://127.0.0.1:8765/api/auth/gitea/callback"
    result = GiteaOAuthClient(base_url, client_id, redirect_uri).start()
    auth_sessions.save(result["state"], result["session"])
    return {
        "status": result["status"],
        "provider": result["provider"],
        "authorization_url": result["authorization_url"],
        "state": result["state"],
    }


@app.get("/api/auth/gitea/callback", response_class=HTMLResponse)
def api_gitea_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    if error:
        return HTMLResponse(
            "<html><body><h1>Gitea login failed</h1><p>Authorization was not completed.</p></body></html>"
        )
    if not code or not state:
        return _gitea_auth_failure(
            "Gitea authorization was not completed.",
            "Please start Gitea login again from WhyWiki.",
        )

    session = auth_sessions.pop(state)
    if session is None:
        return _gitea_auth_failure(
            "Gitea login session expired.",
            "Please start Gitea login again from WhyWiki.",
        )

    client = GiteaOAuthClient(
        session["base_url"],
        session["client_id"],
        session["redirect_uri"],
    )
    try:
        token = client.exchange_code(code, session["code_verifier"])
        identity = GiteaProviderClient(session["base_url"], token.access_token).authenticated_identity()
        require_token_store().save(identity, token)
        account_store().save_identity(identity)
    except Exception:
        return _gitea_auth_failure(
            "Gitea login failed.",
            "WhyWiki could not complete provider authorization. Please check token storage and Gitea OAuth settings, then start login again.",
        )
    return HTMLResponse("<html><body><h1>Gitea connected</h1><p>You can return to WhyWiki.</p></body></html>")


def _gitea_auth_failure(title: str, guidance: str) -> HTMLResponse:
    return HTMLResponse(
        f"<html><body><h1>{title}</h1><p>{guidance}</p></body></html>",
        status_code=400,
    )


@app.post("/api/workspace/connect")
def api_connect_workspace(req: ConnectWorkspaceRequest) -> dict:
    try:
        config = WorkspaceConfig(
            workspace=RepoRef(
                provider=req.provider,
                repo=req.repo,
                base_url=req.base_url,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_workspace_config(workspace_paths(), config)
    return {"workspace": config.workspace.to_dict()}


@app.get("/api/workspace/status")
def api_workspace_status(project_slug: str | None = None) -> dict:
    return workspace_status_payload(project_slug)


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str) -> dict:
    require_workspace_read_if_configured(project_id)
    try:
        return get_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str) -> dict:
    require_review_access_if_configured(project_id)
    try:
        delete_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": True, "project_id": project_id}


@app.post("/api/projects/{project_id}/ingest")
def api_ingest(project_id: str, req: IngestRequest) -> dict:
    require_workspace_read_if_configured(project_id)
    try:
        get_project(project_id)
        return ingest_path(project_id, req.path, req.source_type)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/ingest-jobs")
def api_start_ingest_job(project_id: str, req: IngestRequest) -> dict:
    require_workspace_read_if_configured(project_id)
    try:
        get_project(project_id)
        job = create_job(project_id, "ingest", "Queued project scan.")
        start_background_job(
            job["id"],
            lambda: ingest_path(project_id, req.path, req.source_type),
            "Scanning project source.",
            "Project source scanned.",
        )
        return get_job(job["id"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/build")
def api_build(project_id: str) -> dict:
    require_workspace_read_if_configured(project_id)
    try:
        get_project(project_id)
        return build_project(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/build-jobs")
def api_start_build_job(project_id: str) -> dict:
    require_workspace_read_if_configured(project_id)
    try:
        get_project(project_id)
        job = create_job(project_id, "build", "Queued Wiki generation.")
        start_background_job(
            job["id"],
            lambda: build_project(project_id),
            "Generating evidence-backed Wiki.",
            "Evidence-backed Wiki generated.",
        )
        return get_job(job["id"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str) -> dict:
    try:
        job = get_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    require_workspace_read_if_configured(job["project_id"])
    return job


@app.get("/api/projects/{project_id}/wiki")
def api_list_wiki(project_id: str) -> list[dict]:
    require_workspace_read_if_configured(project_id)
    with connect() as conn:
        rows = conn.execute("SELECT slug, title, updated_at FROM wiki_pages WHERE project_id = ? ORDER BY slug", (project_id,)).fetchall()
        return rows_to_dicts(rows)


@app.get("/api/projects/{project_id}/sources")
def api_list_sources(project_id: str) -> list[dict]:
    require_workspace_read_if_configured(project_id)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sources WHERE project_id = ? ORDER BY path",
            (project_id,),
        ).fetchall()
        return rows_to_dicts(rows)


@app.get("/api/projects/{project_id}/sources/{source_id}/blocks")
def api_list_source_blocks(project_id: str, source_id: str) -> list[dict]:
    require_workspace_read_if_configured(project_id)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM blocks
            WHERE project_id = ? AND source_id = ?
            ORDER BY id
            """,
            (project_id, source_id),
        ).fetchall()
        return rows_to_dicts(rows)


@app.get("/api/projects/{project_id}/facts")
def api_list_facts(project_id: str) -> list[dict]:
    require_workspace_read_if_configured(project_id)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM facts WHERE project_id = ? ORDER BY fact_type, confidence DESC",
            (project_id,),
        ).fetchall()
        return rows_to_dicts(rows)


@app.patch("/api/projects/{project_id}/facts/{fact_id}")
def api_update_fact(project_id: str, fact_id: str, req: FactStatusRequest) -> dict:
    if req.status not in {"candidate", "confirmed", "needs_review"}:
        raise HTTPException(status_code=400, detail="Invalid fact status")
    require_review_access_if_configured(project_id)
    validity_status = "current" if req.status == "confirmed" else "unknown"
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM facts WHERE project_id = ? AND id = ?",
            (project_id, fact_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Fact not found")
        conn.execute(
            "UPDATE facts SET status = ?, validity_status = ? WHERE project_id = ? AND id = ?",
            (req.status, validity_status, project_id, fact_id),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM facts WHERE project_id = ? AND id = ?",
            (project_id, fact_id),
        ).fetchone()
        return dict(updated)


@app.get("/api/projects/{project_id}/facts/{fact_id}/evidence")
def api_fact_evidence(project_id: str, fact_id: str) -> list[dict]:
    require_workspace_read_if_configured(project_id)
    try:
        return fact_evidence(project_id, fact_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/wiki/{slug}", response_class=PlainTextResponse)
def api_get_wiki_page(project_id: str, slug: str) -> str:
    require_workspace_read_if_configured(project_id)
    with connect() as conn:
        row = conn.execute("SELECT content FROM wiki_pages WHERE project_id = ? AND slug = ?", (project_id, slug)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Wiki page not found")
        return row["content"]


@app.get("/api/projects/{project_id}/conflicts")
def api_conflicts(project_id: str) -> list[dict]:
    require_workspace_read_if_configured(project_id)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM conflicts WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
        return rows_to_dicts(rows)


@app.get("/api/projects/{project_id}/conflicts/{conflict_id}/evidence")
def api_conflict_evidence(project_id: str, conflict_id: str) -> list[dict]:
    require_workspace_read_if_configured(project_id)
    try:
        return conflict_evidence(project_id, conflict_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/projects/{project_id}/conflicts/{conflict_id}")
def api_update_conflict(project_id: str, conflict_id: str, req: ConflictStatusRequest) -> dict:
    if req.status not in {"open", "resolved", "ignored"}:
        raise HTTPException(status_code=400, detail="Invalid conflict status")
    require_review_access_if_configured(project_id)
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM conflicts WHERE project_id = ? AND id = ?",
            (project_id, conflict_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Conflict not found")
        conn.execute(
            "UPDATE conflicts SET status = ? WHERE project_id = ? AND id = ?",
            (req.status, project_id, conflict_id),
        )
        conn.commit()
        return {"id": conflict_id, "status": req.status}


@app.get("/api/projects/{project_id}/handover", response_class=PlainTextResponse)
def api_handover(project_id: str) -> str:
    require_workspace_read_if_configured(project_id)
    with connect() as conn:
        row = conn.execute("SELECT content FROM wiki_pages WHERE project_id = ? AND slug = 'handover'", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Handover page not found. Run build first.")
        return row["content"]


@app.post("/api/projects/{project_id}/ask")
def api_ask(project_id: str, req: AskRequest) -> dict:
    require_workspace_read_if_configured(project_id)
    return ask_project(project_id, req.question)
