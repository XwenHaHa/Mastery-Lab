from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import CamelModel


class TeachingAction(CamelModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    request_id: UUID
    expected_revision: int = Field(ge=0)
    action: Literal["START", "CONTINUE", "ANSWER", "ASK", "EXPLAIN_AGAIN", "CHANGE_EXAMPLE", "GIVE_HINT", "DONT_UNDERSTAND", "TRY_MYSELF", "REGENERATE", "PAUSE", "RESUME", "NEXT", "RESTART"]
    content: str = Field(default="", max_length=8000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return value.strip()


class TeachingTask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    instruction: str = Field(min_length=1, max_length=4000)
    question: str = Field(min_length=3, max_length=4000)
    rubric: str = Field(min_length=3, max_length=3000)
    hint: str = Field(min_length=1, max_length=1000)
    summary: str = Field(default="", max_length=2000)


class TeachingJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    evaluation: Literal["CORRECT", "PARTIAL", "INCORRECT", "UNCLEAR", "PASSED", "NEEDS_REVIEW", "FAILED"]
    reason: str = Field(min_length=1, max_length=2000)
    misconceptions: list[str] = Field(max_length=8)
    suggested_action: Literal["CONTINUE", "EXPLAIN_AGAIN", "CHANGE_EXAMPLE", "GIVE_HINT", "ASK_CLARIFICATION", "RETURN_TO_TEACH", "RETURN_TO_DEMO", "RETURN_TO_PAIR", "COMPLETE_STAGE"]
    feedback: str = Field(min_length=1, max_length=6000)
    evidence_quote: str = Field(max_length=2000)
    summary: str = Field(default="", max_length=2000)

    @field_validator("misconceptions")
    @classmethod
    def bound_misconceptions(cls, values: list[str]) -> list[str]:
        if any(len(value) > 500 for value in values):
            raise ValueError("misconception exceeds limit")
        return values
