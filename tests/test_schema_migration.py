import sqlite3

from whywiki.db import init_db


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


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


def test_init_db_adds_requirement_lifecycle_fields(tmp_path):
    db_path = tmp_path / "whywiki.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    init_db(conn)

    assert {"superseded_by_fact_id", "review_note", "updated_at"}.issubset(columns(conn, "facts"))
    assert {
        "id",
        "project_id",
        "conflict_id",
        "action",
        "accepted_fact_id",
        "created_fact_id",
        "superseded_fact_ids_json",
        "rejected_fact_ids_json",
        "reason",
        "evidence_json",
        "created_at",
    }.issubset(columns(conn, "requirement_decisions"))


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "whywiki.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    init_db(conn)
    init_db(conn)

    assert "validity_status" in columns(conn, "facts")
    assert "superseded_by_fact_id" in columns(conn, "facts")
    assert "conflict_key" in columns(conn, "conflicts")
    assert "progress" in columns(conn, "operation_jobs")
    assert "requirement_decisions" in table_names(conn)


def test_init_db_migrates_old_conflict_schema_before_creating_indexes(tmp_path):
    db_path = tmp_path / "whywiki.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE facts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            fact_type TEXT NOT NULL,
            statement TEXT NOT NULL,
            evidence_json TEXT DEFAULT '[]',
            status TEXT DEFAULT 'candidate',
            confidence REAL DEFAULT 0.5,
            created_at TEXT NOT NULL
        );

        CREATE TABLE conflicts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            conflict_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            evidence_json TEXT DEFAULT '[]',
            severity TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO projects (id, name, description, created_at, updated_at)
        VALUES ('project-1', 'Legacy project', '', '2026-05-01T00:00:00', '2026-05-01T00:00:00')
        """
    )
    conn.execute(
        """
        INSERT INTO facts (id, project_id, fact_type, statement, created_at)
        VALUES ('fact-1', 'project-1', 'requirement', 'Legacy requirement', '2026-05-02T00:00:00')
        """
    )
    conn.commit()

    init_db(conn)
    init_db(conn)

    assert "conflict_key" in columns(conn, "conflicts")
    assert {"superseded_by_fact_id", "review_note", "updated_at"}.issubset(columns(conn, "facts"))
    assert "requirement_decisions" in table_names(conn)
    fact = conn.execute("SELECT created_at, updated_at FROM facts WHERE id = 'fact-1'").fetchone()
    assert fact["updated_at"] == fact["created_at"]
