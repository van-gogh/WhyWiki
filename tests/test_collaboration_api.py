import json
import sys

import pytest
from fastapi.testclient import TestClient

from whywiki.collaboration.accounts import AccountStore
from whywiki.collaboration.artifacts import WorkspaceArtifactPaths, save_workspace_config
from whywiki.collaboration.models import LinkedRepo, ProviderIdentity, RepoRef, WorkspaceConfig
from whywiki.collaboration.tokens import FileTokenStore, KeyringTokenStore, ProviderToken
from whywiki.app import app
from whywiki.db import connect
from whywiki.services.conflict_detector import insert_conflict
from whywiki.services.workspace import create_project


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _request_header(request, name: str) -> str | None:
    for header_name, value in request.header_items():
        if header_name.lower() == name.lower():
            return value
    return None


@pytest.fixture(autouse=True)
def isolate_provider_auth_env(tmp_path, monkeypatch):
    monkeypatch.delenv("WHYWIKI_COLLAB_STATIC_PERMISSIONS", raising=False)
    monkeypatch.delenv("WHYWIKI_GITHUB_CLIENT_ID", raising=False)
    monkeypatch.setattr(KeyringTokenStore, "available", lambda self: False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))


def project_with_conflict() -> tuple[str, str]:
    project = create_project("Review Project")
    with connect() as conn:
        insert_conflict(
            conn,
            project["id"],
            "review_gate_fixture",
            "人工审查权限门禁测试冲突",
            "用于验证冲突解决操作是否经过 workspace write 权限门禁。",
            [{"path": "docs/decision.md"}],
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM conflicts WHERE project_id = ?",
            (project["id"],),
        ).fetchone()
    assert row is not None
    return project["id"], row["id"]


def test_auth_accounts_endpoint_starts_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)

    response = client.get("/api/auth/accounts")

    assert response.status_code == 200
    assert response.json() == {"connected_accounts": []}


def test_workspace_status_reports_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)

    response = client.get("/api/workspace/status")

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["access"] is None


def test_workspace_status_reads_configured_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)

    create = client.post(
        "/api/workspace/connect",
        json={"provider": "github", "repo": "owner/whywiki-memory"},
    )
    status = client.get("/api/workspace/status")

    assert create.status_code == 200
    assert status.status_code == 200
    assert status.json()["configured"] is True
    assert status.json()["workspace"]["repo"] == "owner/whywiki-memory"
    assert status.json()["access"]["can_enter_workspace"] is False
    assert status.json()["access"]["workspace"]["missing_provider_identity"] == "github"


def test_workspace_status_uses_stored_provider_token(tmp_path, monkeypatch):
    captured_requests = []
    data_dir = tmp_path / "data"
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(data_dir))
    identity = ProviderIdentity(provider="github", account="alice", provider_user_id="1")
    AccountStore(data_dir / "auth" / "accounts.json").save_identity(identity)
    FileTokenStore(tmp_path / "xdg" / "whywiki" / "tokens.json").save(
        identity,
        ProviderToken(access_token="github-token"),
    )

    def fake_urlopen(request, timeout):
        captured_requests.append(request)
        return _FakeHTTPResponse({"permissions": {"push": True}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = TestClient(app)

    create = client.post(
        "/api/workspace/connect",
        json={"provider": "github", "repo": "owner/whywiki-memory"},
    )
    status = client.get("/api/workspace/status")

    assert create.status_code == 200
    assert status.status_code == 200
    assert _request_header(captured_requests[0], "Authorization") == "Bearer github-token"
    assert "github-token" not in captured_requests[0].get_full_url()
    assert status.json()["access"]["can_enter_workspace"] is True
    assert status.json()["access"]["can_review"] is True


def test_workspace_status_reports_token_store_unavailable_for_connected_account(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    data_dir = tmp_path / "data"
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(data_dir))
    identity = ProviderIdentity(provider="github", account="alice", provider_user_id="1")
    AccountStore(data_dir / "auth" / "accounts.json").save_identity(identity)
    client = TestClient(app)

    create = client.post(
        "/api/workspace/connect",
        json={"provider": "github", "repo": "owner/whywiki-memory"},
    )
    status = client.get("/api/workspace/status")

    assert create.status_code == 200
    assert status.status_code == 503
    assert "token storage" in status.json()["detail"].lower()


def test_workspace_status_reports_project_linked_repo_access(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(data_dir))
    monkeypatch.setenv(
        "WHYWIKI_COLLAB_STATIC_PERMISSIONS",
        "github:owner/whywiki-memory=write",
    )
    client = TestClient(app)
    project = create_project("Linked Repo Project")
    save_workspace_config(
        WorkspaceArtifactPaths(data_dir / "workspace"),
        WorkspaceConfig(
            workspace=RepoRef(provider="github", repo="owner/whywiki-memory"),
            projects={
                project["id"]: [
                    LinkedRepo(id="backend", repo=RepoRef(provider="github", repo="owner/code"), required=True),
                ]
            },
        ),
    )

    response = client.get(f"/api/workspace/status?project_slug={project['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["access"]["can_enter_workspace"] is True
    assert payload["access"]["can_review"] is True
    assert payload["access"]["missing_required_linked_repo_access"] is True
    assert payload["access"]["missing_required_linked_repo_permissions"][0]["repo_key"] == "github:owner/code"


def test_gitea_workspace_requires_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)

    response = client.post(
        "/api/workspace/connect",
        json={"provider": "gitea", "repo": "owner/whywiki-memory"},
    )

    assert response.status_code == 400
    assert "base_url" in response.json()["detail"]


def test_workspace_files_go_under_data_dir_workspace(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(data_dir))
    client = TestClient(app)

    response = client.post(
        "/api/workspace/connect",
        json={"provider": "github", "repo": "owner/whywiki-memory"},
    )

    assert response.status_code == 200
    assert (data_dir / "workspace" / "whywiki.yaml").exists()


def test_project_read_apis_require_workspace_read_permission_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Private Workspace Project")
    connect_response = client.post(
        "/api/workspace/connect",
        json={"provider": "github", "repo": "owner/whywiki-memory"},
    )
    assert connect_response.status_code == 200

    endpoints = [
        "/api/projects",
        f"/api/projects/{project['id']}",
        f"/api/projects/{project['id']}/facts",
        f"/api/projects/{project['id']}/conflicts",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 403, endpoint
        assert "cannot read this WhyWiki workspace repo" in response.json()["detail"]


def test_project_read_apis_allow_workspace_read_permission_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(
        "WHYWIKI_COLLAB_STATIC_PERMISSIONS",
        "github:owner/whywiki-memory=read",
    )
    client = TestClient(app)
    project = create_project("Readable Workspace Project")
    connect_response = client.post(
        "/api/workspace/connect",
        json={"provider": "github", "repo": "owner/whywiki-memory"},
    )
    assert connect_response.status_code == 200

    projects = client.get("/api/projects")
    project_response = client.get(f"/api/projects/{project['id']}")

    assert projects.status_code == 200
    assert project_response.status_code == 200


def test_conflict_resolution_without_workspace_keeps_local_behavior(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project_id, conflict_id = project_with_conflict()

    response = client.patch(
        f"/api/projects/{project_id}/conflicts/{conflict_id}",
        json={"status": "resolved"},
    )

    assert response.status_code == 200
    assert response.json() == {"id": conflict_id, "status": "resolved"}


def test_conflict_resolution_requires_workspace_write_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(
        "WHYWIKI_COLLAB_STATIC_PERMISSIONS",
        "github:owner/whywiki-memory=read",
    )
    client = TestClient(app)
    project_id, conflict_id = project_with_conflict()
    connect_response = client.post(
        "/api/workspace/connect",
        json={"provider": "github", "repo": "owner/whywiki-memory"},
    )
    assert connect_response.status_code == 200

    response = client.patch(
        f"/api/projects/{project_id}/conflicts/{conflict_id}",
        json={"status": "resolved"},
    )

    assert response.status_code == 403


def test_conflict_resolution_requires_required_linked_repo_read_permission(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(data_dir))
    monkeypatch.setenv(
        "WHYWIKI_COLLAB_STATIC_PERMISSIONS",
        "github:owner/whywiki-memory=write",
    )
    client = TestClient(app)
    project_id, conflict_id = project_with_conflict()
    save_workspace_config(
        WorkspaceArtifactPaths(data_dir / "workspace"),
        WorkspaceConfig(
            workspace=RepoRef(provider="github", repo="owner/whywiki-memory"),
            projects={
                project_id: [
                    LinkedRepo(id="backend", repo=RepoRef(provider="github", repo="owner/code"), required=True),
                ]
            },
        ),
    )

    response = client.patch(
        f"/api/projects/{project_id}/conflicts/{conflict_id}",
        json={"status": "resolved"},
    )

    assert response.status_code == 403
    assert "cannot read all required linked source repos" in response.json()["detail"]


def test_conflict_resolution_allows_workspace_write_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(
        "WHYWIKI_COLLAB_STATIC_PERMISSIONS",
        "gitea:https://git.example.test:team/backend=write",
    )
    client = TestClient(app)
    project_id, conflict_id = project_with_conflict()
    connect_response = client.post(
        "/api/workspace/connect",
        json={
            "provider": "gitea",
            "base_url": "https://git.example.test",
            "repo": "team/backend",
        },
    )
    assert connect_response.status_code == 200

    response = client.patch(
        f"/api/projects/{project_id}/conflicts/{conflict_id}",
        json={"status": "resolved"},
    )

    assert response.status_code == 200
    assert response.json() == {"id": conflict_id, "status": "resolved"}
