import base64
import hashlib
import json
from urllib.parse import parse_qs, urlparse

from whywiki.collaboration.oauth import (
    AuthSessionStore,
    GitHubDeviceFlowClient,
    GiteaOAuthClient,
    build_pkce_challenge,
    new_code_verifier,
)
from whywiki.collaboration.tokens import ProviderToken


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


def _request_form(request) -> dict[str, list[str]]:
    return parse_qs((request.data or b"").decode("utf-8"), keep_blank_values=True)


def test_auth_session_store_pops_state_once():
    store = AuthSessionStore()
    store.save("state-1", {"code_verifier": "verifier"})

    assert store.pop("state-1") == {"code_verifier": "verifier"}
    assert store.pop("state-1") is None
    assert store.pop("missing") is None


def test_auth_session_store_records_terminal_result_without_revealing_session():
    store = AuthSessionStore()
    store.save("state-1", {"provider": "gitea", "code_verifier": "secret-verifier"})

    assert store.peek("state-1") == {"provider": "gitea", "code_verifier": "secret-verifier"}

    store.save_result(
        "state-1",
        {
            "status": "failed",
            "provider": "gitea",
            "error": "oauth_misconfigured",
            "error_description": "Check the Gitea OAuth app.",
        },
    )

    assert store.pop("state-1") is None
    assert store.peek("state-1") is None
    assert store.result("state-1") == {
        "status": "failed",
        "provider": "gitea",
        "error": "oauth_misconfigured",
        "error_description": "Check the Gitea OAuth app.",
    }
    assert "secret-verifier" not in json.dumps(store.result("state-1"))


def test_auth_session_store_clears_pending_session_and_result():
    store = AuthSessionStore()
    store.save("state-1", {"provider": "gitea", "code_verifier": "secret-verifier"})
    store.save_result("state-1", {"status": "failed", "provider": "gitea"})

    store.clear("state-1")

    assert store.peek("state-1") is None
    assert store.result("state-1") is None


def test_pkce_challenge_is_sha256_urlsafe_without_padding():
    verifier = "a" * 64

    challenge = build_pkce_challenge(verifier)

    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    assert challenge == expected
    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge
    assert len(new_code_verifier()) >= 43


def test_github_device_flow_start_posts_form_headers_and_returns_prompt(monkeypatch):
    captured_requests = []

    def fake_urlopen(request, timeout):
        captured_requests.append((request, timeout))
        return _FakeHTTPResponse(
            {
                "device_code": "device-code",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = GitHubDeviceFlowClient(client_id="github-client", timeout=3.0).start()

    request, timeout = captured_requests[0]
    assert request.get_full_url() == "https://github.com/login/device/code"
    assert request.get_method() == "POST"
    assert timeout == 3.0
    assert _request_header(request, "Accept") == "application/json"
    assert _request_header(request, "Content-Type") == "application/x-www-form-urlencoded"
    assert _request_header(request, "User-Agent") == "WhyWiki"
    form = _request_form(request)
    assert form["client_id"] == ["github-client"]
    assert form["scope"] == ["repo read:user"]
    assert result == {
        "status": "waiting_for_user",
        "provider": "github",
        "device_code": "device-code",
        "user_code": "ABCD-1234",
        "verification_uri": "https://github.com/login/device",
        "expires_in": 900,
        "poll_after_seconds": 5,
    }


def test_github_device_flow_poll_reports_pending_and_success(monkeypatch):
    responses = [
        {"error": "authorization_pending"},
        {
            "access_token": "fake-github-token",
            "token_type": "bearer",
            "scope": "repo read:user",
        },
    ]
    captured_forms = []

    def fake_urlopen(request, timeout):
        captured_forms.append(_request_form(request))
        return _FakeHTTPResponse(responses.pop(0))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = GitHubDeviceFlowClient(client_id="github-client")

    pending = client.poll("device-code", current_interval=7)
    success = client.poll("device-code")

    assert pending == {
        "status": "waiting_for_user",
        "provider": "github",
        "error": "authorization_pending",
        "poll_after_seconds": 7,
    }
    assert captured_forms[0]["device_code"] == ["device-code"]
    assert captured_forms[0]["grant_type"] == ["urn:ietf:params:oauth:grant-type:device_code"]
    assert success["status"] == "authorized"
    assert success["provider"] == "github"
    assert success["token"] == ProviderToken(
        access_token="fake-github-token",
        token_type="bearer",
        scope="repo read:user",
    )


def test_github_device_flow_poll_slow_down_increases_poll_interval(monkeypatch):
    responses = [
        {"error": "slow_down"},
        {"error": "slow_down", "interval": 20},
    ]

    def fake_urlopen(request, timeout):
        return _FakeHTTPResponse(responses.pop(0))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = GitHubDeviceFlowClient(client_id="github-client")

    without_provider_interval = client.poll("device-code", current_interval=7)
    with_larger_provider_interval = client.poll("device-code", current_interval=7)

    assert without_provider_interval == {
        "status": "waiting_for_user",
        "provider": "github",
        "error": "slow_down",
        "poll_after_seconds": 12,
    }
    assert with_larger_provider_interval == {
        "status": "waiting_for_user",
        "provider": "github",
        "error": "slow_down",
        "poll_after_seconds": 20,
    }


def test_gitea_oauth_start_returns_authorization_url_and_session(monkeypatch):
    monkeypatch.setattr("whywiki.collaboration.oauth.token_urlsafe", lambda length: f"random-{length}")

    result = GiteaOAuthClient(
        base_url="https://git.example.test/",
        client_id="gitea-client",
        redirect_uri="http://127.0.0.1:8765/auth/callback",
    ).start()

    parsed = urlparse(result["authorization_url"])
    query = parse_qs(parsed.query)
    assert parsed.geturl().startswith("https://git.example.test/login/oauth/authorize?")
    assert result["status"] == "redirect"
    assert result["provider"] == "gitea"
    assert query["client_id"] == ["gitea-client"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8765/auth/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["read:user read:repository"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [result["state"]]
    assert result["state"] == "random-32"
    assert result["session"]["state"] == "random-32"
    assert result["session"]["client_id"] == "gitea-client"
    assert result["session"]["code_verifier"] == "random-64"
    assert query["code_challenge"] == [build_pkce_challenge("random-64")]


def test_gitea_exchange_code_posts_form_headers_and_returns_token(monkeypatch):
    captured_requests = []

    def fake_urlopen(request, timeout):
        captured_requests.append((request, timeout))
        return _FakeHTTPResponse(
            {
                "access_token": "fake-gitea-token",
                "token_type": "bearer",
                "scope": "read:user read:repository",
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    token = GiteaOAuthClient(
        base_url="https://git.example.test",
        client_id="gitea-client",
        redirect_uri="http://127.0.0.1:8765/auth/callback",
        timeout=4.0,
    ).exchange_code("auth-code", "code-verifier")

    request, timeout = captured_requests[0]
    form = _request_form(request)
    assert request.get_full_url() == "https://git.example.test/login/oauth/access_token"
    assert request.get_method() == "POST"
    assert timeout == 4.0
    assert _request_header(request, "Accept") == "application/json"
    assert _request_header(request, "Content-Type") == "application/x-www-form-urlencoded"
    assert _request_header(request, "User-Agent") == "WhyWiki"
    assert form["client_id"] == ["gitea-client"]
    assert form["redirect_uri"] == ["http://127.0.0.1:8765/auth/callback"]
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["auth-code"]
    assert form["code_verifier"] == ["code-verifier"]
    assert token == ProviderToken(
        access_token="fake-gitea-token",
        token_type="bearer",
        scope="read:user read:repository",
    )
