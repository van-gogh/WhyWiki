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
