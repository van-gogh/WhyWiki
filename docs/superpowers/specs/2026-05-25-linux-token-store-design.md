# Linux Token Store Design

Date: 2026-05-25

## Problem

WhyWiki uses `keyring` for OAuth token storage. On Linux without a desktop environment (WSL2, headless servers), keyring has no backend available. The current fallback requires manually setting `WHYWIKI_ALLOW_FILE_TOKEN_STORE=1` and stores tokens in the project data directory with insufficient security guarantees. This makes GitHub/Gitea login broken out of the box on Linux.

## Design

### Token Store Selection Logic

Platform-aware automatic selection, zero configuration required:

1. Try `KeyringTokenStore` (probes by writing/reading/deleting a test entry)
2. If keyring is available → use it (covers macOS Keychain, Windows Credential Manager, Linux Secret Service)
3. If keyring is unavailable:
   - **Linux:** automatically use `XdgFileTokenStore` at the XDG data path
   - **macOS/Windows:** raise `TokenStoreUnavailable` with actionable error guiding user to fix keyring

### XDG Path Resolution

Token file location on Linux:

- `$XDG_DATA_HOME/whywiki/tokens.json` if `XDG_DATA_HOME` is set
- `~/.local/share/whywiki/tokens.json` otherwise

Tokens are stored per-user, shared across all WhyWiki projects. The directory is created automatically if it does not exist.

### File Security

- File created with permission mode `0600` (owner read/write only)
- Atomic writes: write to a temporary file, then rename to target path. Prevents corruption from interrupted writes.
- Permission verification on read: if the file has group or other access bits set, refuse to load and raise an error with guidance to fix permissions.

### Removals

The following are removed entirely:

- `WHYWIKI_ALLOW_FILE_TOKEN_STORE` environment variable
- `FileTokenStore.from_env()` class method
- Token storage at `.whywiki/auth/tokens.json` (old project-local path)

### User Impact

- Users who previously authenticated via the old file token store must re-authenticate (OAuth flow again)
- Linux users get working OAuth login without any environment variable configuration
- macOS/Windows users see no behavior change (keyring continues to work)

## Components Changed

- `whywiki/collaboration/tokens.py` — add `xdg_token_path()` function, update `default_token_store()` with platform detection, remove `FileTokenStore.from_env()`. Reuse existing `FileTokenStore` (already has 0600 atomic writes and permission checks) with the XDG path.
- `whywiki/app.py` — remove references to `WHYWIKI_ALLOW_FILE_TOKEN_STORE` in error messages
- `.env.example` — remove `WHYWIKI_ALLOW_FILE_TOKEN_STORE` documentation
- `README.md` / `README.zh-CN.md` — update token storage documentation
- Tests — update token store tests to cover Linux auto-fallback behavior
