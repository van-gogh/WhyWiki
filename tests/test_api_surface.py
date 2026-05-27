from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from whywiki.app import app
from whywiki.db import connect
from whywiki.services.ingest import ingest_path
from whywiki.services.wiki_engine import build_project
from whywiki.services.workspace import create_project
from whywiki.utils import now_iso, to_json


def test_index_versions_static_scripts_for_local_development():
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert '/static/i18n.js?v=' in response.text
    assert '/static/app.js?v=' in response.text


def test_local_folder_picker_api_returns_selected_server_path(monkeypatch, tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()
    monkeypatch.setattr("whywiki.app.choose_local_folder", lambda: selected)
    client = TestClient(app)

    response = client.post("/api/local-folder-picker")

    assert response.status_code == 200
    assert response.json() == {"selected": True, "path": str(selected)}


def test_local_folder_picker_api_reports_cancelled_selection(monkeypatch):
    monkeypatch.setattr("whywiki.app.choose_local_folder", lambda: None)
    client = TestClient(app)

    response = client.post("/api/local-folder-picker")

    assert response.status_code == 200
    assert response.json() == {"selected": False, "path": ""}


def test_project_api_persists_and_updates_tags(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)

    created = client.post(
        "/api/projects",
        json={
            "name": "Tagged Project",
            "description": "Project with browse tags",
            "tags": ["AI", "  Research  ", "AI", ""],
        },
    )

    assert created.status_code == 200
    project = created.json()
    assert project["tags"] == ["ai", "research"]

    listed = client.get("/api/projects")
    assert listed.status_code == 200
    assert listed.json()[0]["tags"] == ["ai", "research"]

    updated = client.patch(
        f"/api/projects/{project['id']}",
        json={"tags": ["Client", "handover"]},
    )

    assert updated.status_code == 200
    assert updated.json()["tags"] == ["client", "handover"]
    assert client.get(f"/api/projects/{project['id']}").json()["tags"] == ["client", "handover"]


def wait_for_job(client: TestClient, job_id: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    last_payload = {}
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        last_payload = response.json()
        if last_payload["status"] in {"succeeded", "failed"}:
            return last_payload
        time.sleep(0.05)
    return last_payload


def seed_source(conn, project_id: str, source_id: str, path: str) -> None:
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO sources(id, project_id, source_type, path, title, content_hash, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (source_id, project_id, "local", path, path, f"hash-{source_id}", "{}", timestamp, timestamp),
    )


def seed_requirement_fact(
    conn,
    project_id: str,
    fact_id: str,
    statement: str,
    source_id: str,
    path: str,
    status: str = "candidate",
    validity_status: str = "unknown",
    superseded_by_fact_id: str = "",
    review_note: str = "",
) -> None:
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO facts(
            id, project_id, fact_type, statement, evidence_json, status, confidence,
            created_at, validity_status, superseded_by_fact_id, review_note, updated_at
        )
        VALUES (?, ?, 'requirement', ?, ?, ?, 0.9, ?, ?, ?, ?, ?)
        """,
        (
            fact_id,
            project_id,
            statement,
            to_json([{"source_id": source_id, "path": path}]),
            status,
            timestamp,
            validity_status,
            superseded_by_fact_id,
            review_note,
            timestamp,
        ),
    )


def seed_requirement_conflict(conn, project_id: str, conflict_id: str = "conf_1") -> None:
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


def test_dashboard_api_lists_sources_facts_and_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Fixture Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    ingest_path(project["id"], root)
    build_project(project["id"])

    sources = client.get(f"/api/projects/{project['id']}/sources")
    facts = client.get(f"/api/projects/{project['id']}/facts")

    assert sources.status_code == 200
    assert facts.status_code == 200
    assert sources.json()
    assert facts.json()

    source_id = sources.json()[0]["id"]
    blocks = client.get(f"/api/projects/{project['id']}/sources/{source_id}/blocks")
    assert blocks.status_code == 200
    assert blocks.json()


def test_fact_status_update_persists_for_review_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Fixture Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    ingest_path(project["id"], root)
    build_project(project["id"])

    fact = client.get(f"/api/projects/{project['id']}/facts").json()[0]
    update = client.patch(
        f"/api/projects/{project['id']}/facts/{fact['id']}",
        json={"status": "confirmed"},
    )

    assert update.status_code == 200
    assert update.json()["status"] == "confirmed"
    facts = client.get(f"/api/projects/{project['id']}/facts").json()
    assert next(item for item in facts if item["id"] == fact["id"])["status"] == "confirmed"


def test_requirement_snapshot_api_groups_current_and_superseded_requirements(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Lifecycle API Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_current", "docs/requirements_v2.md")
        seed_source(conn, project["id"], "source_old", "docs/requirements_v1.md")
        seed_requirement_fact(
            conn,
            project["id"],
            "fact_current",
            "支持离线缓存",
            "source_current",
            "docs/requirements_v2.md",
        )
        seed_requirement_fact(
            conn,
            project["id"],
            "fact_old",
            "不做离线缓存",
            "source_old",
            "docs/requirements_v1.md",
        )
        conn.commit()

    assert (
        client.patch(
            f"/api/projects/{project['id']}/facts/fact_current",
            json={"status": "confirmed", "validity_status": "current"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/projects/{project['id']}/facts/fact_old",
            json={
                "status": "confirmed",
                "validity_status": "superseded",
                "superseded_by_fact_id": "fact_current",
            },
        ).status_code
        == 200
    )

    response = client.get(f"/api/projects/{project['id']}/requirements/snapshot?language=zh-CN")

    assert response.status_code == 200
    payload = response.json()
    assert any(item["id"] == "fact_current" and item["lifecycle_label"] == "当前有效" for item in payload["current"])
    assert any(item["id"] == "fact_old" and item["lifecycle_label"] == "已被替代" for item in payload["superseded"])
    assert payload["source_statuses"]


def test_conflict_decision_api_records_current_requirement_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Conflict Decision API Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_current", "docs/requirements_v2.md")
        seed_source(conn, project["id"], "source_old", "docs/requirements_v1.md")
        seed_requirement_fact(
            conn,
            project["id"],
            "fact_new",
            "支持离线缓存",
            "source_current",
            "docs/requirements_v2.md",
        )
        seed_requirement_fact(
            conn,
            project["id"],
            "fact_old",
            "不做离线缓存",
            "source_old",
            "docs/requirements_v1.md",
        )
        seed_requirement_conflict(conn, project["id"], "conf_1")
        conn.commit()

    response = client.post(
        f"/api/projects/{project['id']}/conflicts/conf_1/decision",
        json={
            "action": "accept_fact",
            "accepted_fact_id": "fact_new",
            "superseded_fact_ids": ["fact_old"],
            "reason": "新版方案覆盖旧版需求",
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "accept_fact"
    snapshot = client.get(f"/api/projects/{project['id']}/requirements/snapshot").json()
    assert any(item["id"] == "fact_new" for item in snapshot["current"])
    assert any(item["id"] == "fact_old" for item in snapshot["superseded"])


def test_conflict_decision_api_rejects_duplicate_target_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Duplicate Decision API Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_current", "docs/requirements_v2.md")
        seed_source(conn, project["id"], "source_old", "docs/requirements_v1.md")
        seed_requirement_fact(conn, project["id"], "fact_new", "支持离线缓存", "source_current", "docs/requirements_v2.md")
        seed_requirement_fact(conn, project["id"], "fact_old", "不做离线缓存", "source_old", "docs/requirements_v1.md")
        seed_requirement_conflict(conn, project["id"], "conf_1")
        conn.commit()

    response = client.post(
        f"/api/projects/{project['id']}/conflicts/conf_1/decision",
        json={
            "action": "accept_fact",
            "accepted_fact_id": "fact_new",
            "superseded_fact_ids": ["fact_old", "fact_old"],
        },
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "request_json",
    [
        {
            "action": "accept_fact",
            "accepted_fact_id": "fact_new",
            "superseded_fact_ids": ["fact_new"],
        },
        {
            "action": "accept_fact",
            "accepted_fact_id": "fact_new",
            "rejected_fact_ids": ["fact_new"],
        },
        {
            "action": "accept_fact",
            "accepted_fact_id": "fact_new",
            "superseded_fact_ids": ["fact_old"],
            "rejected_fact_ids": ["fact_old"],
        },
    ],
)
def test_conflict_decision_api_rejects_target_ids_reused_across_roles(tmp_path, monkeypatch, request_json):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Overlap Decision API Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_current", "docs/requirements_v2.md")
        seed_source(conn, project["id"], "source_old", "docs/requirements_v1.md")
        seed_requirement_fact(conn, project["id"], "fact_new", "支持离线缓存", "source_current", "docs/requirements_v2.md")
        seed_requirement_fact(conn, project["id"], "fact_old", "不做离线缓存", "source_old", "docs/requirements_v1.md")
        seed_requirement_conflict(conn, project["id"], "conf_1")
        conn.commit()

    response = client.post(
        f"/api/projects/{project['id']}/conflicts/conf_1/decision",
        json=request_json,
    )

    assert response.status_code == 400


def test_conflict_decision_api_rejects_fact_not_linked_to_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Scoped Decision API Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_current", "docs/requirements_v2.md")
        seed_source(conn, project["id"], "source_old", "docs/requirements_v1.md")
        seed_source(conn, project["id"], "source_other", "docs/requirements_other.md")
        seed_requirement_fact(conn, project["id"], "fact_new", "支持离线缓存", "source_current", "docs/requirements_v2.md")
        seed_requirement_fact(conn, project["id"], "fact_old", "不做离线缓存", "source_old", "docs/requirements_v1.md")
        seed_requirement_fact(conn, project["id"], "fact_other", "支持邮件通知", "source_other", "docs/requirements_other.md")
        seed_requirement_conflict(conn, project["id"], "conf_1")
        conn.commit()

    response = client.post(
        f"/api/projects/{project['id']}/conflicts/conf_1/decision",
        json={
            "action": "accept_fact",
            "accepted_fact_id": "fact_other",
            "superseded_fact_ids": ["fact_old"],
        },
    )

    assert response.status_code == 400
    assert "not linked" in response.json()["detail"]


def test_conflict_decision_api_rejects_non_requirement_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Non Requirement Decision API Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_api", "docs/api.md")
        seed_requirement_fact(conn, project["id"], "fact_requirement", "支持离线缓存", "source_api", "docs/api.md")
        conn.execute(
            """
            INSERT INTO conflicts(
                id, project_id, conflict_key, conflict_type, title, description,
                evidence_json, severity, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "conf_api",
                project["id"],
                "endpoint:demo",
                "endpoint_mismatch",
                "接口路径不一致",
                "这不是需求冲突",
                to_json([{"source_id": "source_api", "path": "docs/api.md"}]),
                "medium",
                "open",
                now_iso(),
            ),
        )
        conn.commit()

    response = client.post(
        f"/api/projects/{project['id']}/conflicts/conf_api/decision",
        json={
            "action": "accept_fact",
            "accepted_fact_id": "fact_requirement",
        },
    )

    assert response.status_code == 400
    assert "only resolve requirement conflicts" in response.json()["detail"]


def test_conflict_decision_api_rejects_generic_fact_statement_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Fact Statement Conflict API Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_fact", "docs/requirements.md")
        seed_requirement_fact(conn, project["id"], "fact_requirement", "支持离线缓存", "source_fact", "docs/requirements.md")
        conn.execute(
            """
            INSERT INTO conflicts(
                id, project_id, conflict_key, conflict_type, title, description,
                evidence_json, severity, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "conf_fact",
                project["id"],
                "fact:demo",
                "fact_statement_conflict",
                "事实陈述冲突",
                "不是显式需求冲突",
                to_json([{"source_id": "source_fact", "path": "docs/requirements.md"}]),
                "medium",
                "open",
                now_iso(),
            ),
        )
        conn.commit()

    response = client.post(
        f"/api/projects/{project['id']}/conflicts/conf_fact/decision",
        json={
            "action": "accept_fact",
            "accepted_fact_id": "fact_requirement",
        },
    )

    assert response.status_code == 400
    assert "only resolve requirement conflicts" in response.json()["detail"]


def test_conflict_decision_api_returns_404_for_missing_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Missing Conflict Decision API Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_current", "docs/requirements_v2.md")
        seed_requirement_fact(conn, project["id"], "fact_new", "支持离线缓存", "source_current", "docs/requirements_v2.md")
        conn.commit()

    response = client.post(
        f"/api/projects/{project['id']}/conflicts/missing_conflict/decision",
        json={
            "action": "accept_fact",
            "accepted_fact_id": "fact_new",
        },
    )

    assert response.status_code == 404


def test_fact_status_patch_preserves_lifecycle_fields_when_omitted(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Lifecycle Preserve Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_1", "docs/requirements.md")
        seed_requirement_fact(
            conn,
            project["id"],
            "fact_current",
            "当前需求",
            "source_1",
            "docs/requirements.md",
            status="confirmed",
            validity_status="current",
        )
        seed_requirement_fact(
            conn,
            project["id"],
            "fact_old",
            "旧需求",
            "source_1",
            "docs/requirements.md",
            status="confirmed",
            validity_status="superseded",
            superseded_by_fact_id="fact_current",
            review_note="保留这条评审备注",
        )
        conn.commit()

    response = client.patch(
        f"/api/projects/{project['id']}/facts/fact_old",
        json={"status": "needs_review"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_review"
    assert payload["validity_status"] == "superseded"
    assert payload["superseded_by_fact_id"] == "fact_current"
    assert payload["review_note"] == "保留这条评审备注"


def test_fact_status_patch_allows_lifecycle_only_update(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Lifecycle Only Patch Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_1", "docs/requirements.md")
        seed_requirement_fact(conn, project["id"], "fact_current", "当前需求", "source_1", "docs/requirements.md", status="confirmed")
        seed_requirement_fact(conn, project["id"], "fact_old", "旧需求", "source_1", "docs/requirements.md", status="confirmed")
        conn.commit()

    response = client.patch(
        f"/api/projects/{project['id']}/facts/fact_old",
        json={"validity_status": "superseded", "superseded_by_fact_id": "fact_current"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "confirmed"
    assert payload["validity_status"] == "superseded"
    assert payload["superseded_by_fact_id"] == "fact_current"


def test_fact_status_patch_rejects_invalid_superseded_replacement(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Lifecycle Validation Project")
    other_project = create_project("Other Lifecycle Project")
    with connect() as conn:
        seed_source(conn, project["id"], "source_1", "docs/requirements.md")
        seed_source(conn, other_project["id"], "other_source", "docs/other.md")
        seed_requirement_fact(conn, project["id"], "fact_current", "当前需求", "source_1", "docs/requirements.md")
        seed_requirement_fact(conn, project["id"], "fact_old", "旧需求", "source_1", "docs/requirements.md")
        seed_requirement_fact(conn, other_project["id"], "other_fact", "其他项目需求", "other_source", "docs/other.md")
        conn.commit()

    missing = client.patch(
        f"/api/projects/{project['id']}/facts/fact_old",
        json={"status": "confirmed", "validity_status": "superseded"},
    )
    self_reference = client.patch(
        f"/api/projects/{project['id']}/facts/fact_old",
        json={
            "status": "confirmed",
            "validity_status": "superseded",
            "superseded_by_fact_id": "fact_old",
        },
    )
    nonexistent = client.patch(
        f"/api/projects/{project['id']}/facts/fact_old",
        json={
            "status": "confirmed",
            "validity_status": "superseded",
            "superseded_by_fact_id": "missing_fact",
        },
    )
    cross_project = client.patch(
        f"/api/projects/{project['id']}/facts/fact_old",
        json={
            "status": "confirmed",
            "validity_status": "superseded",
            "superseded_by_fact_id": "other_fact",
        },
    )

    assert missing.status_code == 400
    assert self_reference.status_code == 400
    assert nonexistent.status_code == 400
    assert cross_project.status_code == 400


def test_fact_evidence_endpoint_resolves_original_block_text(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Fixture Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    ingest_path(project["id"], root)
    build_project(project["id"])

    fact = client.get(f"/api/projects/{project['id']}/facts").json()[0]
    response = client.get(f"/api/projects/{project['id']}/facts/{fact['id']}/evidence")

    assert response.status_code == 200
    evidence = response.json()
    assert evidence
    assert {"path", "source_type", "block_text", "location"}.issubset(evidence[0])
    assert evidence[0]["block_text"]


def test_conflict_evidence_endpoint_resolves_original_block_text_when_available(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Fixture Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    ingest_path(project["id"], root)
    build_project(project["id"])

    conflict = client.get(f"/api/projects/{project['id']}/conflicts").json()[0]
    response = client.get(f"/api/projects/{project['id']}/conflicts/{conflict['id']}/evidence")

    assert response.status_code == 200
    evidence = response.json()
    assert evidence
    assert {"path", "source_type", "block_text", "location"}.issubset(evidence[0])


def test_ingest_and_build_jobs_expose_progress_until_success(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Fixture Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"

    ingest_start = client.post(
        f"/api/projects/{project['id']}/ingest-jobs",
        json={"path": str(root), "source_type": "local"},
    )
    assert ingest_start.status_code == 200
    ingest_payload = ingest_start.json()
    assert ingest_payload["status"] in {"queued", "running", "succeeded"}
    assert 0 <= ingest_payload["progress"] <= 100

    ingest_done = wait_for_job(client, ingest_payload["id"])
    assert ingest_done["status"] == "succeeded"
    assert ingest_done["progress"] == 100
    assert ingest_done["result"]["files_seen"] > 0

    build_start = client.post(f"/api/projects/{project['id']}/build-jobs")
    assert build_start.status_code == 200
    build_done = wait_for_job(client, build_start.json()["id"])
    assert build_done["status"] == "succeeded"
    assert build_done["progress"] == 100
    assert build_done["result"]["facts_created"] > 0


def test_delete_project_removes_project_and_related_records(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Disposable Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    ingest_path(project["id"], root)
    build_project(project["id"])

    response = client.delete(f"/api/projects/{project['id']}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "project_id": project["id"]}
    assert project["id"] not in {item["id"] for item in client.get("/api/projects").json()}
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    with connect() as conn:
        for table in ("sources", "blocks", "facts", "conflicts", "wiki_pages", "operation_jobs"):
            count = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE project_id = ?", (project["id"],)).fetchone()["count"]
            assert count == 0
