from __future__ import annotations

import json
import os
import sys
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .jsonio import read_json
from .models import ProviderIdentity

_KEYRING_SERVICE = "whywiki"
_KEYRING_PROBE_USER = "__whywiki_keyring_probe__"
_KEYRING_PROBE_VALUE = "probe"


class TokenStoreUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderToken:
    access_token: str
    token_type: str = "bearer"
    scope: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "token_type": self.token_type,
                "scope": self.scope,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, value: str) -> ProviderToken:
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise ValueError("provider token must be a JSON object")
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("provider token requires access_token")
        token_type = payload.get("token_type", "bearer")
        scope = payload.get("scope", "")
        if not isinstance(token_type, str) or not isinstance(scope, str):
            raise ValueError("provider token token_type and scope must be strings")
        return cls(access_token=access_token, token_type=token_type, scope=scope)


class TokenStore(Protocol):
    def save(self, identity: ProviderIdentity, token: ProviderToken) -> None:
        ...

    def load(self, identity: ProviderIdentity) -> ProviderToken | None:
        ...

    def delete(self, identity: ProviderIdentity) -> bool:
        ...


def token_store_key(identity: ProviderIdentity) -> tuple[str, str]:
    return (_KEYRING_SERVICE, identity.identity_key)


class KeyringTokenStore:
    def available(self) -> bool:
        keyring: Any | None = None
        try:
            import keyring

            keyring.get_keyring()
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_PROBE_USER, _KEYRING_PROBE_VALUE)
            available = keyring.get_password(_KEYRING_SERVICE, _KEYRING_PROBE_USER) == _KEYRING_PROBE_VALUE
            keyring.delete_password(_KEYRING_SERVICE, _KEYRING_PROBE_USER)
            return available
        except Exception:
            if keyring is not None:
                try:
                    keyring.delete_password(_KEYRING_SERVICE, _KEYRING_PROBE_USER)
                except Exception:
                    pass
            return False

    def save(self, identity: ProviderIdentity, token: ProviderToken) -> None:
        keyring = _import_keyring()
        service, username = token_store_key(identity)
        keyring.set_password(service, username, token.to_json())

    def load(self, identity: ProviderIdentity) -> ProviderToken | None:
        keyring = _import_keyring()
        service, username = token_store_key(identity)
        value = keyring.get_password(service, username)
        if value is None:
            return None
        return ProviderToken.from_json(value)

    def delete(self, identity: ProviderIdentity) -> bool:
        keyring = _import_keyring()
        service, username = token_store_key(identity)
        if keyring.get_password(service, username) is None:
            return False
        keyring.delete_password(service, username)
        return True


class FileTokenStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, identity: ProviderIdentity, token: ProviderToken) -> None:
        payload = self._read()
        payload[identity.identity_key] = json.loads(token.to_json())
        self._write(payload)

    def load(self, identity: ProviderIdentity) -> ProviderToken | None:
        payload = self._read()
        value = payload.get(identity.identity_key)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("stored provider token must be a JSON object")
        return ProviderToken.from_json(json.dumps(value, ensure_ascii=False))

    def delete(self, identity: ProviderIdentity) -> bool:
        payload = self._read()
        if identity.identity_key not in payload:
            return False
        del payload[identity.identity_key]
        self._write(payload)
        return True

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        payload = read_json(self.path)
        if not isinstance(payload, dict):
            raise ValueError("file token store must contain a JSON object")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            self._write_posix(content)
            return

        self.path.write_text(content, encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            return

    def _write_posix(self, content: str) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        file_descriptor: int | None = None
        temporary_path: Path | None = None
        try:
            for candidate in self._temporary_paths():
                temporary_path = candidate
                try:
                    file_descriptor = os.open(temporary_path, flags, 0o600)
                    break
                except FileExistsError:
                    continue
            if file_descriptor is None:
                raise TokenStoreUnavailable("could not create a secure temporary token file")

            with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
                file_descriptor = None
                file.write(content)
            temporary_path.replace(self.path)
            if stat_mode := self.path.stat().st_mode & 0o077:
                raise PermissionError(
                    f"file token store permissions must not allow group/other access: {oct(stat_mode)}"
                )
        except Exception:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
            if file_descriptor is not None:
                os.close(file_descriptor)
            raise

    def _temporary_paths(self) -> list[Path]:
        paths: list[Path] = []
        for index in range(100):
            paths.append(self.path.with_name(f".{self.path.name}.{os.getpid()}.{index}.tmp"))
        return paths


def xdg_token_path() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        base = Path(xdg_data_home)
    else:
        base = Path.home() / ".local" / "share"
    return base / "whywiki" / "tokens.json"


def default_token_store() -> TokenStore:
    keyring_store = KeyringTokenStore()
    if keyring_store.available():
        return keyring_store
    if sys.platform == "linux":
        return FileTokenStore(xdg_token_path())
    if importlib.util.find_spec("keyring") is None:
        raise TokenStoreUnavailable(
            "keyring Python package is not installed. "
            "Run pip install -e . from the WhyWiki checkout, then restart whywiki serve."
        )
    raise TokenStoreUnavailable(
        "OS credential storage is unavailable. Unlock or configure your system credential store, then retry."
    )


def _import_keyring() -> Any:
    try:
        import keyring
    except Exception as exc:
        raise TokenStoreUnavailable("keyring is unavailable") from exc
    return keyring
