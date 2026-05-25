from __future__ import annotations

import re
import sqlite3
from typing import Any

from ..db import connect, init_db
from ..utils import compact_text, from_json, new_id, now_iso, to_json

ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_/{}/.:-]+)", re.IGNORECASE)


def fact_identity(fact_type: str, statement: str, evidence: list[dict[str, Any]]) -> tuple[str, str, str]:
    first = evidence[0] if evidence and isinstance(evidence[0], dict) else {}
    return (fact_type, statement, str(first.get("path") or ""))


def row_fact_identity(row: sqlite3.Row) -> tuple[str, str, str]:
    evidence = from_json(row["evidence_json"], [])
    return fact_identity(row["fact_type"], row["statement"], evidence if isinstance(evidence, list) else [])


def decision_fact_ids(conn: sqlite3.Connection, project_id: str) -> set[str]:
    ids: set[str] = set()
    rows = conn.execute(
        """
        SELECT accepted_fact_id, created_fact_id, superseded_fact_ids_json, rejected_fact_ids_json
        FROM requirement_decisions
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchall()
    for row in rows:
        for key in ("accepted_fact_id", "created_fact_id"):
            if row[key]:
                ids.add(row[key])
        for key in ("superseded_fact_ids_json", "rejected_fact_ids_json"):
            values = from_json(row[key], [])
            if isinstance(values, list):
                ids.update(str(value) for value in values if value)
    return ids


def should_preserve_unmatched_fact(row: sqlite3.Row, referenced_fact_ids: set[str]) -> bool:
    if row["id"] in referenced_fact_ids:
        return True
    if row["status"] != "candidate":
        return True
    if "validity_status" in row.keys() and (row["validity_status"] or "unknown") != "unknown":
        return True
    if "superseded_by_fact_id" in row.keys() and row["superseded_by_fact_id"]:
        return True
    if "review_note" in row.keys() and row["review_note"]:
        return True
    return False


def lifecycle_priority(row: sqlite3.Row, referenced_fact_ids: set[str]) -> tuple[int, str]:
    if row["id"] in referenced_fact_ids:
        return (0, row["created_at"] or "")
    if should_preserve_unmatched_fact(row, referenced_fact_ids):
        return (1, row["created_at"] or "")
    return (2, row["created_at"] or "")


def classify_fact(block_type: str, text: str) -> tuple[str, float]:
    t = text.lower()
    if "endpoint" in block_type or ENDPOINT_RE.search(text):
        return "api", 0.82
    if block_type.startswith("code_") or "function" in t or "class" in t or "import" in t:
        return "code", 0.78
    if any(k in text for k in ["需求", "用户故事", "Requirement", "requirement"]):
        return "requirement", 0.72
    if any(k in t for k in ["experiment", "f1", "accuracy", "dataset", "model", "模型", "实验"]):
        return "experiment", 0.7
    if any(k in t for k in ["deploy", "docker", "k8s", "kubernetes", "上线", "部署"]):
        return "deployment", 0.7
    if any(k in text for k in ["决定", "原因", "decision", "why", "废弃", "deprecated"]):
        return "decision", 0.68
    if block_type in {"table_row"}:
        return "record", 0.65
    return "document", 0.55


def rebuild_facts(project_id: str, conn: sqlite3.Connection | None = None) -> dict:
    close = conn is None
    conn = conn or connect()
    init_db(conn)
    existing_rows = conn.execute("SELECT * FROM facts WHERE project_id = ?", (project_id,)).fetchall()
    referenced_fact_ids = decision_fact_ids(conn, project_id)
    existing_rows = sorted(existing_rows, key=lambda row: lifecycle_priority(row, referenced_fact_ids))
    existing_by_identity: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
    for row in existing_rows:
        existing_by_identity.setdefault(row_fact_identity(row), []).append(row)

    rows = conn.execute(
        """
        SELECT b.*, s.path AS source_path, s.title AS source_title
        FROM blocks b
        JOIN sources s ON s.id = b.source_id
        WHERE b.project_id = ?
        ORDER BY s.path
        """,
        (project_id,),
    ).fetchall()

    inserted = 0
    processed_fact_ids: set[str] = set()
    for row in rows:
        fact_type, confidence = classify_fact(row["block_type"], row["text"])
        statement = make_statement(fact_type, row["block_type"], row["text"], row["source_title"])
        evidence = [
            {
                "source_id": row["source_id"],
                "block_id": row["id"],
                "path": row["source_path"],
                "location": from_json(row["location_json"], {}),
            }
        ]
        identity = fact_identity(fact_type, statement, evidence)
        existing = existing_by_identity.get(identity, [])
        if existing:
            fact_id = existing.pop(0)["id"]
            processed_fact_ids.add(fact_id)
            conn.execute(
                """
                UPDATE facts
                SET fact_type = ?, statement = ?, evidence_json = ?, confidence = ?, updated_at = ?
                WHERE project_id = ? AND id = ?
                """,
                (fact_type, statement, to_json(evidence), confidence, now_iso(), project_id, fact_id),
            )
        else:
            fact_id = new_id("fact")
            conn.execute(
                """
                INSERT INTO facts(
                    id, project_id, fact_type, statement, evidence_json, status, confidence,
                    created_at, validity_status, superseded_by_fact_id, review_note, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unknown', '', '', ?)
                """,
                (fact_id, project_id, fact_type, statement, to_json(evidence), "candidate", confidence, now_iso(), now_iso()),
            )
            processed_fact_ids.add(fact_id)
            inserted += 1

    for row in existing_rows:
        if row["id"] in processed_fact_ids:
            continue
        if should_preserve_unmatched_fact(row, referenced_fact_ids):
            continue
        conn.execute("DELETE FROM facts WHERE project_id = ? AND id = ?", (project_id, row["id"]))

    conn.commit()
    if close:
        conn.close()
    return {"project_id": project_id, "facts_created": inserted}


def make_statement(fact_type: str, block_type: str, text: str, source_title: str) -> str:
    preview = compact_text(text, 500)
    if fact_type == "api":
        return f"材料 `{source_title}` 中记录了接口相关信息：{preview}"
    if fact_type == "code":
        return f"代码材料 `{source_title}` 中存在代码结构信息：{preview}"
    if fact_type == "requirement":
        return f"材料 `{source_title}` 中记录了需求相关信息：{preview}"
    if fact_type == "experiment":
        return f"材料 `{source_title}` 中记录了实验/模型相关信息：{preview}"
    if fact_type == "deployment":
        return f"材料 `{source_title}` 中记录了部署相关信息：{preview}"
    if fact_type == "decision":
        return f"材料 `{source_title}` 中记录了决策或变更原因：{preview}"
    return f"材料 `{source_title}` 中记录了项目事实：{preview}"
