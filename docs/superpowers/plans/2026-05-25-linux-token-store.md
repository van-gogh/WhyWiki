# Linux Token Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OAuth token storage work out of the box on Linux by using XDG-compliant file storage with strict permissions when keyring is unavailable.

**Architecture:** Platform-aware `default_token_store()` tries keyring first; on Linux, auto-falls back to `FileTokenStore` at `$XDG_DATA_HOME/whywiki/tokens.json` (default `~/.local/share/whywiki/tokens.json`). The `WHYWIKI_ALLOW_FILE_TOKEN_STORE` env var and `FileTokenStore.from_env()` are removed entirely.

**Tech Stack:** Python 3.10+, pytest, FastAPI

---

### Task 1: Add `xdg_token_path()` and update `default_token_store()`

**Files:**
- Modify: `whywiki/collaboration/tokens.py`
- Test: `tests/test_provider_tokens.py`

- [ ] **Step 1: Write failing test for `xdg_token_path`**

```python
def test_xdg_token_path_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    from whywiki.collaboration.tokens import xdg_token_path

    assert xdg_token_path() == tmp_path / "xdg" / "whywiki" / "tokens.json"


def test_xdg_token_path_defaults_to_home_local_share(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    from whywiki.collaboration.tokens import xdg_token_path

    assert xdg_token_path() == tmp_path / "home" / ".local" / "share" / "whywiki" / "tokens.json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_provider_tokens.py::test_xdg_token_path_uses_xdg_data_home tests/test_provider_tokens.py::test_xdg_token_path_defaults_to_home_local_share -v`
Expected: FAIL with ImportError (function doesn't exist yet)

- [ ] **Step 3: Implement `xdg_token_path()`**

In `whywiki/collaboration/tokens.py`, add after the existing imports:

```python
import sys
```

Add the function before `default_token_store()`:

```python
def xdg_token_path() -> Path:
    """Return the XDG-compliant token file path for Linux."""
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    if not base:
        base = str(Path.home() / ".local" / "share")
    return Path(base) / "whywiki" / "tokens.json"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_provider_tokens.py::test_xdg_token_path_uses_xdg_data_home tests/test_provider_tokens.py::test_xdg_token_path_defaults_to_home_local_share -v`
Expected: PASS

- [ ] **Step 5: Write failing test for Linux auto-fallback in `default_token_store`**

Replace `test_default_token_store_uses_file_fallback_when_keyring_unavailable` with:

```python
def test_default_token_store_uses_xdg_file_on_linux_when_keyring_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(KeyringTokenStore, "available", lambda self: False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    store = default_token_store()

    assert isinstance(store, FileTokenStore)
    assert store.path == tmp_path / "xdg" / "whywiki" / "tokens.json"


def test_default_token_store_raises_on_non_linux_when_keyring_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(KeyringTokenStore, "available", lambda self: False)
    monkeypatch.setattr(sys, "platform", "darwin")

    with pytest.raises(TokenStoreUnavailable):
        default_token_store()
```

- [ ] **Step 6: Implement updated `default_token_store()`**

Replace the existing `default_token_store()` in `whywiki/collaboration/tokens.py`:

```python
def default_token_store() -> TokenStore:
    keyring_store = KeyringTokenStore()
    if keyring_store.available():
        return keyring_store
    if sys.platform == "linux":
        return FileTokenStore(xdg_token_path())
    raise TokenStoreUnavailable(
        "No secure token storage available. Install and configure a keyring backend."
    )
```

- [ ] **Step 7: Remove `FileTokenStore.from_env()`**

Delete the `from_env` classmethod from `FileTokenStore`:

```python
    @classmethod
    def from_env(cls, path: Path) -> FileTokenStore:
        if os.getenv("WHYWIKI_ALLOW_FILE_TOKEN_STORE") != "1":
            raise TokenStoreUnavailable("set WHYWIKI_ALLOW_FILE_TOKEN_STORE=1 to use file token storage")
        return cls(path)
```

- [ ] **Step 8: Run all token tests**

Run: `python -m pytest tests/test_provider_tokens.py -v`
Expected: PASS (some old tests will need updating in Task 2)

- [ ] **Step 9: Commit**

```bash
git add whywiki/collaboration/tokens.py tests/test_provider_tokens.py
git commit -m "feat: platform-aware token store with XDG fallback on Linux"
```

---

### Task 2: Update token store tests

**Files:**
- Modify: `tests/test_provider_tokens.py`

- [ ] **Step 1: Remove the `from_env` gate test**

Delete `test_file_token_store_from_env_requires_explicit_fallback` entirely.

- [ ] **Step 2: Update `test_file_token_store_round_trip_with_owner_only_permissions`**

Replace `FileTokenStore.from_env(path)` with `FileTokenStore(path)` and remove the `monkeypatch.setenv("WHYWIKI_ALLOW_FILE_TOKEN_STORE", "1")` line:

```python
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
```

- [ ] **Step 3: Update `test_file_token_store_replaces_permissive_existing_file_with_owner_only_permissions`**

```python
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
```

- [ ] **Step 4: Update `test_keyring_token_store_reports_broken_backend_unavailable`**

```python
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
```

- [ ] **Step 5: Remove unused import of `TokenStoreUnavailable` if no longer needed in tests**

Check if `TokenStoreUnavailable` is still used. It is — in the new `test_default_token_store_raises_on_non_linux_when_keyring_unavailable`. Keep it.

- [ ] **Step 6: Run all token tests**

Run: `python -m pytest tests/test_provider_tokens.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_provider_tokens.py
git commit -m "test: update token store tests for Linux XDG fallback"
```

---

### Task 3: Update `app.py` error messages

**Files:**
- Modify: `whywiki/app.py`

- [ ] **Step 1: Update `require_token_store()` error message**

Change line 88 from:
```python
detail=f"Token storage is unavailable: {exc}. Enable keyring or set WHYWIKI_ALLOW_FILE_TOKEN_STORE=1.",
```
To:
```python
detail=f"Token storage is unavailable: {exc}. Install and configure a keyring backend.",
```

- [ ] **Step 2: Update `provider_registry()` error message**

Change lines 116-117 from:
```python
detail=(
    f"Token storage is unavailable for connected provider accounts: {exc}. "
    "Enable keyring or set WHYWIKI_ALLOW_FILE_TOKEN_STORE=1."
),
```
To:
```python
detail=(
    f"Token storage is unavailable for connected provider accounts: {exc}. "
    "Install and configure a keyring backend."
),
```

- [ ] **Step 3: Run compile check**

Run: `python -m compileall whywiki`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add whywiki/app.py
git commit -m "fix: remove WHYWIKI_ALLOW_FILE_TOKEN_STORE from error messages"
```

---

### Task 4: Update auth API tests

**Files:**
- Modify: `tests/test_auth_api.py`
- Modify: `tests/test_collaboration_api.py`

- [ ] **Step 1: Update `test_auth_api.py` fixture**

In `isolate_auth_api_env`, remove the line:
```python
monkeypatch.delenv("WHYWIKI_ALLOW_FILE_TOKEN_STORE", raising=False)
```

Add Linux platform mock so `default_token_store()` works without keyring:
```python
monkeypatch.setattr(sys, "platform", "linux")
```

Add `import sys` at the top of the file if not already present.

- [ ] **Step 2: Update `_token_store()` helper in `test_auth_api.py`**

Change from:
```python
def _token_store(tmp_path):
    return FileTokenStore.from_env(tmp_path / "data" / "auth" / "tokens.json")
```
To:
```python
def _token_store(tmp_path):
    return FileTokenStore(tmp_path / "data" / "auth" / "tokens.json")
```

- [ ] **Step 3: Remove all `monkeypatch.setenv("WHYWIKI_ALLOW_FILE_TOKEN_STORE", "1")` lines in `test_auth_api.py`**

These appear at lines 92, 161, 272, 336, 369. Remove each one.

- [ ] **Step 4: Update `test_collaboration_api.py` fixture**

In `isolate_provider_auth_env`, remove:
```python
monkeypatch.delenv("WHYWIKI_ALLOW_FILE_TOKEN_STORE", raising=False)
```

Add:
```python
monkeypatch.setattr(sys, "platform", "linux")
monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
```

Note: the fixture needs `tmp_path` added as a parameter if not already present.

- [ ] **Step 5: Remove `monkeypatch.setenv("WHYWIKI_ALLOW_FILE_TOKEN_STORE", "1")` in `test_collaboration_api.py`**

This appears at line 108. Remove it.

- [ ] **Step 6: Run all auth and collaboration tests**

Run: `python -m pytest tests/test_auth_api.py tests/test_collaboration_api.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_auth_api.py tests/test_collaboration_api.py
git commit -m "test: remove WHYWIKI_ALLOW_FILE_TOKEN_STORE from auth tests"
```

---

### Task 5: Update documentation

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `README.md` token storage section**

Replace lines 140-142:
```markdown
- If no OS credential backend is available, WhyWiki fails clearly. For local
  development only, set `WHYWIKI_ALLOW_FILE_TOKEN_STORE=1` to use
  `.whywiki/auth/tokens.json`.
```
With:
```markdown
- On Linux without a desktop credential service, tokens are stored automatically
  in `$XDG_DATA_HOME/whywiki/tokens.json` (default `~/.local/share/whywiki/tokens.json`)
  with strict file permissions (0600).
```

- [ ] **Step 2: Update `README.zh-CN.md` token storage section**

Replace line 126:
```markdown
- 如果没有可用的操作系统凭据后端，WhyWiki 会清楚地失败。仅本地开发时，可以设置 `WHYWIKI_ALLOW_FILE_TOKEN_STORE=1`，使用 `.whywiki/auth/tokens.json`。
```
With:
```markdown
- 在没有桌面凭据服务的 Linux 上，token 会自动存储在 `$XDG_DATA_HOME/whywiki/tokens.json`（默认 `~/.local/share/whywiki/tokens.json`），文件权限为 0600。
```

- [ ] **Step 3: Update `CLAUDE.md` environment variables section**

Remove the line:
```markdown
- `WHYWIKI_ALLOW_FILE_TOKEN_STORE=1` — dev-only fallback when no OS credential store
```

- [ ] **Step 4: Commit**

```bash
git add README.md README.zh-CN.md CLAUDE.md
git commit -m "docs: update token storage docs for Linux XDG support"
```

---

### Task 6: Full verification

- [ ] **Step 1: Compile check**

Run: `python -m compileall whywiki`
Expected: No errors

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest -q`
Expected: All tests pass

- [ ] **Step 3: Verify no remaining references to the removed env var in source code**

Run: `grep -rn "WHYWIKI_ALLOW_FILE_TOKEN_STORE" whywiki/ tests/`
Expected: No output (zero matches)

- [ ] **Step 4: Manual smoke test (optional)**

```bash
unset WHYWIKI_ALLOW_FILE_TOKEN_STORE
export WHYWIKI_GITHUB_CLIENT_ID="test"
./start.sh
# Verify the server starts without token store errors
```
