from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from ..connectors.git_repo import GitRepoConnector
from ..connectors.local_files import LocalFilesConnector, SUPPORTED_EXTENSIONS
from ..db import connect, init_db
from ..parsers import parse_file
from ..utils import new_id, now_iso, sha256_file, sha256_text, to_json


WINDOWS_DRIVE_PATH_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def supported_extensions_label() -> str:
    return ", ".join(sorted(SUPPORTED_EXTENSIONS))


def wsl_path_hint(path_str: str) -> str | None:
    match = WINDOWS_DRIVE_PATH_RE.match(path_str.strip())
    if not match:
        return None
    drive, remainder = match.groups()
    remainder = remainder.replace("\\", "/").lstrip("/")
    return f"/mnt/{drive.lower()}/{remainder}" if remainder else f"/mnt/{drive.lower()}"


def missing_local_path_message(path_str: str, root: Path) -> str:
    base = f"Local source path does not exist: {root}. "
    if os.name != "nt":
        hint = wsl_path_hint(path_str)
        if hint:
            return (
                base
                + "This WhyWiki server is running on POSIX, so Windows-style paths are not directly readable. "
                + f"If this folder is on the same machine through WSL, try {hint}. "
                + "Otherwise enter an absolute folder path that the WhyWiki server can read."
            )
    return base + "Enter an absolute folder path that the WhyWiki server can read."


def validate_local_input_path(path_str: str, source_type: str) -> None:
    if source_type == "git":
        return
    root = Path(path_str).expanduser()
    if not root.exists():
        raise ValueError(missing_local_path_message(path_str, root))


def ingest_path(project_id: str, path: str | Path, source_type: str = "local", conn: sqlite3.Connection | None = None) -> dict:
    """Ingest a local directory/file or git repository into source blocks."""
    close = conn is None
    conn = conn or connect()
    init_db(conn)

    path_str = str(path)
    validate_local_input_path(path_str, source_type)
    connector = GitRepoConnector(path_str) if source_type == "git" else LocalFilesConnector(path_str)
    files = connector.list_files()
    if not files:
        raise ValueError(
            f"No supported files found in source path: {path_str}. "
            f"Choose a folder containing project files such as {supported_extensions_label()}."
        )

    created_sources = 0
    created_blocks = 0
    skipped_files = 0
    errors: list[dict] = []

    for file_path in files:
        try:
            content_hash = sha256_file(file_path)
            existing = conn.execute(
                "SELECT id, content_hash FROM sources WHERE project_id = ? AND path = ?",
                (project_id, str(file_path)),
            ).fetchone()
            if existing and existing["content_hash"] == content_hash:
                skipped_files += 1
                continue
            source_id = existing["id"] if existing else new_id("src")
            now = now_iso()
            if existing:
                conn.execute(
                    "UPDATE sources SET source_type = ?, title = ?, content_hash = ?, updated_at = ? WHERE id = ?",
                    (source_type, file_path.name, content_hash, now, source_id),
                )
                conn.execute("DELETE FROM blocks WHERE source_id = ?", (source_id,))
            else:
                conn.execute(
                    """
                    INSERT INTO sources(id, project_id, source_type, path, title, content_hash, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (source_id, project_id, source_type, str(file_path), file_path.name, content_hash, to_json({}), now, now),
                )
                created_sources += 1

            blocks = parse_file(file_path)
            for block in blocks:
                if not block.text.strip():
                    continue
                block_id = new_id("blk")
                conn.execute(
                    """
                    INSERT INTO blocks(id, project_id, source_id, block_type, text, location_json, metadata_json, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        block_id,
                        project_id,
                        source_id,
                        block.block_type,
                        block.text,
                        to_json(block.location),
                        to_json(block.metadata),
                        sha256_text(block.text),
                    ),
                )
                created_blocks += 1
        except Exception as exc:
            errors.append({"path": str(file_path), "error": str(exc)})

    conn.commit()
    result = {
        "project_id": project_id,
        "input": path_str,
        "source_type": source_type,
        "files_seen": len(files),
        "created_sources": created_sources,
        "created_blocks": created_blocks,
        "skipped_files": skipped_files,
        "errors": errors,
    }
    if close:
        conn.close()
    return result
