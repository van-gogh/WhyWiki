from pathlib import Path

import pytest

from whywiki.collaboration.models import EvidencePointer as ProviderEvidencePointer
from whywiki.db import connect, init_db
from whywiki.services.ask import ask_project
from whywiki.services.ingest import ingest_path
from whywiki.services.wiki_engine import build_project, build_wiki_pages
from whywiki.services.workspace import create_project
from whywiki.utils import now_iso, to_json


def build_messy_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    project = create_project("Fixture Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    ingest_path(project["id"], root)
    build_project(project["id"])
    return project


def seed_requirement_snapshot_project(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    conn = connect(tmp_path / "whywiki.db")
    init_db(conn)
    project = create_project("Requirement Snapshot Demo", conn=conn)
    now = now_iso()
    sources = [
        ("src_current", "docs/requirements_v2.md"),
        ("src_old", "docs/requirements_v1.md"),
        ("src_login", "docs/login_requirements.md"),
    ]
    for source_id, path in sources:
        conn.execute(
            """
            INSERT INTO sources(id, project_id, source_type, path, title, content_hash, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, project["id"], "local", path, path, f"hash-{source_id}", to_json({}), now, now),
        )
    facts = [
        (
            "fact_current",
            "移动端必须支持离线缓存当前项目记忆。",
            "src_current",
            "docs/requirements_v2.md",
            "confirmed",
            "current",
            "",
        ),
        (
            "fact_old",
            "移动端暂不支持离线缓存。",
            "src_old",
            "docs/requirements_v1.md",
            "confirmed",
            "superseded",
            "fact_current",
        ),
        (
            "fact_login",
            "登录必须支持 GitHub Device Flow。",
            "src_login",
            "docs/login_requirements.md",
            "candidate",
            "unknown",
            "",
        ),
    ]
    for fact_id, statement, source_id, path, status, validity, superseded_by in facts:
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
                project["id"],
                statement,
                to_json([{"source_id": source_id, "path": path}]),
                status,
                now,
                validity,
                superseded_by,
                now,
            ),
        )
    conn.commit()
    return conn, project


def test_requirements_wiki_uses_current_requirement_snapshot(tmp_path, monkeypatch):
    conn, project = seed_requirement_snapshot_project(tmp_path, monkeypatch)

    pages = build_wiki_pages(project["id"], conn)
    content = pages["requirements"]

    assert "# 当前需求快照" in content
    assert "## 当前有效" in content
    assert "## 已被替代" in content
    assert "移动端必须支持离线缓存当前项目记忆。" in content
    assert "移动端暂不支持离线缓存。" in content
    assert "状态：当前有效" in content
    assert "状态：已被替代" in content
    assert "证据：`docs/requirements_v2.md`" in content
    assert "替代者：`fact_current`" in content


def test_ask_current_requirement_answer_explains_superseded_history(tmp_path, monkeypatch):
    conn, project = seed_requirement_snapshot_project(tmp_path, monkeypatch)

    result = ask_project(project["id"], "当前需求是什么？", conn=conn)

    assert "当前有效需求如下" in result["answer"]
    assert "移动端必须支持离线缓存当前项目记忆。" in result["answer"]
    assert "状态：当前有效" in result["answer"]
    assert "历史材料中还有以下已被替代的需求" in result["answer"]
    assert "移动端暂不支持离线缓存。" in result["answer"]
    assert "不是当前执行依据" in result["answer"]
    assert result["evidence"] == [{"kind": "fact", "id": "fact_current", "path": "docs/requirements_v2.md", "score": 0.9}]


def test_ask_specific_requirement_question_uses_evidence_retrieval_not_current_snapshot(tmp_path, monkeypatch):
    conn, project = seed_requirement_snapshot_project(tmp_path, monkeypatch)

    result = ask_project(project["id"], "登录需求是什么？", conn=conn)

    assert "当前有效需求如下" not in result["answer"]
    assert "登录必须支持 GitHub Device Flow。" in result["answer"]
    assert "证据：`docs/login_requirements.md`" in result["answer"]
    assert result["evidence"]
    assert result["evidence"][0]["id"] == "fact_login"
    assert result["evidence"][0]["path"] == "docs/login_requirements.md"


def test_ask_returns_structured_evidence(tmp_path, monkeypatch):
    project = build_messy_fixture(tmp_path, monkeypatch)

    result = ask_project(project["id"], "接口是什么？")

    assert result["evidence"]
    assert {"kind", "id", "path", "score"}.issubset(result["evidence"][0])
    assert "证据" in result["answer"]


def test_provider_evidence_pointer_serializes_repo_location():
    pointer = ProviderEvidencePointer(
        provider="gitea",
        base_url="https://git.example.test",
        repo="team/backend",
        commit="abc123",
        path="src/main.py",
        line_start=10,
        line_end=12,
        content_hash="sha256:abc",
    )

    payload = pointer.to_dict()

    assert payload["provider"] == "gitea"
    assert payload["base_url"] == "https://git.example.test"
    assert payload["repo"] == "team/backend"
    assert payload["commit"] == "abc123"
    assert payload["line_start"] == 10


def test_ask_preserves_provider_fields_from_fact_evidence(tmp_path):
    conn = connect(tmp_path / "whywiki.db")
    init_db(conn)
    project = create_project("Provider Demo", conn=conn)
    now = now_iso()
    source_id = "src_provider"
    block_id = "blk_provider"
    fact_id = "fact_provider"
    provider_evidence = {
        "provider": "gitea",
        "base_url": "https://git.example.test",
        "repo": "team/backend",
        "ref": "main",
        "commit": "abc123",
        "path": "src/main.py",
        "line_start": 10,
        "line_end": 12,
        "content_hash": "sha256:abc",
        "source_id": source_id,
        "block_id": block_id,
    }
    conn.execute(
        """
        INSERT INTO sources(id, project_id, source_type, path, title, content_hash, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            project["id"],
            "git",
            "src/main.py",
            "main.py",
            "sha256:source",
            to_json({}),
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO blocks(id, project_id, source_id, block_type, text, location_json, metadata_json, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            block_id,
            project["id"],
            source_id,
            "code_file",
            "Unrelated local block text.",
            to_json({"line_start": 10, "line_end": 12}),
            to_json({}),
            "sha256:block",
        ),
    )
    conn.execute(
        """
        INSERT INTO facts(id, project_id, fact_type, statement, evidence_json, status, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fact_id,
            project["id"],
            "code",
            "Provider metadata is preserved for ask evidence.",
            to_json([provider_evidence]),
            "candidate",
            0.9,
            now,
        ),
    )
    conn.commit()

    result = ask_project(project["id"], "provider metadata", conn=conn)

    assert result["evidence"]
    assert result["evidence"][0] == {
        "kind": "fact",
        "id": fact_id,
        "path": "src/main.py",
        "score": 2.9,
        "provider": "gitea",
        "base_url": "https://git.example.test",
        "repo": "team/backend",
        "ref": "main",
        "commit": "abc123",
        "line_start": 10,
        "line_end": 12,
        "content_hash": "sha256:abc",
    }


def test_ask_returns_evidence_for_exact_docker_term(tmp_path, monkeypatch):
    project = build_messy_fixture(tmp_path, monkeypatch)

    result = ask_project(project["id"], "Docker")

    assert result["evidence"]
    assert "证据" in result["answer"]


def test_ask_returns_evidence_for_exact_post_term(tmp_path, monkeypatch):
    project = build_messy_fixture(tmp_path, monkeypatch)

    result = ask_project(project["id"], "POST")

    assert result["evidence"]
    assert "证据" in result["answer"]


def test_ask_returns_detected_conflicts_for_conflict_question(tmp_path, monkeypatch):
    project = build_messy_fixture(tmp_path, monkeypatch)

    result = ask_project(project["id"], "这个项目当前有哪些冲突？")

    assert any(item["kind"] == "conflict" for item in result["evidence"])
    assert "当前检测到以下待审查冲突" in result["answer"]
    assert "多个材料都声称自己是最新版或最终版" in result["answer"]
    assert "证据" in result["answer"]


def test_ask_refuses_method_without_matching_evidence(tmp_path, monkeypatch):
    project = build_messy_fixture(tmp_path, monkeypatch)

    result = ask_project(project["id"], "GET")

    assert result["evidence"] == []
    assert "没有找到足够证据" in result["answer"]


def test_ask_refuses_without_evidence(tmp_path, monkeypatch):
    project = build_messy_fixture(tmp_path, monkeypatch)

    result = ask_project(project["id"], "火星基地预算是多少？")

    assert result["evidence"] == []
    assert "没有找到足够证据" in result["answer"]


@pytest.mark.parametrize("question", ["用户预算是多少？", "用户收费是多少？", "模型预算是多少？"])
def test_ask_refuses_unsupported_pricing_intent_with_known_terms(tmp_path, monkeypatch, question):
    project = build_messy_fixture(tmp_path, monkeypatch)

    result = ask_project(project["id"], question)

    assert result["evidence"] == []
    assert "没有找到足够证据" in result["answer"]
