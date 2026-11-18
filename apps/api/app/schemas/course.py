"""课程 / 章节 / 知识点 / 学习状态的请求与响应模型（P1.1 建，P1.2 扩展）。

- 对外字段一律 camelCase（见 `base.CamelModel`）；
- 学习状态取值见 `services/learning.py`，这里只做校验与透传，不重复定义进度规则；
- 统计类字段（`progress` / `statusCounts`）由服务层计算后填充，不接受客户端写入。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from ..services.learning import STATUS_LABELS, normalize_status
from .base import CamelModel


def _require_text(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name}不能为空")
    return stripped


class StatusCounts(CamelModel):
    """一组知识点的状态分布（total 与四项之和应当相等）。"""

    total: int = 0
    not_started: int = 0
    in_progress: int = 0
    review: int = 0
    completed: int = 0


class KnowledgePointOut(CamelModel):
    """目录里的知识点：只带长度不带正文，正文用详情接口按需拉取。"""

    id: int
    chapter_id: int
    title: str
    description: str
    content_length: int
    sort_order: int
    code_count: int
    mastery_level: int
    learning_status: str
    completion_source: str | None = None
    last_studied_at: datetime | None = None


class KnowledgePointSummary(CamelModel):
    """知识点列表项：不带正文，避免一次拉回几十万字。"""

    id: int
    chapter_id: int
    chapter_title: str
    title: str
    description: str
    sort_order: int
    code_count: int
    content_length: int
    learning_status: str
    completion_source: str | None = None
    last_studied_at: datetime | None = None


class KnowledgePointDetail(CamelModel):
    """知识点详情：带正文与前后邻居，供阅读面板上下翻页。"""

    id: int
    chapter_id: int
    chapter_title: str
    course_id: int
    course_title: str
    title: str
    description: str
    content: str
    sort_order: int
    code_count: int
    learning_status: str
    completion_source: str | None = None
    last_studied_at: datetime | None = None
    previous_id: int | None = None
    next_id: int | None = None


class ChapterOut(CamelModel):
    id: int
    course_id: int
    title: str
    description: str
    sort_order: int
    code_count: int
    knowledge_points: list[KnowledgePointOut]
    status_counts: StatusCounts
    progress: int


class CourseSummary(CamelModel):
    id: int
    title: str
    description: str
    status: str
    icon: str = ""
    source_type: str
    source_name: str
    source_bytes: int
    chapter_count: int
    knowledge_point_count: int
    code_count: int
    progress: int
    status_counts: StatusCounts
    last_studied_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CourseDetail(CourseSummary):
    warnings: list[str]
    stats: dict[str, Any]
    chapters: list[ChapterOut]


class CourseUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    # 单字符图标：留空字符串表示恢复成「按来源类型显示 MD/PDF」
    icon: str | None = Field(default=None, max_length=16)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return _require_text(value, field_name="课程名称")

    @field_validator("icon")
    @classmethod
    def _icon(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class ChapterCreate(CamelModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _require_text(value, field_name="章节名称") or ""


class ChapterUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return _require_text(value, field_name="章节名称")


class KnowledgePointCreate(CamelModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    content: str = Field(default="", max_length=200_000)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _require_text(value, field_name="知识点名称") or ""


class KnowledgePointUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    content: str | None = Field(default=None, max_length=200_000)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return _require_text(value, field_name="知识点名称")


class PointStatusUpdate(CamelModel):
    """手工调整学习状态。接受历史别名（learning / mastered），统一存四态。"""

    status: str = Field(min_length=1, max_length=16)

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        try:
            return normalize_status(value)
        except ValueError as exc:
            raise ValueError(f"状态取值无效，可选：{', '.join(STATUS_LABELS)}") from exc


class ChapterPointOrder(CamelModel):
    chapter_id: int
    ids: list[int] = Field(default_factory=list)


class ReorderRequest(CamelModel):
    chapters: list[int] = Field(default_factory=list)
    knowledge_points: list[ChapterPointOrder] = Field(default_factory=list)


class ChapterReorderRequest(CamelModel):
    """章节重排：必须是该课程当前全部章节 ID 的一个排列。"""

    ids: list[int] = Field(min_length=1)


class PointReorderRequest(CamelModel):
    """知识点重排：必须是该章节当前全部知识点 ID 的一个排列。"""

    ids: list[int] = Field(min_length=1)


class ChapterProgress(CamelModel):
    id: int
    title: str
    sort_order: int
    knowledge_point_count: int
    progress: int
    status_counts: StatusCounts


class RecentStudy(CamelModel):
    point_id: int
    title: str
    chapter_id: int
    chapter_title: str
    learning_status: str
    last_studied_at: datetime


class CourseProgress(CamelModel):
    """课程学习进度总览（`GET /courses/{id}/progress`）。"""

    course_id: int
    progress: int
    status_counts: StatusCounts
    chapters: list[ChapterProgress]
    recent: list[RecentStudy]
