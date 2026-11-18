"""学习状态与学习进度的唯一事实来源（P1.2）。

四态状态（存库即为这些字面量）：

| 值 | 含义 | 权重 |
| --- | --- | --- |
| `not_started` | 未学习 | 0 |
| `in_progress` | 学习中 | 0.4 |
| `review` | 待复习 | 0.7 |
| `completed` | 已完成 | 1 |

进度公式（课程、章节都用这一套，不允许别处再写一份）：

    进度 = round(Σ weight(status_i) / 知识点总数 * 100)

- 分母为 0（空课程 / 空章节）时进度为 0，不把空内容当成「已完成」。
- 权重是刻意的：只学到一半不该显示 0%，待复习也不该等同于已完成。
- 掌握度（mastery_level）不由这里计算，P1.2 不写该字段，留到后续阶段。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

LearningStatus = Literal["not_started", "in_progress", "completed", "review"]

STATUS_NOT_STARTED: LearningStatus = "not_started"
STATUS_IN_PROGRESS: LearningStatus = "in_progress"
STATUS_COMPLETED: LearningStatus = "completed"
STATUS_REVIEW: LearningStatus = "review"

# 顺序即界面上的展示顺序：未学习 → 学习中 → 待复习 → 已完成
STATUS_ORDER: tuple[LearningStatus, ...] = (
    STATUS_NOT_STARTED,
    STATUS_IN_PROGRESS,
    STATUS_REVIEW,
    STATUS_COMPLETED,
)

STATUS_WEIGHTS: dict[str, float] = {
    STATUS_NOT_STARTED: 0.0,
    STATUS_IN_PROGRESS: 0.4,
    STATUS_REVIEW: 0.7,
    STATUS_COMPLETED: 1.0,
}

STATUS_LABELS: dict[str, str] = {
    STATUS_NOT_STARTED: "未学习",
    STATUS_IN_PROGRESS: "学习中",
    STATUS_REVIEW: "待复习",
    STATUS_COMPLETED: "已完成",
}

# P1.1 只有 not_started / learning / mastered 三种值，旧库里的后两种按语义并入四态。
LEGACY_STATUS_ALIASES: dict[str, LearningStatus] = {
    "learning": STATUS_IN_PROGRESS,
    "mastered": STATUS_COMPLETED,
}


def normalize_status(value: str | None) -> LearningStatus:
    """把任意历史值/别名归一成四态之一；无法识别时抛 ValueError。"""
    raw = (value or "").strip().lower()
    if raw in STATUS_WEIGHTS:
        return raw  # type: ignore[return-value]
    if raw in LEGACY_STATUS_ALIASES:
        return LEGACY_STATUS_ALIASES[raw]
    raise ValueError(f"不支持的学习状态 {value!r}，可选值：{', '.join(STATUS_ORDER)}")


def safe_status(value: Any) -> LearningStatus:
    """读库时容错：出现未知值时按「未学习」处理，不让整页报错。"""
    try:
        return normalize_status(value)
    except ValueError:
        return STATUS_NOT_STARTED


def status_counts(points: Iterable[Any]) -> dict[str, int]:
    """统计一组知识点（或任意带 learning_status 的对象）的状态分布。"""
    counts: dict[str, int] = {"total": 0, **{status: 0 for status in STATUS_ORDER}}
    for point in points:
        counts["total"] += 1
        counts[safe_status(getattr(point, "learning_status", None))] += 1
    return counts


def progress_from_counts(counts: Mapping[str, int]) -> int:
    """由状态分布算加权进度（0–100，四舍五入）。"""
    total = int(counts.get("total", 0))
    if total <= 0:
        return 0
    weighted = sum(STATUS_WEIGHTS[status] * int(counts.get(status, 0)) for status in STATUS_ORDER)
    return int(round(weighted * 100 / total))


def summarize(points: Iterable[Any]) -> tuple[dict[str, int], int]:
    """返回 (状态分布, 进度百分比)。"""
    items = list(points)
    counts = status_counts(items)
    return counts, progress_from_counts(counts)
