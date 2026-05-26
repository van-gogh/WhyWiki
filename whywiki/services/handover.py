from __future__ import annotations

import sqlite3
from collections import defaultdict

from ..db import connect, init_db
from ..utils import from_json
from .lifecycle_labels import conflict_severity_label
from .requirement_lifecycle import build_requirement_snapshot


def first_evidence_path(item: dict) -> str:
    evidence = item.get("evidence", [])
    if not isinstance(evidence, list) or not evidence:
        return "unknown"
    first = evidence[0]
    if not isinstance(first, dict):
        return "unknown"
    return first.get("path") or "unknown"


def generate_handover(project_id: str, conn: sqlite3.Connection | None = None) -> str:
    close = conn is None
    conn = conn or connect()
    init_db(conn)
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    facts = conn.execute("SELECT * FROM facts WHERE project_id = ? ORDER BY confidence DESC LIMIT 80", (project_id,)).fetchall()
    conflicts = conn.execute("SELECT * FROM conflicts WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
    sources = conn.execute("SELECT * FROM sources WHERE project_id = ? ORDER BY path", (project_id,)).fetchall()
    requirement_snapshot = build_requirement_snapshot(project_id, conn, "zh-CN")

    by_type = defaultdict(list)
    for fact in facts:
        by_type[fact["fact_type"]].append(fact)

    lines = [f"# {project['name']} 交接包", ""]
    if project["description"]:
        lines += [project["description"], ""]

    lines += ["## 1. 当前材料概览", ""]
    lines.append(f"- 已摄入来源：{len(sources)} 个")
    lines.append(f"- 已抽取事实：{len(facts)} 条（显示前 80 条）")
    lines.append(f"- 待审查冲突：{len(conflicts)} 条")
    lines.append("")

    lines += ["## 2. 推荐阅读顺序", ""]
    priority = ["README", "overview", "需求", "requirement", "architecture", "api", "deploy", "实验", "experiment"]
    ranked = sorted(sources, key=lambda s: min([i for i, k in enumerate(priority) if k.lower() in (s["path"] + s["title"]).lower()] or [99]))
    for src in ranked[:12]:
        lines.append(f"- `{src['path']}`")
    lines.append("")

    lines += ["## 3. 当前需求 / 业务目标", ""]
    if not requirement_snapshot["current"]:
        lines.append("- 暂未确认当前有效需求。")
    for requirement in requirement_snapshot["current"][:10]:
        lines.append(f"- {requirement['statement']}  ")
        lines.append("  - 状态：当前有效")
        lines.append(f"  - 证据：`{first_evidence_path(requirement)}`")
    if requirement_snapshot["decisions"]:
        lines.append("")
        lines.append("最近需求决策：")
        for decision in requirement_snapshot["decisions"][:5]:
            reason = decision.get("reason") or "未记录原因"
            lines.append(f"- {decision['action_label']}：{reason}")
    lines.append("")

    sections = [
        ("code", "4. 代码结构 / 核心模块"),
        ("api", "5. 接口信息"),
        ("experiment", "6. 实验 / 模型 / 数据"),
        ("deployment", "7. 运行与部署"),
        ("decision", "8. 历史决策与变更原因"),
    ]
    for fact_type, title in sections:
        lines += [f"## {title}", ""]
        items = by_type.get(fact_type, [])[:10]
        if not items:
            lines.append("- 暂未从当前材料中抽取到足够信息。")
        for fact in items:
            evidence = from_json(fact["evidence_json"], [])
            pointer = evidence[0]["path"] if evidence else "unknown"
            lines.append(f"- {fact['statement']}  ")
            lines.append(f"  - 证据：`{pointer}`")
        lines.append("")

    lines += ["## 9. 待审查冲突", ""]
    if not conflicts:
        lines.append("- 暂未发现冲突。")
    for conf in conflicts:
        lines.append(f"- **{conf['title']}**（{conflict_severity_label(conf['severity'])}）")
        lines.append(f"  - {conf['description']}")
    lines.append("")

    lines += ["## 10. 新人接手建议", ""]
    lines += [
        "1. 先读本交接包和 `overview.md`。",
        "2. 再读推荐阅读顺序中的前 3-5 个材料。",
        "3. 优先处理 `conflicts.md` 中的高风险 / 中风险冲突。",
        "4. 对低置信度或缺少证据的事实进行人工确认。",
    ]

    if close:
        conn.close()
    return "\n".join(lines).strip() + "\n"
