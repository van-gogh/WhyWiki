import sqlite3

from whywiki.db import init_db
from whywiki.services.requirement_lifecycle import build_requirement_snapshot
from whywiki.utils import now_iso, to_json


def insert_project(conn: sqlite3.Connection, project_id: str = "proj_1") -> str:
    conn.execute(
        "INSERT INTO projects(id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (project_id, "Lifecycle Project", "", now_iso(), now_iso()),
    )
    return project_id


def insert_source(conn: sqlite3.Connection, project_id: str, source_id: str, path: str) -> None:
    conn.execute(
        """
        INSERT INTO sources(id, project_id, source_type, path, title, content_hash, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (source_id, project_id, "local", path, path, f"hash-{source_id}", "{}", now_iso(), now_iso()),
    )


def insert_requirement(
    conn: sqlite3.Connection,
    project_id: str,
    fact_id: str,
    statement: str,
    source_id: str,
    path: str,
    status: str = "candidate",
    validity_status: str = "unknown",
    superseded_by_fact_id: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO facts(
            id, project_id, fact_type, statement, evidence_json, status, confidence,
            created_at, validity_status, superseded_by_fact_id, review_note, updated_at
        )
        VALUES (?, ?, 'requirement', ?, ?, ?, 0.9, ?, ?, ?, '', ?)
        """,
        (
            fact_id,
            project_id,
            statement,
            to_json([{"source_id": source_id, "path": path}]),
            status,
            now_iso(),
            validity_status,
            superseded_by_fact_id,
            now_iso(),
        ),
    )


def test_snapshot_groups_current_review_and_superseded_requirements(tmp_path):
    conn = sqlite3.connect(tmp_path / "whywiki.db")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    project_id = insert_project(conn)
    insert_source(conn, project_id, "src_new", "docs/requirements_v2.md")
    insert_source(conn, project_id, "src_old", "docs/requirements_v1.md")
    insert_requirement(
        conn, project_id, "fact_current", "支持离线缓存", "src_new", "docs/requirements_v2.md", "confirmed", "current"
    )
    insert_requirement(
        conn,
        project_id,
        "fact_old",
        "不做离线缓存",
        "src_old",
        "docs/requirements_v1.md",
        "confirmed",
        "superseded",
        "fact_current",
    )
    insert_requirement(
        conn, project_id, "fact_review", "需要确认预算限制", "src_new", "docs/requirements_v2.md", "needs_review", "unknown"
    )

    snapshot = build_requirement_snapshot(project_id, conn)

    assert [item["id"] for item in snapshot["current"]] == ["fact_current"]
    assert [item["id"] for item in snapshot["needs_review"]] == ["fact_review"]
    assert [item["id"] for item in snapshot["superseded"]] == ["fact_old"]
    assert snapshot["superseded"][0]["superseded_by_fact_id"] == "fact_current"
    assert snapshot["current"][0]["lifecycle_label"] == "当前有效"
    assert snapshot["needs_review"][0]["evidence"] == [{"source_id": "src_new", "path": "docs/requirements_v2.md"}]
    assert snapshot["source_statuses"]["src_old"]["status"] == "outdated"
    assert snapshot["source_statuses"]["src_new"]["status"] == "active"


def test_snapshot_includes_recent_decisions_and_open_conflicts(tmp_path):
    conn = sqlite3.connect(tmp_path / "whywiki.db")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    project_id = insert_project(conn)
    insert_source(conn, project_id, "src_1", "docs/requirements.md")
    insert_requirement(conn, project_id, "fact_conflict", "缓存策略冲突", "src_1", "docs/requirements.md", "confirmed", "conflicting")
    conn.execute(
        """
        INSERT INTO requirement_decisions(
            id, project_id, conflict_id, action, accepted_fact_id, created_fact_id,
            superseded_fact_ids_json, rejected_fact_ids_json, reason, evidence_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "decision_1",
            project_id,
            "conflict_1",
            "accept_fact",
            "fact_conflict",
            "",
            "[]",
            "[]",
            "当前版本先保留",
            "[]",
            now_iso(),
        ),
    )
    conn.execute(
        """
        INSERT INTO conflicts(
            id, project_id, conflict_key, conflict_type, title, description,
            evidence_json, severity, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "conflict_1",
            project_id,
            "requirement:cache",
            "requirement",
            "缓存策略冲突",
            "两份需求不一致",
            to_json([{"fact_id": "fact_conflict"}]),
            "high",
            "open",
            now_iso(),
        ),
    )

    snapshot = build_requirement_snapshot(project_id, conn, language="en-US")

    assert [item["id"] for item in snapshot["conflicting"]] == ["fact_conflict"]
    assert snapshot["conflicting"][0]["lifecycle_label"] == "Conflicting"
    assert snapshot["source_statuses"]["src_1"]["status"] == "conflicting"
    assert snapshot["decisions"][0]["id"] == "decision_1"
    assert snapshot["decisions"][0]["action_label"] == "Accept as current"
    assert snapshot["decisions"][0]["superseded_fact_ids"] == []
    assert snapshot["open_conflicts"][0]["id"] == "conflict_1"
    assert snapshot["open_conflicts"][0]["evidence"] == [{"fact_id": "fact_conflict"}]
    assert snapshot["metrics"] == {
        "current": 0,
        "needs_review": 0,
        "superseded": 0,
        "historical": 0,
        "rejected": 0,
        "conflicting": 1,
        "decisions": 1,
        "open_conflicts": 1,
        "sources": 1,
    }
