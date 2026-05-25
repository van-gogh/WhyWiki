import sqlite3

import pytest

from whywiki.db import init_db
from whywiki.services.requirement_lifecycle import build_requirement_snapshot, record_requirement_decision
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


def insert_requirement_conflict(conn: sqlite3.Connection, project_id: str, conflict_id: str = "conf_1") -> None:
    conn.execute(
        """
        INSERT INTO conflicts(
            id, project_id, conflict_key, conflict_type, title, description,
            evidence_json, severity, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conflict_id,
            project_id,
            "requirement:cache",
            "requirement",
            "缓存策略冲突",
            "两份需求不一致",
            to_json([{"fact_id": "fact_old"}, {"fact_id": "fact_new"}]),
            "high",
            "open",
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
    insert_requirement(
        conn, project_id, "fact_candidate", "评估批量导入能力", "src_new", "docs/requirements_v2.md", "candidate", "unknown"
    )

    snapshot = build_requirement_snapshot(project_id, conn)
    needs_review_by_id = {item["id"]: item for item in snapshot["needs_review"]}

    assert [item["id"] for item in snapshot["current"]] == ["fact_current"]
    assert set(needs_review_by_id) == {"fact_review", "fact_candidate"}
    candidate_item = needs_review_by_id["fact_candidate"]
    assert candidate_item["lifecycle_status"] == "candidate"
    assert candidate_item["lifecycle_label"] == "候选需求"
    assert [item["id"] for item in snapshot["superseded"]] == ["fact_old"]
    assert snapshot["superseded"][0]["superseded_by_fact_id"] == "fact_current"
    assert snapshot["current"][0]["lifecycle_label"] == "当前有效"
    assert needs_review_by_id["fact_review"]["evidence"] == [{"source_id": "src_new", "path": "docs/requirements_v2.md"}]
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


def test_accept_fact_decision_marks_winner_current_and_old_fact_superseded(tmp_path):
    conn = sqlite3.connect(tmp_path / "whywiki.db")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    project_id = insert_project(conn)
    insert_source(conn, project_id, "src_new", "docs/requirements_v2.md")
    insert_source(conn, project_id, "src_old", "docs/requirements_v1.md")
    insert_requirement(conn, project_id, "fact_new", "支持离线缓存", "src_new", "docs/requirements_v2.md")
    insert_requirement(conn, project_id, "fact_old", "不做离线缓存", "src_old", "docs/requirements_v1.md")
    insert_requirement_conflict(conn, project_id, "conf_1")
    conn.commit()

    decision = record_requirement_decision(
        project_id,
        conflict_id="conf_1",
        action="accept_fact",
        accepted_fact_id="fact_new",
        superseded_fact_ids=["fact_old"],
        rejected_fact_ids=[],
        created_statement="",
        reason="新版方案覆盖旧版需求",
        conn=conn,
    )

    winner = conn.execute("SELECT * FROM facts WHERE project_id = ? AND id = ?", (project_id, "fact_new")).fetchone()
    old = conn.execute("SELECT * FROM facts WHERE project_id = ? AND id = ?", (project_id, "fact_old")).fetchone()
    conflict = conn.execute("SELECT * FROM conflicts WHERE project_id = ? AND id = ?", (project_id, "conf_1")).fetchone()

    assert winner["status"] == "confirmed"
    assert winner["validity_status"] == "current"
    assert old["validity_status"] == "superseded"
    assert old["superseded_by_fact_id"] == "fact_new"
    assert conflict["status"] == "resolved"
    assert decision["action"] == "accept_fact"


def test_accept_fact_decision_marks_rejected_fact_historical(tmp_path):
    conn = sqlite3.connect(tmp_path / "whywiki.db")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    project_id = insert_project(conn)
    insert_source(conn, project_id, "src_new", "docs/requirements_v2.md")
    insert_source(conn, project_id, "src_old", "docs/requirements_v1.md")
    insert_source(conn, project_id, "src_rejected", "docs/requirements_draft.md")
    insert_requirement(conn, project_id, "fact_new", "支持离线缓存", "src_new", "docs/requirements_v2.md")
    insert_requirement(conn, project_id, "fact_old", "不做离线缓存", "src_old", "docs/requirements_v1.md")
    insert_requirement(conn, project_id, "fact_rejected", "离线缓存只支持草稿", "src_rejected", "docs/requirements_draft.md")
    insert_requirement_conflict(conn, project_id, "conf_1")
    conn.commit()

    decision = record_requirement_decision(
        project_id,
        conflict_id="conf_1",
        action="accept_fact",
        accepted_fact_id="fact_new",
        superseded_fact_ids=["fact_old"],
        rejected_fact_ids=["fact_rejected"],
        reason="新版方案覆盖旧版需求",
        conn=conn,
    )

    rejected = conn.execute("SELECT * FROM facts WHERE project_id = ? AND id = ?", (project_id, "fact_rejected")).fetchone()
    snapshot = build_requirement_snapshot(project_id, conn)

    assert rejected["status"] == "rejected"
    assert rejected["validity_status"] == "historical"
    assert rejected["superseded_by_fact_id"] == ""
    assert rejected["review_note"] == "新版方案覆盖旧版需求"
    assert decision["rejected_fact_ids_json"] == '["fact_rejected"]'
    assert [item["id"] for item in snapshot["historical"]] == ["fact_rejected"]


def test_merge_requirement_rejects_rejected_facts_without_superseding_them(tmp_path):
    conn = sqlite3.connect(tmp_path / "whywiki.db")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    project_id = insert_project(conn)
    insert_source(conn, project_id, "src_a", "docs/requirements_a.md")
    insert_source(conn, project_id, "src_b", "docs/requirements_b.md")
    insert_source(conn, project_id, "src_rejected", "docs/requirements_draft.md")
    insert_requirement(conn, project_id, "fact_a", "支持离线缓存", "src_a", "docs/requirements_a.md")
    insert_requirement(conn, project_id, "fact_b", "缓存支持手动刷新", "src_b", "docs/requirements_b.md")
    insert_requirement(conn, project_id, "fact_rejected", "只保留草稿缓存", "src_rejected", "docs/requirements_draft.md")
    insert_requirement_conflict(conn, project_id, "conf_1")
    conn.commit()

    decision = record_requirement_decision(
        project_id,
        conflict_id="conf_1",
        action="merge_requirement",
        superseded_fact_ids=["fact_a", "fact_b"],
        rejected_fact_ids=["fact_rejected"],
        created_statement="支持离线缓存，并允许手动刷新",
        reason="合并两份有效需求，排除草稿方案",
        conn=conn,
    )

    created_fact_id = decision["created_fact_id"]
    superseded = conn.execute(
        "SELECT id, superseded_by_fact_id FROM facts WHERE project_id = ? AND id IN ('fact_a', 'fact_b') ORDER BY id",
        (project_id,),
    ).fetchall()
    rejected = conn.execute("SELECT * FROM facts WHERE project_id = ? AND id = ?", (project_id, "fact_rejected")).fetchone()

    assert created_fact_id
    assert [row["superseded_by_fact_id"] for row in superseded] == [created_fact_id, created_fact_id]
    assert rejected["status"] == "rejected"
    assert rejected["validity_status"] == "historical"
    assert rejected["superseded_by_fact_id"] == ""


def test_decision_rejects_duplicate_ids_and_preserves_external_transaction(tmp_path):
    conn = sqlite3.connect(tmp_path / "whywiki.db")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    project_id = insert_project(conn)
    insert_source(conn, project_id, "src_new", "docs/requirements_v2.md")
    insert_requirement(conn, project_id, "fact_new", "支持离线缓存", "src_new", "docs/requirements_v2.md")
    insert_requirement_conflict(conn, project_id, "conf_1")
    conn.commit()
    conn.execute(
        "UPDATE projects SET description = ? WHERE id = ?",
        ("调用方事务内的变更", project_id),
    )

    with pytest.raises(ValueError):
        record_requirement_decision(
            project_id,
            conflict_id="conf_1",
            action="accept_fact",
            accepted_fact_id="fact_new",
            superseded_fact_ids=["fact_old", "fact_old"],
            conn=conn,
        )

    project = conn.execute("SELECT description FROM projects WHERE id = ?", (project_id,)).fetchone()
    assert project["description"] == "调用方事务内的变更"
