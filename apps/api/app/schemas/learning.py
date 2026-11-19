"""学习档案、学习活动与断点续学的请求模型（P1.5）。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from .base import CamelModel


class ActivityStartRequest(CamelModel):
    course_id: int = Field(gt=0)
    knowledge_point_id: int = Field(gt=0)
    session_id: int | None = Field(default=None, gt=0)


class ActivityHeartbeatRequest(CamelModel):
    active_seconds_delta: int = Field(default=0, ge=0, le=600)


class ActivityFinishRequest(CamelModel):
    result: Literal["finished", "completed", "interrupted"] = "finished"
    reason: str = Field(default="user_exit", max_length=40)


class BreakpointSaveRequest(CamelModel):
    client_seq: int = Field(default=0, ge=0)
    draft_answer: str = Field(default="", max_length=8000)
    input_mode: Literal["ASK", "ANSWER"] = "ASK"


class MistakeStatusRequest(CamelModel):
    status: Literal["open", "understood"]

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        return value
