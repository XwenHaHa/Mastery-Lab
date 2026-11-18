"""AI 学习教室的请求/响应模型（P1.3）。

对外 camelCase；system 提示词、API Key 等内部信息不出现在任何响应里。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .base import CamelModel
from .course import StatusCounts

MessageRole = Literal["user", "assistant"]
MessageStatus = Literal["streaming", "completed", "interrupted", "failed"]


class ClassroomCourseInfo(CamelModel):
    id: int
    title: str
    description: str
    icon: str = ""
    progress: int = 0
    chapter_count: int = 0
    knowledge_point_count: int = 0
    learned_count: int = 0
    status_counts: StatusCounts


class ClassroomPointInfo(CamelModel):
    id: int
    chapter_id: int
    chapter_title: str
    title: str
    description: str
    content_length: int
    sort_order: int
    learning_status: str
    previous_id: int | None = None
    next_id: int | None = None


class ClassroomModelInfo(CamelModel):
    id: int
    name: str
    model_name: str


class ChatMessageOut(CamelModel):
    id: int
    role: MessageRole
    content: str
    status: MessageStatus
    model_name: str = ""
    error_message: str = ""
    created_at: datetime


class ClassroomContextOut(CamelModel):
    course: ClassroomCourseInfo
    point: ClassroomPointInfo
    model: ClassroomModelInfo | None = None


class ClassroomSessionOut(CamelModel):
    id: int
    course: ClassroomCourseInfo
    point: ClassroomPointInfo
    model: ClassroomModelInfo | None = None
    messages: list[ChatMessageOut]
    streaming: bool = False
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None


class SessionOpenRequest(CamelModel):
    course_id: int = Field(gt=0)
    knowledge_point_id: int = Field(gt=0)
    model_config_id: int | None = Field(default=None, gt=0)


class MessageCreateRequest(CamelModel):
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def _content(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("消息内容不能为空")
        return text


class StopStreamResult(CamelModel):
    stopped: bool
    message: str = ""
