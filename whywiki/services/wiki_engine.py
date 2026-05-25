from __future__ import annotations

import sqlite3
from collections import defaultdict

from ..config import get_project_dir
from ..db import connect, init_db
from ..utils import from_json, new_id, now_iso
from .conflict_detector import detect_conflicts
from .fact_extractor import rebuild_facts
from .handover import generate_handover
from .lifecycle_labels import (
    conflict_severity_label,
    conflict_status_label,
    conflict_type_label,
    fact_status_label,
    fact_validity_label,
)
from .requirement_lifecycle import build_requirement_snapshot

PAGE_ORDER = [
    "overview",
    "requirements",
    "architecture",
    "api",
    "experiments",
    "deployment",
    "conflicts",
    "handover",
    "open-questions",
]


def build_project(project_id: str, conn: sqlite3.Connection | None = None) -> dict:
    close = conn is None
    conn = conn or connect()
    init_db(conn)

    fact_result = rebuild_facts(project_id, conn)
    conflict_result = detect_conflicts(project_id, conn)
    pages = build_wiki_pages(project_id, conn)

    conn.commit()
    if close:
        conn.close()
    return {
        "project_id": project_id,
        **fact_result,
        **conflict_result,
        "wiki_pages": list(pages.keys()),
    }


def build_wiki_pages(project_id: str, conn: sqlite3.Connection) -> dict[str, str]:
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    sources = conn.execute("SELECT * FROM sources WHERE project_id = ? ORDER BY path", (project_id,)).fetchall()
    facts = conn.execute("SELECT * FROM facts WHERE project_id = ? ORDER BY fact_type, confidence DESC", (project_id,)).fetchall()
    conflicts = conn.execute("SELECT * FROM conflicts WHERE project_id = ? ORDER BY severity DESC, created_at DESC", (project_id,)).fetchall()

    facts_by_type = defaultdict(list)
    for fact in facts:
        facts_by_type[fact["fact_type"]].append(fact)

    pages: dict[str, str] = {}
    pages["overview"] = render_overview(project, sources, facts, conflicts)
    pages["requirements"] = render_requirement_snapshot_page(project_id, conn)
    pages["architecture"] = render_fact_page("代码结构与架构", facts_by_type.get("code", []))
    pages["api"] = render_fact_page("接口信息", facts_by_type.get("api", []))
    pages["experiments"] = render_fact_page("实验、模型与数据", facts_by_type.get("experiment", []))
    pages["deployment"] = render_fact_page("运行与部署", facts_by_type.get("deployment", []))
    pages["conflicts"] = render_conflicts(conflicts)
    pages["handover"] = generate_handover(project_id, conn)
    pages["open-questions"] = render_open_questions(conflicts)

    wiki_dir = get_project_dir(project_id) / "wiki"
    for slug, content in pages.items():
        (wiki_dir / f"{slug}.md").write_text(content, encoding="utf-8")
        existing = conn.execute("SELECT id FROM wiki_pages WHERE project_id = ? AND slug = ?", (project_id, slug)).fetchone()
        now = now_iso()
        title = title_from_slug(slug)
        if existing:
            conn.execute(
                "UPDATE wiki_pages SET title = ?, content = ?, updated_at = ? WHERE id = ?",
                (title, content, now, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO wiki_pages(id, project_id, slug, title, content, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id("page"), project_id, slug, title, content, now),
            )
    return pages


def render_overview(project, sources, facts, conflicts) -> str:
    lines = [f"# {project['name']} 项目 Wiki", ""]
    if project["description"]:
        lines += [project["description"], ""]
    lines += [
        "## 当前状态",
        "",
        f"- 来源材料：{len(sources)} 个",
        f"- 项目事实：{len(facts)} 条",
        f"- 待审查冲突：{len(conflicts)} 条",
        "",
        "## Wiki 页面",
        "",
    ]
    for slug in PAGE_ORDER:
        lines.append(f"- [{title_from_slug(slug)}]({slug}.md)")
    lines += ["", "## 最近摄入来源", ""]
    for src in list(sources)[:20]:
        lines.append(f"- `{src['path']}`")
    return "\n".join(lines).strip() + "\n"


def render_fact_page(title: str, facts) -> str:
    lines = [f"# {title}", ""]
    if not facts:
        lines += ["当前材料中还没有抽取到足够信息。", ""]
        return "\n".join(lines)
    for fact in facts[:80]:
        evidence = from_json(fact["evidence_json"], [])
        pointer = evidence[0]["path"] if evidence else "unknown"
        lines.append(f"- {fact['statement']}")
        lines.append(f"  - 证据：`{pointer}`")
        status = fact["status"]
        validity = fact["validity_status"] if "validity_status" in fact.keys() else "unknown"
        lines.append(
            f"  - 状态：{fact_status_label(status)}，有效性：{fact_validity_label(validity)}，置信度：{fact['confidence']:.2f}"
        )
    return "\n".join(lines).strip() + "\n"


def first_evidence_path(item: dict) -> str:
    evidence = item.get("evidence", [])
    if not isinstance(evidence, list) or not evidence:
        return "unknown"
    first = evidence[0]
    if not isinstance(first, dict):
        return "unknown"
    return first.get("path") or "unknown"


def render_requirement_item(item: dict) -> list[str]:
    lines = [f"- {item['statement']}"]
    lines.append(f"  - 状态：{item.get('lifecycle_label', item.get('lifecycle_status', 'unknown'))}")
    lines.append(f"  - 证据：`{first_evidence_path(item)}`")
    superseded_by = item.get("superseded_by_fact_id")
    if superseded_by:
        lines.append(f"  - 替代者：`{superseded_by}`")
    return lines


def render_requirement_snapshot_page(project_id: str, conn: sqlite3.Connection) -> str:
    snapshot = build_requirement_snapshot(project_id, conn, "zh-CN")
    sections = [
        ("当前有效", snapshot["current"]),
        ("待确认", [*snapshot["needs_review"], *snapshot["conflicting"]]),
        ("已被替代", snapshot["superseded"]),
        ("历史参考", [*snapshot["historical"], *snapshot["rejected"]]),
    ]
    lines = ["# 当前需求快照", ""]
    for title, items in sections:
        lines += [f"## {title}", ""]
        if not items:
            lines.append("- 暂无。")
        for item in items:
            lines.extend(render_requirement_item(item))
        lines.append("")

    if snapshot["open_conflicts"]:
        lines += ["## 未解决冲突", ""]
        for conflict in snapshot["open_conflicts"]:
            lines.append(f"- **{conflict['title']}**（{conflict_severity_label(conflict['severity'])}）")
            lines.append(f"  - {conflict['description']}")
            evidence = conflict.get("evidence", [])
            paths = [item.get("path") for item in evidence if isinstance(item, dict) and item.get("path")]
            if paths:
                lines.append("  - 证据：" + "、".join(f"`{path}`" for path in paths[:5]))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_conflicts(conflicts) -> str:
    lines = ["# 冲突与待审查项", ""]
    if not conflicts:
        lines += ["当前没有检测到冲突。", ""]
        return "\n".join(lines)
    for conf in conflicts:
        evidence = from_json(conf["evidence_json"], [])
        lines.append(f"## {conf['title']}")
        lines.append("")
        lines.append(f"- 类型：{conflict_type_label(conf['conflict_type'])}")
        lines.append(f"- 严重程度：{conflict_severity_label(conf['severity'])}")
        lines.append(f"- 状态：{conflict_status_label(conf['status'])}")
        lines.append(f"- 描述：{conf['description']}")
        if evidence:
            lines.append("- 证据：")
            for ev in evidence[:10]:
                path = ev.get("path", "unknown")
                lines.append(f"  - `{path}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_open_questions(conflicts) -> str:
    lines = ["# Open Questions", "", "这些问题需要人工确认或补充材料。", ""]
    if not conflicts:
        lines.append("- 暂无。")
    for conf in conflicts:
        lines.append(f"- {conf['title']}：{conf['description']}")
    return "\n".join(lines).strip() + "\n"


def title_from_slug(slug: str) -> str:
    mapping = {
        "overview": "项目总览",
        "requirements": "需求与业务目标",
        "architecture": "代码结构与架构",
        "api": "接口信息",
        "experiments": "实验、模型与数据",
        "deployment": "运行与部署",
        "conflicts": "冲突与待审查项",
        "handover": "项目交接包",
        "open-questions": "Open Questions",
    }
    return mapping.get(slug, slug)
