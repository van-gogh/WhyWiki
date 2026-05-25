from __future__ import annotations

import sqlite3
from typing import Any

from ..db import connect, rows_to_dicts
from ..utils import from_json
from .lifecycle_labels import decision_action_label, requirement_status_label, source_status_label

OUTDATED_REQUIREMENT_STATUSES = {"superseded", "rejected", "historical"}
ACTIVE_REQUIREMENT_STATUSES = {"current", "confirmed", "needs_review", "candidate"}
SNAPSHOT_GROUPS = ("current", "needs_review", "superseded", "historical", "rejected", "conflicting")


def row_value(row: sqlite3.Row | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    if key in row.keys():
        return row[key]
    return default


def requirement_lifecycle_status(row: sqlite3.Row | dict[str, Any]) -> str:
    status = row_value(row, "status", "") or ""
    validity = row_value(row, "validity_status", "") or ""

    if validity == "current":
        return "current"
    if validity == "superseded":
        return "superseded"
    if validity == "historical":
        return "historical"
    if validity == "conflicting":
        return "conflicting"
    if status == "rejected" or validity == "outdated":
        return "rejected"
    if status in {"candidate", "needs_review"}:
        return "needs_review"
    if status == "confirmed":
        return "confirmed"
    return "candidate"


def fact_to_requirement(row: sqlite3.Row | dict[str, Any], language: str | None = None) -> dict[str, Any]:
    item = dict(row)
    evidence = from_json(row_value(row, "evidence_json", "[]"), [])
    if not isinstance(evidence, list):
        evidence = []
    lifecycle_status = requirement_lifecycle_status(row)
    item["evidence"] = evidence
    item["lifecycle_status"] = lifecycle_status
    item["lifecycle_label"] = requirement_status_label(lifecycle_status, language)
    return item


def derive_source_statuses(
    sources: list[sqlite3.Row] | list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    language: str | None = None,
) -> dict[str, dict[str, Any]]:
    requirements_by_source_id: dict[str, list[dict[str, Any]]] = {}
    requirements_by_path: dict[str, list[dict[str, Any]]] = {}
    for requirement in requirements:
        for evidence in requirement.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            source_id = evidence.get("source_id")
            path = evidence.get("path")
            if source_id:
                requirements_by_source_id.setdefault(str(source_id), []).append(requirement)
            if path:
                requirements_by_path.setdefault(str(path), []).append(requirement)

    statuses: dict[str, dict[str, Any]] = {}
    for source in sources:
        source_id = row_value(source, "id", "")
        path = row_value(source, "path", "")
        related = list(requirements_by_source_id.get(source_id, []))
        if not related and path:
            related = list(requirements_by_path.get(path, []))

        status = "active"
        if related:
            lifecycle_statuses = {requirement.get("lifecycle_status", "candidate") for requirement in related}
            if "conflicting" in lifecycle_statuses:
                status = "conflicting"
            elif lifecycle_statuses and lifecycle_statuses.issubset(OUTDATED_REQUIREMENT_STATUSES):
                status = "outdated"
            elif lifecycle_statuses & OUTDATED_REQUIREMENT_STATUSES and lifecycle_statuses & ACTIVE_REQUIREMENT_STATUSES:
                status = "partially_outdated"

        source_item = dict(source)
        source_item["status"] = status
        source_item["label"] = source_status_label(status, language)
        source_item["requirement_count"] = len(related)
        statuses[source_id] = source_item
    return statuses


def decision_to_snapshot(row: sqlite3.Row | dict[str, Any], language: str | None = None) -> dict[str, Any]:
    item = dict(row)
    superseded = from_json(row_value(row, "superseded_fact_ids_json", "[]"), [])
    rejected = from_json(row_value(row, "rejected_fact_ids_json", "[]"), [])
    evidence = from_json(row_value(row, "evidence_json", "[]"), [])
    item["superseded_fact_ids"] = superseded if isinstance(superseded, list) else []
    item["rejected_fact_ids"] = rejected if isinstance(rejected, list) else []
    item["evidence"] = evidence if isinstance(evidence, list) else []
    item["action_label"] = decision_action_label(row_value(row, "action", ""), language)
    return item


def conflict_to_snapshot(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    evidence = from_json(row_value(row, "evidence_json", "[]"), [])
    item["evidence"] = evidence if isinstance(evidence, list) else []
    return item


def build_requirement_snapshot(
    project_id: str,
    conn: sqlite3.Connection | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    close = conn is None
    conn = conn or connect()
    try:
        fact_rows = conn.execute(
            """
            SELECT *
            FROM facts
            WHERE project_id = ? AND fact_type = 'requirement'
            ORDER BY created_at ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        requirements = [fact_to_requirement(row, language) for row in fact_rows]

        snapshot: dict[str, Any] = {group: [] for group in SNAPSHOT_GROUPS}
        for requirement in requirements:
            lifecycle_status = requirement["lifecycle_status"]
            if lifecycle_status in {"current", "confirmed"}:
                snapshot["current"].append(requirement)
            elif lifecycle_status in {"needs_review", "candidate"}:
                snapshot["needs_review"].append(requirement)
            elif lifecycle_status in snapshot:
                snapshot[lifecycle_status].append(requirement)
            else:
                snapshot["needs_review"].append(requirement)

        decision_rows = conn.execute(
            """
            SELECT *
            FROM requirement_decisions
            WHERE project_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 20
            """,
            (project_id,),
        ).fetchall()
        conflict_rows = conn.execute(
            """
            SELECT *
            FROM conflicts
            WHERE project_id = ? AND status = 'open'
            ORDER BY created_at DESC, id DESC
            """,
            (project_id,),
        ).fetchall()
        source_rows = conn.execute(
            """
            SELECT *
            FROM sources
            WHERE project_id = ?
            ORDER BY path ASC, id ASC
            """,
            (project_id,),
        ).fetchall()

        decisions = [decision_to_snapshot(row, language) for row in decision_rows]
        open_conflicts = [conflict_to_snapshot(row) for row in conflict_rows]
        source_statuses = derive_source_statuses(rows_to_dicts(source_rows), requirements, language)

        snapshot["decisions"] = decisions
        snapshot["open_conflicts"] = open_conflicts
        snapshot["source_statuses"] = source_statuses
        snapshot["metrics"] = {
            "current": len(snapshot["current"]),
            "needs_review": len(snapshot["needs_review"]),
            "superseded": len(snapshot["superseded"]),
            "historical": len(snapshot["historical"]),
            "rejected": len(snapshot["rejected"]),
            "conflicting": len(snapshot["conflicting"]),
            "decisions": len(decisions),
            "open_conflicts": len(open_conflicts),
            "sources": len(source_statuses),
        }
        return snapshot
    finally:
        if close:
            conn.close()
