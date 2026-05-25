from __future__ import annotations

import sqlite3
from typing import Any

from ..db import connect, rows_to_dicts
from ..utils import from_json, new_id, now_iso, to_json
from .lifecycle_labels import decision_action_label, requirement_status_label, source_status_label

OUTDATED_REQUIREMENT_STATUSES = {"superseded", "rejected", "historical"}
ACTIVE_REQUIREMENT_STATUSES = {"current", "confirmed", "needs_review", "candidate"}
SNAPSHOT_GROUPS = ("current", "needs_review", "superseded", "historical", "rejected", "conflicting")
DECISION_ACTIONS = {"accept_fact", "merge_requirement", "mark_outdated", "leave_for_later", "ignore_conflict"}


class RequirementLifecycleNotFound(ValueError):
    pass


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
    if status == "needs_review":
        return "needs_review"
    if status == "candidate":
        return "candidate"
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


def evidence_items_overlap(conflict_evidence: dict[str, Any], fact_evidence: dict[str, Any]) -> bool:
    fact_id = conflict_evidence.get("fact_id")
    if fact_id:
        return False
    for key in ("block_id", "source_id"):
        if conflict_evidence.get(key) and conflict_evidence.get(key) == fact_evidence.get(key):
            return True
    return bool(conflict_evidence.get("path") and conflict_evidence.get("path") == fact_evidence.get("path"))


def conflict_requirement_fact_ids(
    conn: sqlite3.Connection,
    project_id: str,
    conflict: sqlite3.Row | dict[str, Any],
) -> set[str]:
    conflict_evidence = conflict_to_snapshot(conflict)["evidence"]
    direct_fact_ids = {
        str(item["fact_id"])
        for item in conflict_evidence
        if isinstance(item, dict) and item.get("fact_id")
    }
    matched_ids = set(direct_fact_ids)
    rows = conn.execute(
        """
        SELECT id, evidence_json
        FROM facts
        WHERE project_id = ? AND fact_type = 'requirement'
        """,
        (project_id,),
    ).fetchall()
    for row in rows:
        if row["id"] in direct_fact_ids:
            continue
        fact_evidence = from_json(row["evidence_json"], [])
        if not isinstance(fact_evidence, list):
            continue
        for conflict_item in conflict_evidence:
            if not isinstance(conflict_item, dict):
                continue
            if any(
                isinstance(fact_item, dict) and evidence_items_overlap(conflict_item, fact_item)
                for fact_item in fact_evidence
            ):
                matched_ids.add(row["id"])
                break
    return matched_ids


def _unique_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for fact_id in ids:
        fact_id = (fact_id or "").strip()
        if fact_id and fact_id not in seen:
            seen.add(fact_id)
            unique.append(fact_id)
    return unique


def _normalized_ids(ids: list[str], label: str) -> list[str]:
    normalized = [(fact_id or "").strip() for fact_id in ids]
    normalized = [fact_id for fact_id in normalized if fact_id]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"Duplicate requirement fact ids in {label}")
    return normalized


def _ensure_distinct_roles(accepted_fact_id: str, superseded_ids: list[str], rejected_ids: list[str]) -> None:
    role_ids = [fact_id for fact_id in [accepted_fact_id, *superseded_ids, *rejected_ids] if fact_id]
    if len(role_ids) != len(set(role_ids)):
        raise ValueError("Requirement fact ids cannot be repeated across decision roles")


def _validate_requirement_facts(conn: sqlite3.Connection, project_id: str, fact_ids: list[str]) -> None:
    if not fact_ids:
        return
    placeholders = ",".join("?" for _ in fact_ids)
    rows = conn.execute(
        f"""
        SELECT id
        FROM facts
        WHERE project_id = ? AND fact_type = 'requirement' AND id IN ({placeholders})
        """,
        (project_id, *fact_ids),
    ).fetchall()
    found = {row["id"] for row in rows}
    missing = [fact_id for fact_id in fact_ids if fact_id not in found]
    if missing:
        raise ValueError(f"Requirement fact not found for project: {', '.join(missing)}")


def _validate_conflict_fact_scope(
    conn: sqlite3.Connection,
    project_id: str,
    conflict: sqlite3.Row | dict[str, Any],
    fact_ids: list[str],
) -> None:
    if not fact_ids:
        return
    scoped_ids = conflict_requirement_fact_ids(conn, project_id, conflict)
    if not scoped_ids:
        raise ValueError("Conflict has no linked requirement facts")
    outside = [fact_id for fact_id in fact_ids if fact_id not in scoped_ids]
    if outside:
        raise ValueError(f"Requirement fact is not linked to this conflict: {', '.join(outside)}")


def requirement_evidence(conn: sqlite3.Connection, project_id: str, fact_id: str) -> list[Any]:
    row = conn.execute(
        """
        SELECT evidence_json
        FROM facts
        WHERE project_id = ? AND fact_type = 'requirement' AND id = ?
        """,
        (project_id, fact_id),
    ).fetchone()
    if not row:
        raise RequirementLifecycleNotFound(f"Requirement fact not found for project: {fact_id}")
    evidence = from_json(row["evidence_json"], [])
    return evidence if isinstance(evidence, list) else []


def _merged_evidence(conn: sqlite3.Connection, project_id: str, fact_ids: list[str]) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for fact_id in fact_ids:
        for evidence_item in requirement_evidence(conn, project_id, fact_id):
            key = to_json(evidence_item)
            if key not in seen:
                seen.add(key)
                merged.append(evidence_item)
    return merged


def create_merged_requirement(
    conn: sqlite3.Connection,
    project_id: str,
    statement: str,
    source_fact_ids: list[str],
) -> str:
    source_fact_ids = _unique_ids(source_fact_ids)
    _validate_requirement_facts(conn, project_id, source_fact_ids)
    now = now_iso()
    fact_id = new_id("fact")
    conn.execute(
        """
        INSERT INTO facts(
            id, project_id, fact_type, statement, evidence_json, status, confidence,
            created_at, validity_status, superseded_by_fact_id, review_note, updated_at
        )
        VALUES (?, ?, 'requirement', ?, ?, 'confirmed', 0.9, ?, 'current', '', '', ?)
        """,
        (fact_id, project_id, statement, to_json(_merged_evidence(conn, project_id, source_fact_ids)), now, now),
    )
    return fact_id


def _ensure_conflict(conn: sqlite3.Connection, project_id: str, conflict_id: str) -> sqlite3.Row:
    if not conflict_id:
        raise ValueError("Conflict id is required")
    row = conn.execute(
        "SELECT * FROM conflicts WHERE project_id = ? AND id = ?",
        (project_id, conflict_id),
    ).fetchone()
    if not row:
        raise RequirementLifecycleNotFound("Conflict not found")
    return row


def _update_rejected_facts(
    conn: sqlite3.Connection,
    project_id: str,
    fact_ids: list[str],
    note: str,
    now: str,
) -> None:
    for fact_id in fact_ids:
        cursor = conn.execute(
            """
            UPDATE facts
            SET status = 'rejected', validity_status = 'historical', superseded_by_fact_id = '',
                review_note = ?, updated_at = ?
            WHERE project_id = ? AND id = ?
            """,
            (note, now, project_id, fact_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"Rejected requirement fact was not updated: {fact_id}")


def record_requirement_decision(
    project_id: str,
    conflict_id: str,
    action: str,
    accepted_fact_id: str = "",
    superseded_fact_ids: list[str] | None = None,
    rejected_fact_ids: list[str] | None = None,
    created_statement: str = "",
    reason: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    if action not in DECISION_ACTIONS:
        raise ValueError("Invalid requirement decision action")

    owns_connection = conn is None
    conn = conn or connect()
    savepoint_name = new_id("requirement_decision")
    conn.execute(f"SAVEPOINT {savepoint_name}")
    try:
        conflict = _ensure_conflict(conn, project_id, conflict_id)
        accepted_fact_id = accepted_fact_id.strip()
        superseded_ids = _normalized_ids(superseded_fact_ids or [], "superseded_fact_ids")
        rejected_ids = _normalized_ids(rejected_fact_ids or [], "rejected_fact_ids")
        _ensure_distinct_roles(accepted_fact_id, superseded_ids, rejected_ids)
        target_ids = _unique_ids([accepted_fact_id, *superseded_ids, *rejected_ids])
        _validate_conflict_fact_scope(conn, project_id, conflict, target_ids)
        created_fact_id = ""
        note = reason.strip()
        now = now_iso()

        if action == "accept_fact":
            if not accepted_fact_id:
                raise ValueError("accept_fact requires accepted_fact_id")
            _validate_requirement_facts(conn, project_id, target_ids)
            cursor = conn.execute(
                """
                UPDATE facts
                SET status = 'confirmed', validity_status = 'current', superseded_by_fact_id = '',
                    review_note = ?, updated_at = ?
                WHERE project_id = ? AND id = ?
                """,
                (note, now, project_id, accepted_fact_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Accepted requirement fact was not updated")
            for fact_id in superseded_ids:
                conn.execute(
                    """
                    UPDATE facts
                    SET status = 'confirmed', validity_status = 'superseded', superseded_by_fact_id = ?,
                        review_note = ?, updated_at = ?
                    WHERE project_id = ? AND id = ?
                    """,
                    (accepted_fact_id, note, now, project_id, fact_id),
                )
            _update_rejected_facts(conn, project_id, rejected_ids, note, now)

        elif action == "merge_requirement":
            if not created_statement.strip():
                raise ValueError("merge_requirement requires created_statement")
            source_fact_ids = _unique_ids([accepted_fact_id, *superseded_ids])
            if not source_fact_ids:
                raise ValueError("merge_requirement requires source facts")
            _validate_requirement_facts(conn, project_id, [*source_fact_ids, *rejected_ids])
            created_fact_id = create_merged_requirement(conn, project_id, created_statement.strip(), source_fact_ids)
            for fact_id in source_fact_ids:
                conn.execute(
                    """
                    UPDATE facts
                    SET status = 'confirmed', validity_status = 'superseded', superseded_by_fact_id = ?,
                        review_note = ?, updated_at = ?
                    WHERE project_id = ? AND id = ?
                    """,
                    (created_fact_id, note, now, project_id, fact_id),
                )
            _update_rejected_facts(conn, project_id, rejected_ids, note, now)

        elif action == "mark_outdated":
            if not target_ids:
                raise ValueError("mark_outdated requires target facts")
            _validate_requirement_facts(conn, project_id, target_ids)
            _update_rejected_facts(conn, project_id, target_ids, note, now)

        elif action in {"leave_for_later", "ignore_conflict"}:
            _validate_requirement_facts(conn, project_id, target_ids)

        evidence = _merged_evidence(conn, project_id, target_ids) if target_ids else conflict_to_snapshot(conflict)["evidence"]
        if action != "leave_for_later":
            next_status = "ignored" if action == "ignore_conflict" else "resolved"
            conn.execute(
                "UPDATE conflicts SET status = ? WHERE project_id = ? AND id = ?",
                (next_status, project_id, conflict_id),
            )

        decision_id = new_id("decision")
        conn.execute(
            """
            INSERT INTO requirement_decisions(
                id, project_id, conflict_id, action, accepted_fact_id, created_fact_id,
                superseded_fact_ids_json, rejected_fact_ids_json, reason, evidence_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                project_id,
                conflict_id,
                action,
                accepted_fact_id,
                created_fact_id,
                to_json(superseded_ids),
                to_json(rejected_ids),
                note,
                to_json(evidence),
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM requirement_decisions WHERE project_id = ? AND id = ?",
            (project_id, decision_id),
        ).fetchone()
        conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        if owns_connection:
            conn.commit()
        return dict(row)
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        raise
    finally:
        if owns_connection:
            conn.close()


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
