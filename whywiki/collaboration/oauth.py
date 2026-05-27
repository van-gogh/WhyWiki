from __future__ import annotations

import base64
import hashlib
import json
from secrets import token_urlsafe
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from whywiki.collaboration.tokens import ProviderToken


def _post_form(url: str, data: dict[str, str], timeout: float) -> dict[str, Any]:
    from urllib.error import HTTPError
    from urllib.request import urlopen

    request = Request(
        url,
        data=urlencode(data).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "WhyWiki",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            raise RuntimeError(f"provider OAuth request failed: {exc.code} {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise ValueError("provider OAuth response must be a JSON object")
    return payload


def build_pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def new_code_verifier() -> str:
    return token_urlsafe(64)


class AuthSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._results: dict[str, dict[str, Any]] = {}

    def save(self, state: str, payload: dict[str, Any]) -> None:
        self._sessions[state] = dict(payload)
        self._results.pop(state, None)

    def pop(self, state: str) -> dict[str, Any] | None:
        return self._sessions.pop(state, None)

    def peek(self, state: str) -> dict[str, Any] | None:
        payload = self._sessions.get(state)
        return dict(payload) if payload is not None else None

    def save_result(self, state: str, payload: dict[str, Any]) -> None:
        self._sessions.pop(state, None)
        self._results[state] = dict(payload)

    def result(self, state: str) -> dict[str, Any] | None:
        payload = self._results.get(state)
        return dict(payload) if payload is not None else None

    def clear(self, state: str) -> None:
        self._sessions.pop(state, None)
        self._results.pop(state, None)


class GitHubDeviceFlowClient:
    def __init__(self, client_id: str, timeout: float = 10.0) -> None:
        self._client_id = client_id
        self._timeout = timeout

    def start(self) -> dict[str, Any]:
        payload = _post_form(
            "https://github.com/login/device/code",
            {"client_id": self._client_id, "scope": "repo read:user"},
            self._timeout,
        )
        error = payload.get("error")
        if error is not None:
            return {
                "status": "failed",
                "provider": "github",
                "error": error,
                "error_description": payload.get("error_description", ""),
            }
        return {
            "status": "waiting_for_user",
            "provider": "github",
            "device_code": payload["device_code"],
            "user_code": payload["user_code"],
            "verification_uri": payload["verification_uri"],
            "expires_in": payload["expires_in"],
            "poll_after_seconds": payload.get("interval", 5),
        }

    def poll(self, device_code: str, current_interval: int | float = 5) -> dict[str, Any]:
        payload = _post_form(
            "https://github.com/login/oauth/access_token",
            {
                "client_id": self._client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            self._timeout,
        )

        error = payload.get("error")
        if error == "authorization_pending":
            return {
                "status": "waiting_for_user",
                "provider": "github",
                "error": error,
                "poll_after_seconds": current_interval,
            }
        if error == "slow_down":
            provider_interval = payload.get("interval")
            slowed_interval = current_interval + 5
            if isinstance(provider_interval, int | float):
                slowed_interval = max(slowed_interval, provider_interval)
            return {
                "status": "waiting_for_user",
                "provider": "github",
                "error": error,
                "poll_after_seconds": slowed_interval,
            }
        if error is not None:
            return {
                "status": "failed",
                "provider": "github",
                "error": error,
                "error_description": payload.get("error_description", ""),
            }

        return {
            "status": "authorized",
            "provider": "github",
            "token": _provider_token_from_payload(payload),
        }


class GiteaOAuthClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        redirect_uri: str,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._timeout = timeout

    def start(self) -> dict[str, Any]:
        state = token_urlsafe(32)
        code_verifier = new_code_verifier()
        code_challenge = build_pkce_challenge(code_verifier)
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": "read:user read:repository",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        session = {
            "provider": "gitea",
            "base_url": self._base_url,
            "client_id": self._client_id,
            "state": state,
            "code_verifier": code_verifier,
            "redirect_uri": self._redirect_uri,
        }
        return {
            "status": "redirect",
            "provider": "gitea",
            "authorization_url": f"{self._base_url}/login/oauth/authorize?{query}",
            "state": state,
            "session": session,
        }

    def exchange_code(self, code: str, code_verifier: str) -> ProviderToken:
        payload = _post_form(
            f"{self._base_url}/login/oauth/access_token",
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
            },
            self._timeout,
        )
        return _provider_token_from_payload(payload)


def _provider_token_from_payload(payload: dict[str, Any]) -> ProviderToken:
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("provider OAuth response requires access_token")
    token_type = payload.get("token_type", "bearer")
    scope = payload.get("scope", "")
    if not isinstance(token_type, str) or not isinstance(scope, str):
        raise ValueError("provider OAuth token_type and scope must be strings")
    return ProviderToken(access_token=access_token, token_type=token_type, scope=scope)
