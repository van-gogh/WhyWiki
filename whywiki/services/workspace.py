from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from ..db import connect, init_db
from ..utils import from_json, new_id, now_iso, to_json


def normalize_project_tags(tags: Iterable[str] | None = None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags or []:
        value = " ".join(str(tag).strip().lower().split())
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def project_payload(row: sqlite3.Row | dict) -> dict:
    project = dict(row)
    project["tags"] = normalize_project_tags(from_json(project.pop("tags_json", "[]"), []))
    return project


def create_project(
    name: str,
    description: str = "",
    tags: Iterable[str] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict:
    close = conn is None
    conn = conn or connect()
    init_db(conn)
    project_id = new_id("proj")
    now = now_iso()
    normalized_tags = normalize_project_tags(tags)
    conn.execute(
        """
        INSERT INTO projects(id, name, description, tags_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, name, description, to_json(normalized_tags), now, now),
    )
    conn.commit()
    project = get_project(project_id, conn)
    if close:
        conn.close()
    return project


def list_projects(conn: sqlite3.Connection | None = None) -> list[dict]:
    close = conn is None
    conn = conn or connect()
    init_db(conn)
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    if close:
        conn.close()
    return [project_payload(row) for row in rows]


def get_project(project_id: str, conn: sqlite3.Connection | None = None) -> dict:
    close = conn is None
    conn = conn or connect()
    init_db(conn)
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if close:
        conn.close()
    if not row:
        raise ValueError(f"Project not found: {project_id}")
    return project_payload(row)


def update_project_tags(
    project_id: str,
    tags: Iterable[str] | None,
    conn: sqlite3.Connection | None = None,
) -> dict:
    close = conn is None
    conn = conn or connect()
    init_db(conn)
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        if close:
            conn.close()
        raise ValueError(f"Project not found: {project_id}")
    now = now_iso()
    conn.execute(
        "UPDATE projects SET tags_json = ?, updated_at = ? WHERE id = ?",
        (to_json(normalize_project_tags(tags)), now, project_id),
    )
    conn.commit()
    project = get_project(project_id, conn)
    if close:
        conn.close()
    return project


def delete_project(project_id: str, conn: sqlite3.Connection | None = None) -> bool:
    close = conn is None
    conn = conn or connect()
    init_db(conn)
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        if close:
            conn.close()
        raise ValueError(f"Project not found: {project_id}")
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    if close:
        conn.close()
    return True
