import json
import sys

import pytest
from fastapi.testclient import TestClient

from whywiki import app as app_module
from whywiki.app import app
from whywiki.collaboration.accounts import AccountStore
from whywiki.collaboration.models import ProviderIdentity
from whywiki.collaboration.tokens import FileTokenStore, KeyringTokenStore, ProviderToken


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


@pytest.fixture(autouse=True)
def isolate_auth_api_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("WHYWIKI_GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("WHYWIKI_COLLAB_STATIC_PERMISSIONS", raising=False)
    monkeypatch.setattr(KeyringTokenStore, "available", lambda self: False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    if hasattr(app_module, "auth_sessions"):
        app_module.auth_sessions._sessions.clear()
        if hasattr(app_module.auth_sessions, "_results"):
            app_module.auth_sessions._results.clear()


def _client() -> TestClient:
    return TestClient(app)


def _token_store(tmp_path):
    return FileTokenStore(tmp_path / "xdg" / "whywiki" / "tokens.json")


def test_github_device_start_requires_client_id_configuration():
    response = _client().post("/api/auth/github/device/start")

    assert response.status_code == 400
    assert "GitHub Client ID" in response.json()["detail"]
    assert "WhyWiki" in response.json()["detail"]
    assert "WHYWIKI_GITHUB_CLIENT_ID" not in response.json()["detail"]


def test_github_device_start_ignores_legacy_env_client_id(monkeypatch):
    monkeypatch.setenv("WHYWIKI_GITHUB_CLIENT_ID", "legacy-env-client")

    response = _client().post("/api/auth/github/device/start")

    assert response.status_code == 400
    assert "GitHub Client ID" in response.json()["detail"]


def test_github_device_start_accepts_client_id_from_request_body(monkeypatch):
    captured_forms = []

    def fake_urlopen(request, timeout):
        captured_forms.append(request.data.decode("utf-8"))
        return _FakeHTTPResponse(
            {
                "device_code": "device-123",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 7,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = _client().post(
        "/api/auth/github/device/start",
        json={"client_id": "github-client-from-ui"},
    )

    assert response.status_code == 200
    assert response.json()["user_code"] == "ABCD-EFGH"
    assert "client_id=github-client-from-ui" in captured_forms[0]


def test_github_device_start_returns_device_codes_and_poll_interval(monkeypatch):
    captured_requests = []

    def fake_urlopen(request, timeout):
        captured_requests.append(request)
        return _FakeHTTPResponse(
            {
                "device_code": "device-123",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 7,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = _client().post(
        "/api/auth/github/device/start",
        json={"client_id": "github-client"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "waiting_for_user",
        "provider": "github",
        "device_code": "device-123",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://github.com/login/device",
        "expires_in": 900,
        "interval": 7,
        "poll_after_seconds": 7,
    }
    assert captured_requests[0].full_url == "https://github.com/login/device/code"


def test_github_device_poll_authorized_saves_identity_and_token_without_returning_token(
    tmp_path,
    monkeypatch,
):
    identity = ProviderIdentity(provider="github", account="alice", provider_user_id="42")

    def fake_poll(self, device_code, current_interval=5):
        assert device_code == "device-123"
        assert current_interval == 7
        return {
            "status": "authorized",
            "provider": "github",
            "token": ProviderToken(access_token="secret-token", scope="repo"),
        }

    monkeypatch.setattr(app_module.GitHubDeviceFlowClient, "poll", fake_poll)
    monkeypatch.setattr(
        app_module.GitHubProviderClient,
        "authenticated_identity",
        lambda self: identity,
    )

    response = _client().post(
        "/api/auth/github/device/poll",
        json={"device_code": "device-123", "current_interval": 7, "client_id": "github-client"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "connected",
        "provider": "github",
        "identity": identity.to_dict(),
    }
    assert "secret-token" not in response.text
    assert AccountStore(tmp_path / "data" / "auth" / "accounts.json").list_identities() == [identity]
    assert _token_store(tmp_path).load(identity).access_token == "secret-token"


def test_github_device_poll_accepts_client_id_from_request_body(monkeypatch):
    constructed_client_ids = []

    class FakeGitHubDeviceFlowClient:
        def __init__(self, client_id):
            constructed_client_ids.append(client_id)

        def poll(self, device_code, current_interval=5):
            assert device_code == "device-123"
            assert current_interval == 7
            return {
                "status": "waiting_for_user",
                "provider": "github",
                "error": "authorization_pending",
                "poll_after_seconds": current_interval,
            }

    monkeypatch.setattr(app_module, "GitHubDeviceFlowClient", FakeGitHubDeviceFlowClient)

    response = _client().post(
        "/api/auth/github/device/poll",
        json={
            "device_code": "device-123",
            "current_interval": 7,
            "client_id": "github-client-from-ui",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "waiting_for_user"
    assert constructed_client_ids == ["github-client-from-ui"]


def test_github_device_poll_authorized_returns_503_when_token_store_unavailable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    identity = ProviderIdentity(provider="github", account="alice", provider_user_id="42")

    monkeypatch.setattr(
        app_module.GitHubDeviceFlowClient,
        "poll",
        lambda self, device_code, current_interval=5: {
            "status": "authorized",
            "provider": "github",
            "token": ProviderToken(access_token="secret-token", scope="repo"),
        },
    )
    monkeypatch.setattr(
        app_module.GitHubProviderClient,
        "authenticated_identity",
        lambda self: identity,
    )

    response = _client().post(
        "/api/auth/github/device/poll",
        json={"device_code": "device-123", "client_id": "github-client"},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "token storage" in detail.lower()
    assert detail.count("Install and configure a keyring backend") <= 1
    assert AccountStore(app_module.get_data_dir() / "auth" / "accounts.json").list_identities() == []


def test_github_device_poll_pending_passes_through_without_saving_account_or_token(
    tmp_path,
    monkeypatch,
):
    def fake_poll(self, device_code, current_interval=5):
        return {
            "status": "waiting_for_user",
            "provider": "github",
            "error": "authorization_pending",
            "poll_after_seconds": current_interval,
        }

    monkeypatch.setattr(app_module.GitHubDeviceFlowClient, "poll", fake_poll)

    response = _client().post(
        "/api/auth/github/device/poll",
        json={"device_code": "device-123", "current_interval": 8, "client_id": "github-client"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "waiting_for_user"
    assert response.json()["poll_after_seconds"] == 8
    assert AccountStore(tmp_path / "data" / "auth" / "accounts.json").list_identities() == []
    assert not (tmp_path / "xdg" / "whywiki" / "tokens.json").exists()


def test_gitea_start_requires_base_url_and_client_id():
    client = _client()

    missing_base_url = client.post(
        "/api/auth/gitea/start",
        json={"base_url": "", "client_id": "client"},
    )
    missing_client_id = client.post(
        "/api/auth/gitea/start",
        json={"base_url": "https://git.example.test", "client_id": ""},
    )

    assert missing_base_url.status_code == 400
    assert "base_url" in missing_base_url.json()["detail"]
    assert missing_client_id.status_code == 400
    assert "client_id" in missing_client_id.json()["detail"]


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://git.example.test",
        "http://:8765",
        "http://@",
        "http://user@:80",
    ],
)
def test_gitea_start_rejects_invalid_base_url(base_url):
    response = _client().post(
        "/api/auth/gitea/start",
        json={"base_url": base_url, "client_id": "gitea-client"},
    )

    assert response.status_code == 400
    assert "http(s)" in response.json()["detail"]


def test_gitea_start_stores_session_and_returns_authorization_url_without_token(monkeypatch):
    def fake_start(self):
        return {
            "status": "redirect",
            "provider": "gitea",
            "authorization_url": "https://git.example.test/login/oauth/authorize?state=state-123",
            "state": "state-123",
            "session": {"state": "state-123", "code_verifier": "verifier"},
        }

    monkeypatch.setattr(app_module.GiteaOAuthClient, "start", fake_start)

    response = _client().post(
        "/api/auth/gitea/start",
        json={"base_url": "https://git.example.test", "client_id": "gitea-client"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "redirect",
        "provider": "gitea",
        "authorization_url": "https://git.example.test/login/oauth/authorize?state=state-123",
        "state": "state-123",
    }
    assert "verifier" not in response.text
    assert app_module.auth_sessions.pop("state-123") == {"state": "state-123", "code_verifier": "verifier"}


def test_gitea_status_reports_waiting_session_without_session_secret(monkeypatch):
    def fake_start(self):
        return {
            "status": "redirect",
            "provider": "gitea",
            "authorization_url": "https://git.example.test/login/oauth/authorize?state=state-123",
            "state": "state-123",
            "session": {
                "provider": "gitea",
                "base_url": "https://git.example.test",
                "state": "state-123",
                "code_verifier": "secret-verifier",
            },
        }

    monkeypatch.setattr(app_module.GiteaOAuthClient, "start", fake_start)

    start = _client().post(
        "/api/auth/gitea/start",
        json={"base_url": "https://git.example.test", "client_id": "gitea-client"},
    )
    status = _client().get(f"/api/auth/gitea/status?state={start.json()['state']}")

    assert status.status_code == 200
    assert status.json() == {"status": "waiting_for_user", "provider": "gitea"}
    assert "secret-verifier" not in status.text


def test_gitea_callback_missing_code_or_state_returns_html_400():
    missing_code = _client().get("/api/auth/gitea/callback?state=state-123")
    missing_state = _client().get("/api/auth/gitea/callback?code=code-123")

    assert missing_code.status_code == 400
    assert missing_code.headers["content-type"].startswith("text/html")
    assert "authorization was not completed" in missing_code.text.lower()
    assert missing_state.status_code == 400
    assert missing_state.headers["content-type"].startswith("text/html")
    assert "authorization was not completed" in missing_state.text.lower()


def test_gitea_callback_invalid_state_returns_html_400():
    response = _client().get("/api/auth/gitea/callback?code=code-123&state=missing")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "session expired" in response.text.lower()
    assert "start gitea login again" in response.text.lower()


def test_gitea_callback_success_saves_identity_and_token(tmp_path, monkeypatch):
    identity = ProviderIdentity(
        provider="gitea",
        base_url="https://git.example.test",
        account="alice",
        provider_user_id="99",
    )
    app_module.auth_sessions.save(
        "state-123",
        {
            "base_url": "https://git.example.test",
            "client_id": "gitea-client",
            "redirect_uri": "http://127.0.0.1:8765/api/auth/gitea/callback",
            "code_verifier": "verifier",
        },
    )

    def fake_exchange_code(self, code, code_verifier):
        assert code == "code-123"
        assert code_verifier == "verifier"
        return ProviderToken(access_token="gitea-secret", scope="read:user")

    monkeypatch.setattr(app_module.GiteaOAuthClient, "exchange_code", fake_exchange_code)
    monkeypatch.setattr(
        app_module.GiteaProviderClient,
        "authenticated_identity",
        lambda self: identity,
    )

    response = _client().get("/api/auth/gitea/callback?code=code-123&state=state-123")

    assert response.status_code == 200
    assert "connected" in response.text.lower()
    assert "gitea-secret" not in response.text
    assert AccountStore(tmp_path / "data" / "auth" / "accounts.json").list_identities() == [identity]
    assert _token_store(tmp_path).load(identity).access_token == "gitea-secret"
    status = _client().get("/api/auth/gitea/status?state=state-123")
    assert status.status_code == 200
    assert status.json() == {
        "status": "connected",
        "provider": "gitea",
        "identity": identity.to_dict(),
    }
    assert "gitea-secret" not in status.text


def test_gitea_callback_provider_failure_returns_html_without_saving_account(tmp_path, monkeypatch):
    app_module.auth_sessions.save(
        "state-123",
        {
            "base_url": "https://git.example.test",
            "client_id": "gitea-client",
            "redirect_uri": "http://127.0.0.1:8765/api/auth/gitea/callback",
            "code_verifier": "verifier",
        },
    )

    def fail_exchange_code(self, code, code_verifier):
        raise RuntimeError("provider returned malformed token response")

    monkeypatch.setattr(app_module.GiteaOAuthClient, "exchange_code", fail_exchange_code)

    response = _client().get("/api/auth/gitea/callback?code=code-123&state=state-123")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "gitea login failed" in response.text.lower()
    assert "provider returned malformed" not in response.text
    assert AccountStore(tmp_path / "data" / "auth" / "accounts.json").list_identities() == []
    status = _client().get("/api/auth/gitea/status?state=state-123")
    assert status.status_code == 200
    assert status.json()["status"] == "failed"
    assert status.json()["provider"] == "gitea"
    assert status.json()["error"] == "oauth_exchange_failed"
    assert "Redirect URL" in status.json()["error_description"]
    assert "provider returned malformed" not in status.text


def test_gitea_callback_provider_error_records_failed_status(monkeypatch):
    app_module.auth_sessions.save(
        "state-123",
        {
            "provider": "gitea",
            "base_url": "https://git.example.test",
            "client_id": "gitea-client",
            "redirect_uri": "http://127.0.0.1:8765/api/auth/gitea/callback",
            "code_verifier": "verifier",
        },
    )

    response = _client().get("/api/auth/gitea/callback?error=access_denied&state=state-123")

    assert response.status_code == 400
    assert "authorization was not completed" in response.text.lower()
    status = _client().get("/api/auth/gitea/status?state=state-123")
    assert status.status_code == 200
    assert status.json()["status"] == "failed"
    assert status.json()["provider"] == "gitea"
    assert status.json()["error"] == "access_denied"


def test_gitea_status_expired_and_cancel_clear_pending_session():
    app_module.auth_sessions.save(
        "state-123",
        {
            "provider": "gitea",
            "base_url": "https://git.example.test",
            "client_id": "gitea-client",
            "redirect_uri": "http://127.0.0.1:8765/api/auth/gitea/callback",
            "code_verifier": "secret-verifier",
        },
    )

    cancelled = _client().post("/api/auth/gitea/cancel", json={"state": "state-123"})
    expired = _client().get("/api/auth/gitea/status?state=state-123")

    assert cancelled.status_code == 200
    assert cancelled.json() == {"status": "cancelled", "provider": "gitea"}
    assert expired.status_code == 200
    assert expired.json()["status"] == "expired"
    assert expired.json()["provider"] == "gitea"
    assert expired.json()["error"] == "session_expired"
    assert "secret-verifier" not in expired.text


def test_delete_account_removes_identity_and_token(tmp_path, monkeypatch):
    identity = ProviderIdentity(provider="github", account="alice", provider_user_id="42")
    AccountStore(tmp_path / "data" / "auth" / "accounts.json").save_identity(identity)
    _token_store(tmp_path).save(identity, ProviderToken(access_token="secret-token"))

    response = _client().delete("/api/auth/accounts/github%3A42")

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert AccountStore(tmp_path / "data" / "auth" / "accounts.json").list_identities() == []
    assert _token_store(tmp_path).load(identity) is None


def test_delete_account_preserves_identity_when_token_store_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    identity = ProviderIdentity(provider="github", account="alice", provider_user_id="42")
    store = AccountStore(tmp_path / "data" / "auth" / "accounts.json")
    store.save_identity(identity)

    response = _client().delete("/api/auth/accounts/github%3A42")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "token storage" in detail.lower()
    assert detail.count("Install and configure a keyring backend") <= 1
    assert store.list_identities() == [identity]


def test_delete_missing_account_does_not_require_token_store():
    response = _client().delete("/api/auth/accounts/github%3A404")

    assert response.status_code == 200
    assert response.json() == {"deleted": False}


def test_auth_accounts_returns_only_metadata(tmp_path, monkeypatch):
    identity = ProviderIdentity(provider="github", account="alice", provider_user_id="42")
    AccountStore(tmp_path / "data" / "auth" / "accounts.json").save_identity(identity)
    _token_store(tmp_path).save(identity, ProviderToken(access_token="secret-token"))

    response = _client().get("/api/auth/accounts")

    assert response.status_code == 200
    assert response.json() == {"connected_accounts": [identity.to_dict()]}
    assert "secret-token" not in response.text
