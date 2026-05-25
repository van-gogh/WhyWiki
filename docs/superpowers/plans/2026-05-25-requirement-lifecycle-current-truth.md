# Requirement Lifecycle Current Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first WhyWiki requirement lifecycle slice so resolved conflicts update a structured current requirement set, preserve superseded evidence, and show localized status language in the UI and generated outputs.

**Architecture:** Keep the existing SQLite + FastAPI + vanilla static frontend. Add a narrow requirement lifecycle service on top of `facts`, `conflicts`, and evidence pointers; store human conflict decisions in a small append-only table; derive source material status from requirement facts instead of rewriting original files. UI and generated text must use shared localization helpers so Chinese mode shows Chinese status labels and English mode shows English labels.

**Tech Stack:** Python stdlib SQLite, FastAPI/Pydantic, existing WhyWiki service modules, vanilla JavaScript, existing i18n dictionary, pytest, static asset tests.

---

## Scope Check

The approved spec touches persistence, API, generated Wiki/Ask output, and Web UI. This plan keeps it as one vertical product slice because each task builds on the same lifecycle model and produces a working behavior incrementally:

1. Store lifecycle fields and decision records.
2. Expose current requirement snapshots.
3. Resolve requirement conflicts with explicit user decisions.
4. Show localized lifecycle language in UI.
5. Use current truth in Wiki, handover, Ask, and docs.

This plan does not add roadmap management, due dates, assignments, enterprise approval, or original file rewriting.

## File Structure

- Create `whywiki/services/lifecycle_labels.py`: shared status/action/source label keys and backend labels for generated text.
- Create `whywiki/services/requirement_lifecycle.py`: requirement snapshot, decision recording, conflict-to-requirement matching, and source status derivation.
- Modify `whywiki/db.py`: add `facts.superseded_by_fact_id`, `facts.review_note`, `facts.updated_at`, and `requirement_decisions`.
- Modify `whywiki/app.py`: add lifecycle request models and endpoints; extend fact update status validation.
- Modify `whywiki/services/wiki_engine.py`: render requirements from the current snapshot instead of raw fact rows.
- Modify `whywiki/services/handover.py`: use current requirement language and include recent decision records.
- Modify `whywiki/services/ask.py`: answer current-requirement questions from the current snapshot and explain superseded requirements.
- Modify `whywiki/static/i18n.js`: add lifecycle labels/actions in English and Chinese.
- Modify `whywiki/static/app.js`: add requirement status helpers, snapshot loading, source status badges, and conflict decision controls.
- Modify `whywiki/static/styles.css`: add visual states for current, superseded, historical, source outdated, and decision controls.
- Modify tests:
  - `tests/test_schema_migration.py`
  - `tests/test_api_surface.py`
  - `tests/test_evidence_outputs.py`
  - `tests/test_web_assets.py`
  - `tests/test_requirement_lifecycle.py`
- Modify docs:
  - `docs/FEATURE_STATUS.md`
  - `docs/ui_ux_guidelines.md`
  - `README.md`
  - `README.zh-CN.md`

---

### Task 1: Lifecycle Schema And Label Foundation

**Files:**
- Modify: `whywiki/db.py`
- Create: `whywiki/services/lifecycle_labels.py`
- Test: `tests/test_schema_migration.py`

- [ ] **Step 1: Write failing schema migration tests**

Add to `tests/test_schema_migration.py`:

```python
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
```

Add to `tests/test_schema_migration.py::test_init_db_is_idempotent`:

```python
    assert "superseded_by_fact_id" in columns(conn, "facts")
    assert "requirement_decisions" in {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
```

- [ ] **Step 2: Run the failing schema tests**

Run:

```bash
python -m pytest tests/test_schema_migration.py::test_init_db_adds_requirement_lifecycle_fields tests/test_schema_migration.py::test_init_db_is_idempotent -q
```

Expected: first test fails because lifecycle columns and `requirement_decisions` are missing.

- [ ] **Step 3: Add lifecycle schema**

In `whywiki/db.py`, update `apply_migrations`:

```python
    ensure_column(conn, "facts", "superseded_by_fact_id", "TEXT DEFAULT ''")
    ensure_column(conn, "facts", "review_note", "TEXT DEFAULT ''")
    ensure_column(conn, "facts", "updated_at", "TEXT DEFAULT ''")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_decisions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            conflict_id TEXT DEFAULT '',
            action TEXT NOT NULL,
            accepted_fact_id TEXT DEFAULT '',
            created_fact_id TEXT DEFAULT '',
            superseded_fact_ids_json TEXT DEFAULT '[]',
            rejected_fact_ids_json TEXT DEFAULT '[]',
            reason TEXT DEFAULT '',
            evidence_json TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requirement_decisions_project ON requirement_decisions(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requirement_decisions_conflict ON requirement_decisions(project_id, conflict_id)")

    conn.execute("UPDATE facts SET updated_at = created_at WHERE updated_at = ''")
    conn.execute("UPDATE schema_version SET version = 5")
```

Keep existing table creation unchanged, then rely on migrations so old databases upgrade safely.

- [ ] **Step 4: Create lifecycle label helper**

Create `whywiki/services/lifecycle_labels.py`:

```python
from __future__ import annotations

from typing import Literal

Language = Literal["zh-CN", "en-US"]

SUPPORTED_LANGUAGES = {"zh-CN", "en-US"}

REQUIREMENT_STATUS_LABELS = {
    "candidate": {"zh-CN": "候选需求", "en-US": "Candidate"},
    "needs_review": {"zh-CN": "待确认", "en-US": "Needs review"},
    "current": {"zh-CN": "当前有效", "en-US": "Current"},
    "confirmed": {"zh-CN": "已确认", "en-US": "Confirmed"},
    "superseded": {"zh-CN": "已被替代", "en-US": "Superseded"},
    "rejected": {"zh-CN": "已拒绝", "en-US": "Rejected"},
    "historical": {"zh-CN": "历史参考", "en-US": "Historical"},
    "conflicting": {"zh-CN": "存在冲突", "en-US": "Conflicting"},
    "unknown": {"zh-CN": "待判断", "en-US": "Unknown"},
}

SOURCE_STATUS_LABELS = {
    "active": {"zh-CN": "当前可信", "en-US": "Active"},
    "partially_outdated": {"zh-CN": "部分过期", "en-US": "Partially outdated"},
    "outdated": {"zh-CN": "已过期", "en-US": "Outdated"},
    "conflicting": {"zh-CN": "存在冲突", "en-US": "Conflicting"},
    "reference_only": {"zh-CN": "历史参考", "en-US": "Reference only"},
}

DECISION_ACTION_LABELS = {
    "accept_fact": {"zh-CN": "接受为当前需求", "en-US": "Accept as current"},
    "merge_requirement": {"zh-CN": "合并为新需求", "en-US": "Merge into new requirement"},
    "mark_outdated": {"zh-CN": "标记为已过期", "en-US": "Mark outdated"},
    "leave_for_later": {"zh-CN": "暂不处理", "en-US": "Leave for later"},
    "ignore_conflict": {"zh-CN": "忽略此冲突", "en-US": "Ignore this conflict"},
}


def normalize_language(language: str | None) -> Language:
    return "en-US" if language == "en-US" else "zh-CN"


def label(group: dict[str, dict[str, str]], key: str, language: str | None = None, fallback: str = "") -> str:
    lang = normalize_language(language)
    values = group.get(key)
    if values is None and fallback:
        values = group.get(fallback)
    if not values:
        return key
    return values[lang]


def requirement_status_label(status: str, language: str | None = None) -> str:
    return label(REQUIREMENT_STATUS_LABELS, status or "unknown", language, "unknown")


def source_status_label(status: str, language: str | None = None) -> str:
    values = SOURCE_STATUS_LABELS.get(status or "active", SOURCE_STATUS_LABELS["active"])
    return values[normalize_language(language)]


def decision_action_label(action: str, language: str | None = None) -> str:
    values = DECISION_ACTION_LABELS.get(action or "leave_for_later", DECISION_ACTION_LABELS["leave_for_later"])
    return values[normalize_language(language)]
```

- [ ] **Step 5: Run schema tests**

Run:

```bash
python -m pytest tests/test_schema_migration.py -q
```

Expected: schema migration tests pass.

- [ ] **Step 6: Commit**

```bash
git add whywiki/db.py whywiki/services/lifecycle_labels.py tests/test_schema_migration.py
git commit -m "feat: add requirement lifecycle schema"
```

---

### Task 2: Requirement Snapshot Service

**Files:**
- Create: `whywiki/services/requirement_lifecycle.py`
- Test: `tests/test_requirement_lifecycle.py`

- [ ] **Step 1: Write failing snapshot service tests**

Create `tests/test_requirement_lifecycle.py`:

```python
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
    insert_requirement(conn, project_id, "fact_current", "支持离线缓存", "src_new", "docs/requirements_v2.md", "confirmed", "current")
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
    insert_requirement(conn, project_id, "fact_review", "需要确认预算限制", "src_new", "docs/requirements_v2.md", "needs_review", "unknown")

    snapshot = build_requirement_snapshot(project_id, conn)

    assert [item["id"] for item in snapshot["current"]] == ["fact_current"]
    assert [item["id"] for item in snapshot["needs_review"]] == ["fact_review"]
    assert [item["id"] for item in snapshot["superseded"]] == ["fact_old"]
    assert snapshot["superseded"][0]["superseded_by_fact_id"] == "fact_current"
    assert snapshot["source_statuses"]["src_old"]["status"] == "outdated"
    assert snapshot["source_statuses"]["src_new"]["status"] == "active"
```

- [ ] **Step 2: Run failing snapshot test**

Run:

```bash
python -m pytest tests/test_requirement_lifecycle.py::test_snapshot_groups_current_review_and_superseded_requirements -q
```

Expected: import fails because `requirement_lifecycle.py` does not exist.

- [ ] **Step 3: Implement snapshot service**

Create `whywiki/services/requirement_lifecycle.py`:

```python
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from ..db import connect, rows_to_dicts
from ..utils import from_json
from .lifecycle_labels import requirement_status_label, source_status_label

CURRENT_VALIDITY = {"current"}
REVIEW_STATUSES = {"candidate", "needs_review"}
SUPERSEDED_VALIDITY = {"superseded", "outdated"}
HISTORICAL_VALIDITY = {"historical"}
REJECTED_STATUSES = {"rejected"}


def row_value(row: sqlite3.Row | dict[str, Any], key: str, default: Any = "") -> Any:
    if isinstance(row, sqlite3.Row):
        return row[key] if key in row.keys() else default
    return row.get(key, default)


def requirement_lifecycle_status(row: sqlite3.Row | dict[str, Any]) -> str:
    status = row_value(row, "status", "")
    validity = row_value(row, "validity_status", "")
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


def fact_to_requirement(row: sqlite3.Row, language: str | None = None) -> dict[str, Any]:
    item = dict(row)
    item["evidence"] = from_json(row["evidence_json"], [])
    item["lifecycle_status"] = requirement_lifecycle_status(row)
    item["lifecycle_label"] = requirement_status_label(item["lifecycle_status"], language)
    return item


def source_ids_for_requirement(item: dict[str, Any]) -> set[str]:
    ids = set()
    for evidence in item.get("evidence", []):
        source_id = evidence.get("source_id")
        if source_id:
            ids.add(source_id)
    return ids


def derive_source_statuses(sources: list[dict[str, Any]], requirements: list[dict[str, Any]], language: str | None = None) -> dict[str, dict[str, Any]]:
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for requirement in requirements:
        for source_id in source_ids_for_requirement(requirement):
            by_source[source_id].append(requirement)

    result = {}
    for source in sources:
        source_id = source["id"]
        rows = by_source.get(source_id, [])
        statuses = {row["lifecycle_status"] for row in rows}
        if not rows:
            status = "active"
        elif statuses <= {"superseded", "rejected", "historical"}:
            status = "outdated"
        elif statuses & {"superseded", "rejected", "historical"}:
            status = "partially_outdated"
        elif statuses & {"conflicting"}:
            status = "conflicting"
        else:
            status = "active"
        result[source_id] = {
            "source_id": source_id,
            "path": source["path"],
            "status": status,
            "label": source_status_label(status, language),
            "affected_requirements": len(rows),
        }
    return result


def build_requirement_snapshot(project_id: str, conn: sqlite3.Connection | None = None, language: str | None = None) -> dict[str, Any]:
    close = conn is None
    conn = conn or connect()
    requirements = [
        fact_to_requirement(row, language)
        for row in conn.execute(
            """
            SELECT * FROM facts
            WHERE project_id = ? AND fact_type = 'requirement'
            ORDER BY created_at DESC, confidence DESC
            """,
            (project_id,),
        ).fetchall()
    ]
    sources = rows_to_dicts(conn.execute("SELECT * FROM sources WHERE project_id = ? ORDER BY path", (project_id,)).fetchall())
    decisions = rows_to_dicts(
        conn.execute(
            "SELECT * FROM requirement_decisions WHERE project_id = ? ORDER BY created_at DESC LIMIT 20",
            (project_id,),
        ).fetchall()
    )
    open_conflicts = rows_to_dicts(
        conn.execute(
            "SELECT * FROM conflicts WHERE project_id = ? AND status = 'open' ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
    )

    grouped = {
        "current": [],
        "needs_review": [],
        "superseded": [],
        "historical": [],
        "rejected": [],
        "conflicting": [],
    }
    for requirement in requirements:
        status = requirement["lifecycle_status"]
        if status in {"current", "confirmed"}:
            grouped["current"].append(requirement)
        elif status in {"needs_review", "candidate"}:
            grouped["needs_review"].append(requirement)
        elif status in grouped:
            grouped[status].append(requirement)
        else:
            grouped["needs_review"].append(requirement)

    snapshot = {
        **grouped,
        "decisions": decisions,
        "open_conflicts": open_conflicts,
        "source_statuses": derive_source_statuses(sources, requirements, language),
        "metrics": {
            "current": len(grouped["current"]),
            "needs_review": len(grouped["needs_review"]),
            "superseded": len(grouped["superseded"]),
            "historical": len(grouped["historical"]),
            "open_conflicts": len(open_conflicts),
        },
    }
    if close:
        conn.close()
    return snapshot
```

- [ ] **Step 4: Run snapshot service tests**

Run:

```bash
python -m pytest tests/test_requirement_lifecycle.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add whywiki/services/requirement_lifecycle.py tests/test_requirement_lifecycle.py
git commit -m "feat: derive requirement truth snapshot"
```

---

### Task 3: Requirement Snapshot API And Source Statuses

**Files:**
- Modify: `whywiki/app.py`
- Test: `tests/test_api_surface.py`

- [ ] **Step 1: Write failing API tests**

Add to `tests/test_api_surface.py`:

```python
def test_requirement_snapshot_api_groups_current_and_superseded_requirements(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Lifecycle API Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    ingest_path(project["id"], root)
    build_project(project["id"])

    facts = [fact for fact in client.get(f"/api/projects/{project['id']}/facts").json() if fact["fact_type"] == "requirement"]
    assert len(facts) >= 2
    winner, old = facts[0], facts[1]
    assert client.patch(
        f"/api/projects/{project['id']}/facts/{winner['id']}",
        json={"status": "confirmed", "validity_status": "current"},
    ).status_code == 200
    assert client.patch(
        f"/api/projects/{project['id']}/facts/{old['id']}",
        json={"status": "confirmed", "validity_status": "superseded", "superseded_by_fact_id": winner["id"]},
    ).status_code == 200

    response = client.get(f"/api/projects/{project['id']}/requirements/snapshot?language=zh-CN")

    assert response.status_code == 200
    payload = response.json()
    assert any(item["id"] == winner["id"] and item["lifecycle_label"] == "当前有效" for item in payload["current"])
    assert any(item["id"] == old["id"] and item["lifecycle_label"] == "已被替代" for item in payload["superseded"])
    assert payload["source_statuses"]
```

- [ ] **Step 2: Run failing API test**

Run:

```bash
python -m pytest tests/test_api_surface.py::test_requirement_snapshot_api_groups_current_and_superseded_requirements -q
```

Expected: fails because `/requirements/snapshot` and extended fact update payload do not exist.

- [ ] **Step 3: Extend fact update request and endpoint**

In `whywiki/app.py`, import snapshot service:

```python
from .services.requirement_lifecycle import build_requirement_snapshot
```

Replace `FactStatusRequest` with:

```python
class FactStatusRequest(BaseModel):
    status: str
    validity_status: str | None = None
    superseded_by_fact_id: str | None = None
    review_note: str | None = None
```

Replace allowed fact status logic inside `api_update_fact`:

```python
    allowed_statuses = {"candidate", "confirmed", "needs_review", "rejected"}
    allowed_validity = {"unknown", "current", "outdated", "conflicting", "superseded", "historical"}
    if req.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Invalid fact status")
    if req.validity_status is not None and req.validity_status not in allowed_validity:
        raise HTTPException(status_code=400, detail="Invalid fact validity status")
```

Replace the update block with:

```python
        next_validity = req.validity_status
        if next_validity is None:
            next_validity = "current" if req.status == "confirmed" else "unknown"
        conn.execute(
            """
            UPDATE facts
            SET status = ?, validity_status = ?, superseded_by_fact_id = ?, review_note = ?, updated_at = datetime('now')
            WHERE project_id = ? AND id = ?
            """,
            (
                req.status,
                next_validity,
                req.superseded_by_fact_id or "",
                req.review_note or "",
                project_id,
                fact_id,
            ),
        )
```

- [ ] **Step 4: Add snapshot endpoint**

In `whywiki/app.py`, add after `api_list_facts`:

```python
@app.get("/api/projects/{project_id}/requirements/snapshot")
def api_requirement_snapshot(project_id: str, language: str = "zh-CN") -> dict:
    require_workspace_read_if_configured(project_id)
    with connect() as conn:
        return build_requirement_snapshot(project_id, conn, language)
```

- [ ] **Step 5: Run API tests**

Run:

```bash
python -m pytest tests/test_api_surface.py::test_requirement_snapshot_api_groups_current_and_superseded_requirements tests/test_api_surface.py::test_fact_status_update_persists_for_review_workflow -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add whywiki/app.py tests/test_api_surface.py
git commit -m "feat: expose requirement truth snapshot"
```

---

### Task 4: Conflict Decision API

**Files:**
- Modify: `whywiki/services/requirement_lifecycle.py`
- Modify: `whywiki/app.py`
- Test: `tests/test_requirement_lifecycle.py`
- Test: `tests/test_api_surface.py`

- [ ] **Step 1: Write failing service test for accepting a fact**

Add to `tests/test_requirement_lifecycle.py`:

```python
from whywiki.services.requirement_lifecycle import record_requirement_decision


def test_accept_fact_decision_marks_winner_current_and_old_fact_superseded(tmp_path):
    conn = sqlite3.connect(tmp_path / "whywiki.db")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    project_id = insert_project(conn)
    insert_source(conn, project_id, "src_new", "docs/requirements_v2.md")
    insert_source(conn, project_id, "src_old", "docs/requirements_v1.md")
    insert_requirement(conn, project_id, "fact_new", "支持离线缓存", "src_new", "docs/requirements_v2.md")
    insert_requirement(conn, project_id, "fact_old", "不做离线缓存", "src_old", "docs/requirements_v1.md")
    conn.execute(
        """
        INSERT INTO conflicts(id, project_id, conflict_type, title, description, evidence_json, severity, status, created_at)
        VALUES ('conf_1', ?, 'requirement_mismatch', '离线缓存冲突', '新旧需求不一致', '[]', 'high', 'open', ?)
        """,
        (project_id, now_iso()),
    )

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

    assert decision["action"] == "accept_fact"
    new_row = conn.execute("SELECT status, validity_status FROM facts WHERE id = 'fact_new'").fetchone()
    old_row = conn.execute("SELECT validity_status, superseded_by_fact_id FROM facts WHERE id = 'fact_old'").fetchone()
    conflict = conn.execute("SELECT status FROM conflicts WHERE id = 'conf_1'").fetchone()
    assert dict(new_row) == {"status": "confirmed", "validity_status": "current"}
    assert dict(old_row) == {"validity_status": "superseded", "superseded_by_fact_id": "fact_new"}
    assert conflict["status"] == "resolved"
```

- [ ] **Step 2: Run failing service decision test**

Run:

```bash
python -m pytest tests/test_requirement_lifecycle.py::test_accept_fact_decision_marks_winner_current_and_old_fact_superseded -q
```

Expected: fails because `record_requirement_decision` does not exist.

- [ ] **Step 3: Implement decision recording**

Add to `whywiki/services/requirement_lifecycle.py`:

```python
from ..utils import new_id, now_iso, to_json

DECISION_ACTIONS = {"accept_fact", "merge_requirement", "mark_outdated", "leave_for_later", "ignore_conflict"}


def requirement_evidence(conn: sqlite3.Connection, project_id: str, fact_id: str) -> list[dict[str, Any]]:
    row = conn.execute(
        "SELECT evidence_json FROM facts WHERE project_id = ? AND id = ?",
        (project_id, fact_id),
    ).fetchone()
    return from_json(row["evidence_json"], []) if row else []


def create_merged_requirement(conn: sqlite3.Connection, project_id: str, statement: str, source_fact_ids: list[str]) -> str:
    evidence = []
    for fact_id in source_fact_ids:
        evidence.extend(requirement_evidence(conn, project_id, fact_id))
    created_id = new_id("fact")
    conn.execute(
        """
        INSERT INTO facts(
            id, project_id, fact_type, statement, evidence_json, status, confidence,
            created_at, validity_status, superseded_by_fact_id, review_note, updated_at
        )
        VALUES (?, ?, 'requirement', ?, ?, 'confirmed', 1.0, ?, 'current', '', '', ?)
        """,
        (created_id, project_id, statement.strip(), to_json(evidence), now_iso(), now_iso()),
    )
    return created_id


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

    close = conn is None
    conn = conn or connect()
    superseded_fact_ids = superseded_fact_ids or []
    rejected_fact_ids = rejected_fact_ids or []
    created_fact_id = ""

    if action == "accept_fact":
        if not accepted_fact_id:
            raise ValueError("accepted_fact_id is required for accept_fact")
        conn.execute(
            "UPDATE facts SET status = 'confirmed', validity_status = 'current', superseded_by_fact_id = '', review_note = ?, updated_at = ? WHERE project_id = ? AND id = ?",
            (reason, now_iso(), project_id, accepted_fact_id),
        )
        for fact_id in superseded_fact_ids:
            conn.execute(
                "UPDATE facts SET status = 'confirmed', validity_status = 'superseded', superseded_by_fact_id = ?, review_note = ?, updated_at = ? WHERE project_id = ? AND id = ?",
                (accepted_fact_id, reason, now_iso(), project_id, fact_id),
            )
    elif action == "merge_requirement":
        source_fact_ids = [accepted_fact_id, *superseded_fact_ids]
        source_fact_ids = [fact_id for fact_id in source_fact_ids if fact_id]
        if not created_statement.strip() or not source_fact_ids:
            raise ValueError("created_statement and source fact ids are required for merge_requirement")
        created_fact_id = create_merged_requirement(conn, project_id, created_statement, source_fact_ids)
        for fact_id in source_fact_ids:
            conn.execute(
                "UPDATE facts SET status = 'confirmed', validity_status = 'superseded', superseded_by_fact_id = ?, review_note = ?, updated_at = ? WHERE project_id = ? AND id = ?",
                (created_fact_id, reason, now_iso(), project_id, fact_id),
            )
    elif action == "mark_outdated":
        target_ids = [accepted_fact_id, *superseded_fact_ids, *rejected_fact_ids]
        for fact_id in {fact_id for fact_id in target_ids if fact_id}:
            conn.execute(
                "UPDATE facts SET status = 'rejected', validity_status = 'historical', review_note = ?, updated_at = ? WHERE project_id = ? AND id = ?",
                (reason, now_iso(), project_id, fact_id),
            )
    elif action == "ignore_conflict":
        conn.execute("UPDATE conflicts SET status = 'ignored' WHERE project_id = ? AND id = ?", (project_id, conflict_id))
    elif action == "leave_for_later":
        conn.execute("UPDATE conflicts SET status = 'open' WHERE project_id = ? AND id = ?", (project_id, conflict_id))

    if action not in {"leave_for_later"}:
        next_status = "ignored" if action == "ignore_conflict" else "resolved"
        conn.execute("UPDATE conflicts SET status = ? WHERE project_id = ? AND id = ?", (next_status, project_id, conflict_id))

    decision_id = new_id("decision")
    evidence = []
    for fact_id in [accepted_fact_id, created_fact_id, *superseded_fact_ids, *rejected_fact_ids]:
        if fact_id:
            evidence.extend(requirement_evidence(conn, project_id, fact_id))
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
            to_json(superseded_fact_ids),
            to_json(rejected_fact_ids),
            reason.strip(),
            to_json(evidence),
            now_iso(),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM requirement_decisions WHERE id = ?", (decision_id,)).fetchone()
    if close:
        conn.close()
    return dict(row)
```

- [ ] **Step 4: Write failing API decision test**

Add to `tests/test_api_surface.py`:

```python
def test_conflict_decision_api_records_current_requirement_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    client = TestClient(app)
    project = create_project("Decision API Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    ingest_path(project["id"], root)
    build_project(project["id"])
    facts = [fact for fact in client.get(f"/api/projects/{project['id']}/facts").json() if fact["fact_type"] == "requirement"]
    conflicts = client.get(f"/api/projects/{project['id']}/conflicts").json()
    assert len(facts) >= 2
    assert conflicts

    response = client.post(
        f"/api/projects/{project['id']}/conflicts/{conflicts[0]['id']}/decision",
        json={
            "action": "accept_fact",
            "accepted_fact_id": facts[0]["id"],
            "superseded_fact_ids": [facts[1]["id"]],
            "reason": "新版需求覆盖旧版需求",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "accept_fact"
    snapshot = client.get(f"/api/projects/{project['id']}/requirements/snapshot").json()
    assert any(item["id"] == facts[0]["id"] for item in snapshot["current"])
    assert any(item["id"] == facts[1]["id"] for item in snapshot["superseded"])
```

- [ ] **Step 5: Add API request model and endpoint**

In `whywiki/app.py`, import:

```python
from .services.requirement_lifecycle import build_requirement_snapshot, record_requirement_decision
```

Add request model:

```python
class RequirementDecisionRequest(BaseModel):
    action: str
    accepted_fact_id: str = ""
    superseded_fact_ids: list[str] = Field(default_factory=list)
    rejected_fact_ids: list[str] = Field(default_factory=list)
    created_statement: str = ""
    reason: str = ""
```

Add endpoint after `api_update_conflict`:

```python
@app.post("/api/projects/{project_id}/conflicts/{conflict_id}/decision")
def api_record_requirement_decision(project_id: str, conflict_id: str, req: RequirementDecisionRequest) -> dict:
    require_review_access_if_configured(project_id)
    try:
        return record_requirement_decision(
            project_id,
            conflict_id=conflict_id,
            action=req.action,
            accepted_fact_id=req.accepted_fact_id,
            superseded_fact_ids=req.superseded_fact_ids,
            rejected_fact_ids=req.rejected_fact_ids,
            created_statement=req.created_statement,
            reason=req.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 6: Run decision tests**

Run:

```bash
python -m pytest tests/test_requirement_lifecycle.py::test_accept_fact_decision_marks_winner_current_and_old_fact_superseded tests/test_api_surface.py::test_conflict_decision_api_records_current_requirement_choice -q
```

Expected: tests pass.

- [ ] **Step 7: Commit**

```bash
git add whywiki/services/requirement_lifecycle.py whywiki/app.py tests/test_requirement_lifecycle.py tests/test_api_surface.py
git commit -m "feat: record requirement conflict decisions"
```

---

### Task 5: Localized Web Lifecycle UI

**Files:**
- Modify: `whywiki/static/i18n.js`
- Modify: `whywiki/static/app.js`
- Modify: `whywiki/static/styles.css`
- Test: `tests/test_web_assets.py`

- [ ] **Step 1: Write failing static asset tests**

Add to `tests/test_web_assets.py`:

```python
def test_i18n_contains_requirement_lifecycle_terms_for_each_language():
    languages = parse_i18n_keys()
    keys = {
        "requirement.status.current",
        "requirement.status.candidate",
        "requirement.status.needsReview",
        "requirement.status.confirmed",
        "requirement.status.superseded",
        "requirement.status.rejected",
        "requirement.status.historical",
        "requirement.status.conflicting",
        "source.status.active",
        "source.status.partiallyOutdated",
        "source.status.outdated",
        "source.status.conflicting",
        "source.status.referenceOnly",
        "action.acceptAsCurrent",
        "action.mergeRequirement",
        "action.markOutdated",
        "action.leaveForLater",
        "action.ignoreThisConflict",
        "decision.reasonPlaceholder",
    }
    for language, language_keys in languages.items():
        assert not keys - language_keys, f"{language} missing keys: {sorted(keys - language_keys)}"

    content = (STATIC / "i18n.js").read_text(encoding="utf-8")
    assert '"requirement.status.current": "当前有效"' in content
    assert '"requirement.status.superseded": "已被替代"' in content
    assert '"requirement.status.current": "Current"' in content
    assert '"requirement.status.superseded": "Superseded"' in content


def test_app_js_uses_snapshot_and_localized_lifecycle_labels():
    content = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    for symbol in (
        "function requirementLifecycleStatus",
        "function requirementStatusLabel",
        "function renderRequirementSnapshot",
        "function submitRequirementDecision",
        "/api/projects/${projectId}/requirements/snapshot",
        "/api/projects/${projectId}/conflicts/${conflictId}/decision",
    ):
        assert symbol in content
    assert "fieldValue(conflict.status)" not in content
    assert ".status-badge-current" in css
    assert ".status-badge-superseded" in css
    assert ".source-status-partially_outdated" in css
```

- [ ] **Step 2: Run failing static tests**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_i18n_contains_requirement_lifecycle_terms_for_each_language tests/test_web_assets.py::test_app_js_uses_snapshot_and_localized_lifecycle_labels -q
```

Expected: tests fail because lifecycle i18n keys and UI helpers are missing.

- [ ] **Step 3: Add i18n lifecycle terms**

In `whywiki/static/i18n.js`, add English entries:

```javascript
    "requirement.status.current": "Current",
    "requirement.status.candidate": "Candidate",
    "requirement.status.needsReview": "Needs review",
    "requirement.status.confirmed": "Confirmed",
    "requirement.status.superseded": "Superseded",
    "requirement.status.rejected": "Rejected",
    "requirement.status.historical": "Historical",
    "requirement.status.conflicting": "Conflicting",
    "source.status.active": "Active",
    "source.status.partiallyOutdated": "Partially outdated",
    "source.status.outdated": "Outdated",
    "source.status.conflicting": "Conflicting",
    "source.status.referenceOnly": "Reference only",
    "action.acceptAsCurrent": "Accept as current",
    "action.mergeRequirement": "Merge into new requirement",
    "action.markOutdated": "Mark outdated",
    "action.leaveForLater": "Leave for later",
    "action.ignoreThisConflict": "Ignore this conflict",
    "decision.reasonPlaceholder": "Why is this the current requirement?",
```

Add Chinese entries:

```javascript
    "requirement.status.current": "当前有效",
    "requirement.status.candidate": "候选需求",
    "requirement.status.needsReview": "待确认",
    "requirement.status.confirmed": "已确认",
    "requirement.status.superseded": "已被替代",
    "requirement.status.rejected": "已拒绝",
    "requirement.status.historical": "历史参考",
    "requirement.status.conflicting": "存在冲突",
    "source.status.active": "当前可信",
    "source.status.partiallyOutdated": "部分过期",
    "source.status.outdated": "已过期",
    "source.status.conflicting": "存在冲突",
    "source.status.referenceOnly": "历史参考",
    "action.acceptAsCurrent": "接受为当前需求",
    "action.mergeRequirement": "合并为新需求",
    "action.markOutdated": "标记为已过期",
    "action.leaveForLater": "暂不处理",
    "action.ignoreThisConflict": "忽略此冲突",
    "decision.reasonPlaceholder": "为什么以这条需求为准？",
```

- [ ] **Step 4: Add frontend lifecycle helpers**

In `whywiki/static/app.js`, near `factStatusKind`, add:

```javascript
function requirementLifecycleStatus(fact = {}) {
  if (fact.lifecycle_status === "needs_review") return "needsReview";
  if (fact.lifecycle_status) return fact.lifecycle_status;
  if (fact.validity_status === "current") return "current";
  if (fact.validity_status === "superseded") return "superseded";
  if (fact.validity_status === "historical") return "historical";
  if (fact.validity_status === "conflicting") return "conflicting";
  if (fact.status === "rejected" || fact.validity_status === "outdated") return "rejected";
  if (fact.status === "needs_review") return "needsReview";
  if (fact.status === "confirmed") return "confirmed";
  return "candidate";
}

function requirementStatusLabel(fact = {}) {
  const status = requirementLifecycleStatus(fact);
  const keyMap = {
    needsReview: "requirement.status.needsReview",
    current: "requirement.status.current",
    candidate: "requirement.status.candidate",
    confirmed: "requirement.status.confirmed",
    superseded: "requirement.status.superseded",
    rejected: "requirement.status.rejected",
    historical: "requirement.status.historical",
    conflicting: "requirement.status.conflicting",
  };
  return t(keyMap[status] || "requirement.status.candidate");
}

function sourceMemoryStatusLabel(status = "active") {
  const keyMap = {
    active: "source.status.active",
    partially_outdated: "source.status.partiallyOutdated",
    outdated: "source.status.outdated",
    conflicting: "source.status.conflicting",
    reference_only: "source.status.referenceOnly",
  };
  return t(keyMap[status] || "source.status.active");
}
```

Update `factStatusKind` and `factStatusLabel` to delegate:

```javascript
function factStatusKind(fact) {
  return requirementLifecycleStatus(fact).replace("needsReview", "needs-review");
}

function factStatusLabel(fact) {
  return requirementStatusLabel(fact);
}
```

- [ ] **Step 5: Add snapshot renderer**

In `whywiki/static/app.js`, add:

```javascript
async function loadRequirementSnapshot(projectId) {
  return api(`/api/projects/${projectId}/requirements/snapshot?language=${encodeURIComponent(currentLang)}`);
}

function renderRequirementSnapshot(snapshot) {
  const wrapper = createElement("div", "requirement-snapshot");
  const groups = [
    ["current", "requirement.status.current"],
    ["needs_review", "requirement.status.needsReview"],
    ["superseded", "requirement.status.superseded"],
    ["historical", "requirement.status.historical"],
  ];
  groups.forEach(([key, labelKey]) => {
    const rows = snapshot[key] || [];
    const section = createElement("section", `requirement-snapshot-section requirement-snapshot-${key}`);
    section.append(createElement("h3", "", t(labelKey)));
    if (rows.length) {
      const grid = createElement("div", "fact-grid");
      rows.forEach((fact) => grid.append(renderFactCard(fact)));
      section.append(grid);
    } else {
      section.append(createElement("p", "muted", t("view.empty")));
    }
    wrapper.append(section);
  });
  return wrapper;
}
```

Update `renderFacts(projectId)`:

```javascript
async function renderFacts(projectId) {
  const snapshot = await loadRequirementSnapshot(projectId);
  const panel = createPanel(t("view.facts.title"));
  panel.append(createElement("p", "status-intro", t("status.subtitle")));
  panel.append(renderRequirementSnapshot(snapshot));
  return panel;
}
```

- [ ] **Step 6: Add conflict decision controls**

In `whywiki/static/app.js`, add:

```javascript
async function submitRequirementDecision(conflictId, payload) {
  const projectId = requireProject();
  if (!projectId) return null;
  return api(`/api/projects/${projectId}/conflicts/${conflictId}/decision`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

function selectableRequirementOptions(requirements = []) {
  return requirements.filter((item) => ["candidate", "needs_review", "confirmed", "current", "conflicting"].includes(requirementLifecycleStatus(item)));
}

function renderRequirementSelect(requirements, labelText, multiple = false) {
  const label = document.createElement("label");
  const text = createElement("span", "", labelText);
  const select = document.createElement("select");
  if (multiple) select.multiple = true;
  selectableRequirementOptions(requirements).forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.statement || item.id;
    select.append(option);
  });
  label.append(text, select);
  return { label, select };
}

function selectedOptions(select) {
  return Array.from(select.selectedOptions).map((option) => option.value).filter(Boolean);
}

function renderConflictDecisionControls(conflict, actions, requirements = []) {
  const controls = createElement("div", "decision-controls");
  const accepted = renderRequirementSelect(requirements, t("action.acceptAsCurrent"));
  const superseded = renderRequirementSelect(requirements, t("requirement.status.superseded"), true);
  const reason = document.createElement("input");
  reason.type = "text";
  reason.placeholder = t("decision.reasonPlaceholder");
  const accept = createActionButton(t("action.acceptAsCurrent"), "primary", () => {
    const acceptedFactId = accepted.select.value;
    if (!acceptedFactId) {
      actions.replaceChildren(renderOperationFeedback("error", t("view.error"), t("empty.facts.body")));
      return;
    }
    actions.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
    submitRequirementDecision(conflict.id, {
      action: "accept_fact",
      accepted_fact_id: acceptedFactId,
      superseded_fact_ids: selectedOptions(superseded.select).filter((id) => id !== acceptedFactId),
      reason: reason.value,
    }).then(() => loadView("review")).catch((error) => {
      actions.replaceChildren(renderOperationFeedback("error", t("view.error"), error.message));
    });
  });
  const later = createActionButton(t("action.leaveForLater"), "tertiary", () => {
    actions.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
    submitRequirementDecision(conflict.id, { action: "leave_for_later", reason: reason.value }).then(() => loadView("review")).catch((error) => {
      actions.replaceChildren(renderOperationFeedback("error", t("view.error"), error.message));
    });
  });
  const ignore = createActionButton(t("action.ignoreThisConflict"), "tertiary", () => {
    actions.replaceChildren(renderOperationFeedback("loading", t("view.loading")));
    submitRequirementDecision(conflict.id, { action: "ignore_conflict", reason: reason.value }).then(() => loadView("review")).catch((error) => {
      actions.replaceChildren(renderOperationFeedback("error", t("view.error"), error.message));
    });
  });
  controls.append(accepted.label, superseded.label, reason, accept, later, ignore);
  return controls;
}
```

In `renderConflictCard`, replace `fieldValue(conflict.status)` with localized status labels:

```javascript
    renderStatusBadge(conflict.status === "ignored" ? t("action.ignoreThisConflict") : t("requirement.status.conflicting"), conflict.status || "open")
```

Change `renderConflictCard(conflict)` to `renderConflictCard(conflict, requirements = [])`, then replace `actions.append(resolve, ignore);` with:

```javascript
  actions.append(renderConflictDecisionControls(conflict, actions, requirements));
```

Update `renderReview(projectId)` to fetch the snapshot and pass requirement choices into every conflict card:

```javascript
async function renderReview(projectId) {
  const [conflicts, facts, snapshot] = await Promise.all([
    api(`/api/projects/${projectId}/conflicts`),
    api(`/api/projects/${projectId}/facts`),
    loadRequirementSnapshot(projectId),
  ]);
  const panel = createPanel(t("review.title"));
  const intro = document.createElement("p");
  intro.className = "status-intro";
  intro.textContent = t("review.subtitle");
  panel.append(intro);

  const requirementChoices = [
    ...(snapshot.current || []),
    ...(snapshot.needs_review || []),
    ...(snapshot.conflicting || []),
  ];

  if (conflicts.length) {
    const grid = createElement("div", "conflict-grid");
    conflicts.forEach((conflict) => grid.append(renderConflictCard(conflict, requirementChoices)));
    appendSection(panel, t("view.conflicts.title"), grid);
  } else {
    appendSection(panel, t("view.conflicts.title"), renderEmptyState({
      title: t("empty.conflicts.title"),
      body: t("empty.conflicts.body"),
      kind: "conflicts",
    }));
  }

  const reviewFacts = facts.filter((fact) => fact.status === "needs_review" || fact.validity_status === "conflicting");
  appendSection(
    panel,
    t("view.facts.title"),
    reviewFacts.length ? renderStateCards(reviewFacts, 8) : renderEmptyState({
      title: t("empty.facts.title"),
      body: t("empty.facts.body"),
      kind: "facts",
    })
  );
  return panel;
}
```

Keep `updateConflictStatus` for compatibility with old code paths until no caller remains.

- [ ] **Step 7: Add lifecycle CSS**

In `whywiki/static/styles.css`, add:

```css
.requirement-snapshot {
  display: grid;
  gap: 18px;
}

.requirement-snapshot-section {
  display: grid;
  gap: 12px;
}

.status-badge-current,
.status-badge-confirmed {
  border-color: var(--confirmed);
  color: var(--confirmed);
}

.status-badge-superseded,
.status-badge-historical,
.source-status-partially_outdated,
.source-status-outdated {
  border-color: var(--stale);
  color: var(--stale);
}

.status-badge-rejected,
.status-badge-conflicting {
  border-color: var(--conflict);
  color: var(--conflict);
}

.decision-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.decision-controls input {
  min-width: min(260px, 100%);
  flex: 1 1 240px;
}
```

- [ ] **Step 8: Run static tests**

Run:

```bash
python -m pytest tests/test_web_assets.py::test_i18n_contains_requirement_lifecycle_terms_for_each_language tests/test_web_assets.py::test_app_js_uses_snapshot_and_localized_lifecycle_labels -q
```

Expected: tests pass.

- [ ] **Step 9: Commit**

```bash
git add whywiki/static/i18n.js whywiki/static/app.js whywiki/static/styles.css tests/test_web_assets.py
git commit -m "feat: localize requirement lifecycle UI"
```

---

### Task 6: Generated Snapshot, Handover, And Ask Behavior

**Files:**
- Modify: `whywiki/services/wiki_engine.py`
- Modify: `whywiki/services/handover.py`
- Modify: `whywiki/services/ask.py`
- Test: `tests/test_evidence_outputs.py`

- [ ] **Step 1: Write failing evidence output tests**

Add to `tests/test_evidence_outputs.py`:

```python
def test_requirements_wiki_uses_current_requirement_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    project = create_project("Snapshot Wiki Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    ingest_path(project["id"], root)
    build_project(project["id"])
    with connect() as conn:
        facts = conn.execute("SELECT * FROM facts WHERE project_id = ? AND fact_type = 'requirement' LIMIT 2", (project["id"],)).fetchall()
        conn.execute("UPDATE facts SET status = 'confirmed', validity_status = 'current' WHERE id = ?", (facts[0]["id"],))
        conn.execute("UPDATE facts SET status = 'confirmed', validity_status = 'superseded', superseded_by_fact_id = ? WHERE id = ?", (facts[0]["id"], facts[1]["id"]))
        build_wiki_pages(project["id"], conn)
        page = conn.execute("SELECT content FROM wiki_pages WHERE project_id = ? AND slug = 'requirements'", (project["id"],)).fetchone()["content"]

    assert "当前需求快照" in page
    assert "当前有效" in page
    assert "已被替代" in page
    assert facts[0]["statement"] in page
    assert facts[1]["statement"] in page


def test_ask_current_requirement_answer_explains_superseded_history(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    project = create_project("Ask Snapshot Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    ingest_path(project["id"], root)
    build_project(project["id"])
    with connect() as conn:
        facts = conn.execute("SELECT * FROM facts WHERE project_id = ? AND fact_type = 'requirement' LIMIT 2", (project["id"],)).fetchall()
        conn.execute("UPDATE facts SET status = 'confirmed', validity_status = 'current' WHERE id = ?", (facts[0]["id"],))
        conn.execute("UPDATE facts SET status = 'confirmed', validity_status = 'superseded', superseded_by_fact_id = ? WHERE id = ?", (facts[0]["id"], facts[1]["id"]))
        conn.commit()
        answer = ask_project(project["id"], "当前需求是什么？", conn)

    assert "当前有效需求" in answer["answer"]
    assert "已被替代" in answer["answer"]
    assert facts[0]["statement"] in answer["answer"]
```

Ensure imports include:

```python
from whywiki.db import connect
from whywiki.services.ask import ask_project
from whywiki.services.wiki_engine import build_wiki_pages
```

- [ ] **Step 2: Run failing output tests**

Run:

```bash
python -m pytest tests/test_evidence_outputs.py::test_requirements_wiki_uses_current_requirement_snapshot tests/test_evidence_outputs.py::test_ask_current_requirement_answer_explains_superseded_history -q
```

Expected: tests fail because wiki and Ask still use raw facts.

- [ ] **Step 3: Render current requirements snapshot in Wiki**

In `whywiki/services/wiki_engine.py`, import:

```python
from .requirement_lifecycle import build_requirement_snapshot
```

Replace requirements page generation:

```python
    pages["requirements"] = render_requirement_snapshot_page(project_id, conn)
```

Add:

```python
def render_requirement_snapshot_page(project_id: str, conn: sqlite3.Connection) -> str:
    snapshot = build_requirement_snapshot(project_id, conn, "zh-CN")
    lines = ["# 当前需求快照", ""]
    sections = [
        ("当前有效", snapshot["current"]),
        ("待确认", snapshot["needs_review"]),
        ("已被替代", snapshot["superseded"]),
        ("历史参考", snapshot["historical"]),
    ]
    for title, rows in sections:
        lines += [f"## {title}", ""]
        if not rows:
            lines += ["- 暂无。", ""]
            continue
        for fact in rows:
            evidence = fact.get("evidence", [])
            pointer = evidence[0].get("path", "unknown") if evidence else "unknown"
            lines.append(f"- {fact['statement']}")
            lines.append(f"  - 状态：{fact['lifecycle_label']}")
            lines.append(f"  - 证据：`{pointer}`")
            if fact.get("superseded_by_fact_id"):
                lines.append(f"  - 替代者：`{fact['superseded_by_fact_id']}`")
        lines.append("")
    if snapshot["open_conflicts"]:
        lines += ["## 未解决冲突", ""]
        for conflict in snapshot["open_conflicts"]:
            lines.append(f"- {conflict['title']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
```

- [ ] **Step 4: Update Ask current requirement behavior**

In `whywiki/services/ask.py`, import:

```python
from .requirement_lifecycle import build_requirement_snapshot
```

Add:

```python
CURRENT_REQUIREMENT_TERMS = ("当前需求", "有效需求", "需求是什么", "current requirement", "current requirements")


def has_current_requirement_intent(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in CURRENT_REQUIREMENT_TERMS)


def answer_current_requirement_question(project_id: str, question: str, conn: sqlite3.Connection) -> dict | None:
    if not has_current_requirement_intent(question):
        return None
    snapshot = build_requirement_snapshot(project_id, conn, "zh-CN")
    bullets = []
    evidence = []
    for item in snapshot["current"][:8]:
        item_evidence = item.get("evidence", [])
        path = item_evidence[0].get("path", "unknown") if item_evidence else "unknown"
        bullets.append(f"- {item['statement']}\n  - 状态：当前有效\n  - 证据：`{path}`")
        evidence.append({"kind": "fact", "id": item["id"], "path": path, "score": 5.0})
    if snapshot["superseded"]:
        bullets.append("\n历史材料中还有已被替代的需求，默认不作为当前开发依据：")
        for item in snapshot["superseded"][:5]:
            bullets.append(f"- {item['statement']}\n  - 状态：已被替代")
    if not bullets:
        return {
            "question": question,
            "answer": "当前还没有用户确认的有效需求。请先处理待确认需求或冲突。",
            "evidence": [],
        }
    answer = "我只能基于当前已摄入材料和用户裁决回答。当前有效需求如下：\n\n" + "\n".join(bullets)
    return {"question": question, "answer": answer, "evidence": evidence}
```

In `ask_project`, call this before generic retrieval and after conflict answer:

```python
    current_requirement_answer = answer_current_requirement_question(project_id, question, conn)
    if current_requirement_answer is not None:
        if close:
            conn.close()
        return current_requirement_answer
```

- [ ] **Step 5: Update handover current requirement section**

In `whywiki/services/handover.py`, use `build_requirement_snapshot(project_id, conn, "zh-CN")` for the current requirements section. The section should list current requirements first, then a short “最近裁决” list from snapshot decisions. Do not list superseded requirements as normal current requirements.

Use this rendering shape:

```python
lines.append("## 3. 当前需求 / 业务目标")
if snapshot["current"]:
    for item in snapshot["current"][:12]:
        lines.append(f"- {item['statement']}（{item['lifecycle_label']}）")
else:
    lines.append("- 当前还没有确认的有效需求。")
if snapshot["decisions"]:
    lines += ["", "最近裁决："]
    for decision in snapshot["decisions"][:5]:
        reason = decision["reason"] or "未填写原因"
        lines.append(f"- {decision['created_at']}：{reason}")
```

- [ ] **Step 6: Run output tests**

Run:

```bash
python -m pytest tests/test_evidence_outputs.py::test_requirements_wiki_uses_current_requirement_snapshot tests/test_evidence_outputs.py::test_ask_current_requirement_answer_explains_superseded_history -q
```

Expected: tests pass.

- [ ] **Step 7: Commit**

```bash
git add whywiki/services/wiki_engine.py whywiki/services/handover.py whywiki/services/ask.py tests/test_evidence_outputs.py
git commit -m "feat: generate current requirement snapshot outputs"
```

---

### Task 7: Product Documentation And Full Verification

**Files:**
- Modify: `docs/FEATURE_STATUS.md`
- Modify: `docs/ui_ux_guidelines.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: Update feature ledger**

In `docs/FEATURE_STATUS.md`, add or update rows:

```markdown
| Facts | 需求生命周期 | 已完成 | `fact_type=requirement` 支持当前有效、待确认、已被替代、已拒绝、历史参考等语义；内部枚举保留英文，用户界面通过 i18n 显示本地化状态。 |
| 冲突 | 需求冲突裁决记录 | 已完成 | 冲突解决会写入 `requirement_decisions`，胜出需求进入当前需求集，被淘汰需求保留为已被替代或历史参考。 |
| Wiki | 当前需求快照 | 已完成 | `requirements` Wiki 页面从结构化当前需求集生成，展示当前有效需求、已被替代需求、未解决冲突和证据。 |
| Web UI | 生命周期本地化状态 | 已完成 | 中文模式显示“当前有效 / 已被替代 / 待确认”等中文状态；英文模式显示对应英文状态，不在主 UI 暴露裸枚举。 |
```

Update the completion definition if needed with:

```markdown
9. 面向用户的状态、动作和错误提示必须遵守当前语言；内部枚举不能直接暴露到主 UI 或生成输出。
```

- [ ] **Step 2: Update UI guidelines**

In `docs/ui_ux_guidelines.md`, add a short rule under information source/status guidance:

```markdown
### Language-Specific Status Copy

User-facing status words, action labels, empty states, error recovery text, Wiki generated headings, handover headings, and Ask explanations must follow the selected product language.

- Chinese mode uses Chinese status labels such as 当前有效、待确认、已被替代、历史参考.
- English mode uses English status labels such as Current, Needs review, Superseded, Historical.
- Internal enum values such as `current`, `superseded`, and `needs_review` may appear in APIs, logs, tests, and developer diagnostics, but not in the main UI.
- Evidence excerpts, file paths, API endpoints, code symbols, and original document titles stay faithful to the source language.
```

- [ ] **Step 3: Update README pair**

In `README.md`, update feature bullets to mention current requirement snapshots and superseded history:

```markdown
- 🧭 **Current requirement snapshot** that separates current requirements from superseded historical requirements
- 📝 **Decision records** for conflict resolution, so old documents remain evidence without becoming current truth
```

In `README.zh-CN.md`, mirror the same section structure:

```markdown
- 🧭 **当前需求快照**，把当前有效需求和已被替代的历史需求分开
- 📝 **冲突裁决记录**，旧文档继续保留为证据，但不会被误当作当前真相
```

- [ ] **Step 4: Run required checks**

Run:

```bash
python -m compileall whywiki
python -m pytest -q
```

Expected:

- `compileall` exits 0.
- Full pytest exits 0. Existing FastAPI `on_event` warnings may remain.

- [ ] **Step 5: Optional browser verification**

If the local server is running at `http://127.0.0.1:8765/`, verify:

- 中文模式下需求卡片显示“当前有效 / 已被替代 / 待确认”。
- 英文模式下同一卡片显示 “Current / Superseded / Needs review”。
- 冲突卡片显示“接受为当前需求 / 合并为新需求 / 标记为已过期 / 暂不处理 / 忽略此冲突”。
- 来源页能显示“部分过期”或 “Partially outdated”。
- Ask “当前需求是什么？”不会把已被替代需求当作当前需求。

If no server is running, report that automated verification was performed and browser verification was not run.

- [ ] **Step 6: Commit docs and verification updates**

```bash
git add docs/FEATURE_STATUS.md docs/ui_ux_guidelines.md README.md README.zh-CN.md
git commit -m "docs: document requirement lifecycle behavior"
```

---

## Plan Self-Review

Spec coverage:

- Original materials are not rewritten: Task 2 derives source status from evidence; no task writes source files.
- Superseded requirements stay as evidence: Task 1 adds lifecycle fields; Task 2 and Task 4 keep superseded facts.
- Conflict decisions become project knowledge: Task 4 adds `requirement_decisions`.
- Current requirement snapshot exists as generated view: Task 2 builds it, Task 3 exposes it, Task 6 renders it.
- Ask/Wiki/handover use current truth: Task 6 covers all three.
- Chinese and English status copy rules are enforced: Task 1 backend labels and Task 5 frontend i18n.
- Documentation stays aligned: Task 7 updates feature ledger, UI guidelines, and README pair.

Scope boundaries:

- The plan does not add roadmap management, assignment, due dates, enterprise approval, or automatic source document edits.
- The conflict UI asks the user to choose the accepted requirement and superseded requirements before posting a decision, so it does not fake a success path.
- The decision API already supports accepted/superseded fact IDs, so additional conflict matching can improve defaults without another schema change.

Type consistency:

- Fact lifecycle uses `status` for review disposition and `validity_status` for current/superseded/historical truth state.
- `requirement_decisions.action` uses `accept_fact`, `merge_requirement`, `mark_outdated`, `leave_for_later`, and `ignore_conflict`.
- Snapshot API returns `current`, `needs_review`, `superseded`, `historical`, `rejected`, `conflicting`, `decisions`, `open_conflicts`, `source_statuses`, and `metrics`.

Verification commands:

- Focused tests after each task are listed in the task body.
- Final required checks are `python -m compileall whywiki` and `python -m pytest -q`.
