import sqlite3

from whywiki.db import init_db


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def test_init_db_adds_schema_version_and_review_fields(tmp_path):
    db_path = tmp_path / "whywiki.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    init_db(conn)

    version = conn.execute("SELECT version FROM schema_version").fetchone()
    assert version["version"] >= 1
    assert {"status"}.issubset(columns(conn, "projects"))
    assert {"tags_json"}.issubset(columns(conn, "projects"))
    assert {"version_hint"}.issubset(columns(conn, "sources"))
    assert {"validity_status"}.issubset(columns(conn, "facts"))
    assert {"conflict_key"}.issubset(columns(conn, "conflicts"))
    assert {
        "id",
        "project_id",
        "operation_type",
        "status",
        "progress",
        "message",
        "result_json",
        "error",
        "created_at",
        "updated_at",
    }.issubset(columns(conn, "operation_jobs"))


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "whywiki.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    init_db(conn)
    init_db(conn)

    assert "validity_status" in columns(conn, "facts")
    assert "conflict_key" in columns(conn, "conflicts")
    assert "progress" in columns(conn, "operation_jobs")
