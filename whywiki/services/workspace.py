from __future__ import annotations

import sqlite3

from ..db import connect, init_db, rows_to_dicts
from ..utils import new_id, now_iso


def create_project(name: str, description: str = "", conn: sqlite3.Connection | None = None) -> dict:
    close = conn is None
    conn = conn or connect()
    init_db(conn)
    project_id = new_id("proj")
    now = now_iso()
    conn.execute(
        "INSERT INTO projects(id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, name, description, now, now),
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
    return rows_to_dicts(rows)


def get_project(project_id: str, conn: sqlite3.Connection | None = None) -> dict:
    close = conn is None
    conn = conn or connect()
    init_db(conn)
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if close:
        conn.close()
    if not row:
        raise ValueError(f"Project not found: {project_id}")
    return dict(row)


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
