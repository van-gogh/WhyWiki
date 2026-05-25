from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .config import get_db_path


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows}


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version(version) VALUES (0)")

    ensure_column(conn, "projects", "status", "TEXT DEFAULT 'active'")
    ensure_column(conn, "projects", "tags_json", "TEXT DEFAULT '[]'")
    ensure_column(conn, "sources", "version_hint", "TEXT DEFAULT ''")
    ensure_column(conn, "facts", "validity_status", "TEXT DEFAULT 'unknown'")
    ensure_column(conn, "conflicts", "conflict_key", "TEXT DEFAULT ''")

    conn.execute("UPDATE schema_version SET version = 4")


def init_db(conn: sqlite3.Connection | None = None) -> None:
    close = conn is None
    conn = conn or connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            path TEXT NOT NULL,
            title TEXT DEFAULT '',
            content_hash TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, path)
        );

        CREATE TABLE IF NOT EXISTS blocks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            block_type TEXT NOT NULL,
            text TEXT NOT NULL,
            location_json TEXT DEFAULT '{}',
            metadata_json TEXT DEFAULT '{}',
            content_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            fact_type TEXT NOT NULL,
            statement TEXT NOT NULL,
            evidence_json TEXT DEFAULT '[]',
            status TEXT DEFAULT 'candidate',
            confidence REAL DEFAULT 0.5,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conflicts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            conflict_key TEXT DEFAULT '',
            conflict_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            evidence_json TEXT DEFAULT '[]',
            severity TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wiki_pages (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, slug)
        );

        CREATE TABLE IF NOT EXISTS operation_jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            operation_type TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER DEFAULT 0,
            message TEXT DEFAULT '',
            result_json TEXT DEFAULT '{}',
            error TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id);
        CREATE INDEX IF NOT EXISTS idx_blocks_project ON blocks(project_id);
        CREATE INDEX IF NOT EXISTS idx_blocks_source ON blocks(source_id);
        CREATE INDEX IF NOT EXISTS idx_facts_project ON facts(project_id);
        CREATE INDEX IF NOT EXISTS idx_conflicts_project ON conflicts(project_id);
        CREATE INDEX IF NOT EXISTS idx_conflicts_project_key ON conflicts(project_id, conflict_key);
        CREATE INDEX IF NOT EXISTS idx_wiki_project ON wiki_pages(project_id);
        CREATE INDEX IF NOT EXISTS idx_operation_jobs_project ON operation_jobs(project_id);
        """
    )
    apply_migrations(conn)
    conn.commit()
    if close:
        conn.close()


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]
