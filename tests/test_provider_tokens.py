import json
import os
import stat
import sys
import importlib.util
from types import SimpleNamespace

import pytest

from whywiki.collaboration.models import ProviderIdentity
from whywiki.collaboration.tokens import (
    FileTokenStore,
    KeyringTokenStore,
    ProviderToken,
    TokenStoreUnavailable,
    default_token_store,
    token_store_key,
    xdg_token_path,
)


def test_github_identity_key_and_token_store_key_are_stable():
    identity = ProviderIdentity(provider="github", account="alice", provider_user_id="1")

    assert identity.identity_key == "github:1"
    assert token_store_key(identity) == ("whywiki", "github:1")


def test_gitea_identity_key_distinguishes_servers_and_normalizes_trailing_slash():
    first = ProviderIdentity(
        provider="gitea",
        account="alice",
        provider_user_id="1",
        base_url="https://git.one.test/",
    )
    second = ProviderIdentity(
        provider="gitea",
        account="alice",
        provider_user_id="1",
        base_url="https://git.two.test",
    )

    assert first.identity_key == "gitea:https://git.one.test:1"
    assert second.identity_key == "gitea:https://git.two.test:1"
    assert first.identity_key != second.identity_key


def test_file_token_store_round_trip_with_owner_only_permissions(tmp_path):
    path = tmp_path / "auth" / "tokens.json"
    identity = ProviderIdentity(provider="github", account="alice", provider_user_id="1")
    token = ProviderToken(access_token="secret-token", scope="repo read:user")
    store = FileTokenStore(path)

    store.save(identity, token)

    assert store.load(identity) == token
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "github:1": {
            "access_token": "secret-token",
            "scope": "repo read:user",
            "token_type": "bearer",
        }
    }
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    assert store.delete(identity)
    assert store.load(identity) is None
    assert json.loads(path.read_text(encoding="utf-8")) == {}


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable to this platform")
def test_file_token_store_replaces_permissive_existing_file_with_owner_only_permissions(tmp_path):
    path = tmp_path / "auth" / "tokens.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}\n", encoding="utf-8")
    path.chmod(0o644)
    identity = ProviderIdentity(provider="github", account="alice", provider_user_id="1")
    store = FileTokenStore(path)

    store.save(identity, ProviderToken(access_token="secret-token"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["github:1"]["access_token"] == "secret-token"


def test_keyring_token_store_reports_broken_backend_unavailable(monkeypatch, tmp_path):
    def broken_set_password(service, username, password):
        raise RuntimeError("backend unavailable")

    fake_keyring = SimpleNamespace(
        get_keyring=lambda: object(),
        set_password=broken_set_password,
        get_password=lambda service, username: (_ for _ in ()).throw(RuntimeError("backend unavailable")),
        delete_password=lambda service, username: None,
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    assert not KeyringTokenStore().available()
    store = default_token_store()

    assert isinstance(store, FileTokenStore)
    assert store.path == tmp_path / "xdg" / "whywiki" / "tokens.json"


def test_xdg_token_path_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert xdg_token_path() == tmp_path / "xdg" / "whywiki" / "tokens.json"


def test_xdg_token_path_defaults_to_home_local_share(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert xdg_token_path() == tmp_path / "home" / ".local" / "share" / "whywiki" / "tokens.json"


def test_default_token_store_uses_xdg_file_on_linux_when_keyring_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(KeyringTokenStore, "available", lambda self: False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    store = default_token_store()
    assert isinstance(store, FileTokenStore)
    assert store.path == tmp_path / "xdg" / "whywiki" / "tokens.json"


def test_default_token_store_raises_on_non_linux_when_keyring_unavailable(monkeypatch):
    monkeypatch.setattr(KeyringTokenStore, "available", lambda self: False)
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(TokenStoreUnavailable):
        default_token_store()


def test_default_token_store_reports_missing_keyring_package_on_non_linux(monkeypatch):
    monkeypatch.setattr(KeyringTokenStore, "available", lambda self: False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None if name == "keyring" else object())

    with pytest.raises(TokenStoreUnavailable) as exc_info:
        default_token_store()

    message = str(exc_info.value)
    assert "keyring Python package is not installed" in message
    assert "pip install -e ." in message
