"""通用教学活动协议（P1.6-A）。

一个协议承载 14 类活动；差异只体现在 activityType、interaction 和 evaluation。
本阶段只定义模型与校验，不接入状态机（P1.6-C 才按活动编排）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

SCHEMA_VERSION = 1
MAX_DEFINITION_BYTES = 64 * 1024

ActivityType = Literal[
    "TEXT_EXPLANATION",
    "IMAGE_ANALYSIS",
    "FORMULA_DERIVATION",
    "DIAGRAM_WALKTHROUGH",
    "CODE_DEMO",
    "MULTIPLE_CHOICE",
    "FILL_IN_BLANK",
    "SHORT_ANSWER",
    "STEP_ORDERING",
    "CALCULATION",
    "CONVERSATION",
    "PRACTICAL_TASK",
    "AUDIO_EXERCISE",
    "VIDEO_ANALYSIS",
]

InputKind = Literal[
    "NONE",
    "REFLECTION",
    "SHORT_TEXT",
    "STEPS",
    "HOTSPOT_ORDER",
    "PREDICT_OUTPUT",
    "CHOICE",
    "BLANKS",
    "ORDER",
    "CALCULATION",
    "DIALOGUE",
    "DELIVERABLE",
    "AUDIO_RESPONSE",
    "DICTATION",
    "TIMESTAMP_ANSWER",
]

EvaluationMode = Literal["NONE", "EXACT", "NORMALIZED", "NUMERIC", "RUBRIC_AI", "MANUAL"]
EvidenceRule = Literal["QUOTE", "SELECTION", "VALUE", "SEQUENCE", "ATTACHMENT", "SELF_REPORT"]
HintPenalty = Literal["NONE", "CAP_GUIDED", "BLOCK_INDEPENDENT"]
FeedbackPolicy = Literal["IMMEDIATE", "AFTER_SUBMIT", "DEFERRED"]
ActivityStatus = Literal["PENDING", "ACTIVE", "WAITING_EVALUATION", "COMPLETED", "SKIPPED", "FAILED"]
ActivityVerdict = Literal[
    "CORRECT",
    "PARTIAL",
    "INCORRECT",
    "UNCLEAR",
    "PASSED",
    "NEEDS_REVIEW",
    "FAILED",
]

ACTIVITY_TYPES: tuple[str, ...] = (
    "TEXT_EXPLANATION",
    "IMAGE_ANALYSIS",
    "FORMULA_DERIVATION",
    "DIAGRAM_WALKTHROUGH",
    "CODE_DEMO",
    "MULTIPLE_CHOICE",
    "FILL_IN_BLANK",
    "SHORT_ANSWER",
    "STEP_ORDERING",
    "CALCULATION",
    "CONVERSATION",
    "PRACTICAL_TASK",
    "AUDIO_EXERCISE",
    "VIDEO_ANALYSIS",
)

INPUT_KINDS_BY_TYPE: dict[str, set[str]] = {
    "TEXT_EXPLANATION": {"NONE", "REFLECTION"},
    "IMAGE_ANALYSIS": {"SHORT_TEXT"},
    "FORMULA_DERIVATION": {"STEPS"},
    "DIAGRAM_WALKTHROUGH": {"HOTSPOT_ORDER", "NONE"},
    "CODE_DEMO": {"NONE", "PREDICT_OUTPUT"},
    "MULTIPLE_CHOICE": {"CHOICE"},
    "FILL_IN_BLANK": {"BLANKS"},
    "SHORT_ANSWER": {"SHORT_TEXT"},
    "STEP_ORDERING": {"ORDER"},
    "CALCULATION": {"CALCULATION"},
    "CONVERSATION": {"DIALOGUE"},
    "PRACTICAL_TASK": {"DELIVERABLE"},
    "AUDIO_EXERCISE": {"AUDIO_RESPONSE", "CHOICE", "DICTATION"},
    "VIDEO_ANALYSIS": {"TIMESTAMP_ANSWER", "SHORT_TEXT"},
}

EVALUATION_MODES_BY_TYPE: dict[str, set[str]] = {
    "TEXT_EXPLANATION": {"NONE"},
    "IMAGE_ANALYSIS": {"RUBRIC_AI"},
    "FORMULA_DERIVATION": {"RUBRIC_AI"},
    "DIAGRAM_WALKTHROUGH": {"EXACT", "RUBRIC_AI", "NONE"},
    "CODE_DEMO": {"NONE", "EXACT"},
    "MULTIPLE_CHOICE": {"EXACT"},
    "FILL_IN_BLANK": {"EXACT", "NORMALIZED"},
    "SHORT_ANSWER": {"RUBRIC_AI"},
    "STEP_ORDERING": {"EXACT"},
    "CALCULATION": {"NUMERIC"},
    "CONVERSATION": {"NONE", "RUBRIC_AI"},
    "PRACTICAL_TASK": {"MANUAL", "RUBRIC_AI"},
    "AUDIO_EXERCISE": {"EXACT", "NORMALIZED", "RUBRIC_AI"},
    "VIDEO_ANALYSIS": {"RUBRIC_AI", "EXACT"},
}


class ProtocolModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class MarkdownBlock(ProtocolModel):
    kind: Literal["markdown"]
    text: str = Field(min_length=1, max_length=20000)


class LatexBlock(ProtocolModel):
    kind: Literal["latex"]
    expression: str = Field(min_length=1, max_length=4000)
    display: bool = True


class CodeBlock(ProtocolModel):
    kind: Literal["code"]
    language: str = Field(default="", max_length=40)
    code: str = Field(min_length=1, max_length=20000)
    caption: str = Field(default="", max_length=400)


class ImageBlock(ProtocolModel):
    kind: Literal["image"]
    material_id: int = Field(gt=0)
    alt: str = Field(min_length=1, max_length=400)
    caption: str = Field(default="", max_length=400)


class DiagramBlock(ProtocolModel):
    kind: Literal["diagram"]
    format: Literal["mermaid", "svg", "image"]
    payload: str = Field(min_length=1, max_length=40000)
    caption: str = Field(default="", max_length=400)


class TableBlock(ProtocolModel):
    kind: Literal["table"]
    headers: list[str] = Field(min_length=1, max_length=20)
    rows: list[list[str]] = Field(default_factory=list, max_length=200)


class AudioBlock(ProtocolModel):
    kind: Literal["audio"]
    material_id: int = Field(gt=0)
    transcript: str = Field(default="", max_length=20000)


class VideoBlock(ProtocolModel):
    kind: Literal["video"]
    material_id: int = Field(gt=0)
    captions: str = Field(default="", max_length=20000)


class CalloutBlock(ProtocolModel):
    kind: Literal["callout"]
    tone: Literal["info", "warning", "tip"]
    text: str = Field(min_length=1, max_length=4000)


class StepItem(ProtocolModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=4000)


class StepsBlock(ProtocolModel):
    kind: Literal["steps"]
    items: list[StepItem] = Field(min_length=1, max_length=20)


ContentBlock = Annotated[
    Union[
        MarkdownBlock,
        LatexBlock,
        CodeBlock,
        ImageBlock,
        DiagramBlock,
        TableBlock,
        AudioBlock,
        VideoBlock,
        CalloutBlock,
        StepsBlock,
    ],
    Field(discriminator="kind"),
]


class SourceRef(ProtocolModel):
    course_file: str = Field(default="", max_length=400)
    page: int | None = Field(default=None, ge=1)
    section_path: str = Field(default="", max_length=400)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class MaterialRef(ProtocolModel):
    material_id: int = Field(gt=0)
    role: Literal["primary", "supporting", "reference"] = "primary"
    caption: str = Field(default="", max_length=400)
    source: SourceRef | None = None


class InteractionSpec(ProtocolModel):
    input_kind: InputKind
    prompt: str = Field(min_length=1, max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bound_payload(self):
        if len(json.dumps(self.payload, ensure_ascii=False)) > 32000:
            raise ValueError("interaction payload 超出 32 KB 限制")
        return self


class EvaluationCriterion(ProtocolModel):
    id: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    weight: float = Field(default=1.0, ge=0, le=100)
    required: bool = True


class EvaluationSpec(ProtocolModel):
    mode: EvaluationMode
    pass_threshold: float = Field(default=0.7, ge=0, le=1)
    criteria: list[EvaluationCriterion] = Field(default_factory=list, max_length=20)
    evidence_rule: EvidenceRule = "QUOTE"
    allow_hints: bool = True
    max_hints: int = Field(default=2, ge=0, le=20)
    hint_penalty: HintPenalty = "CAP_GUIDED"
    feedback_policy: FeedbackPolicy = "IMMEDIATE"


class TeachingActivityDefinition(ProtocolModel):
    schema_version: Literal[1] = 1
    type: ActivityType
    stage: str = Field(min_length=1, max_length=32)
    knowledge_point_id: int = Field(gt=0)

    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=1000)

    content: list[ContentBlock] = Field(default_factory=list, max_length=40)
    materials: list[MaterialRef] = Field(default_factory=list, max_length=20)
    interaction: InteractionSpec
    evaluation: EvaluationSpec
    source: list[SourceRef] = Field(default_factory=list, max_length=20)

    applicable: bool = True
    skip_reason: str = Field(default="", max_length=500)
    difficulty: Literal[1, 2, 3] = 1
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self):
        if self.interaction.input_kind not in INPUT_KINDS_BY_TYPE[self.type]:
            raise ValueError(f"{self.type} 不支持 inputKind={self.interaction.input_kind}")
        if self.evaluation.mode not in EVALUATION_MODES_BY_TYPE[self.type]:
            raise ValueError(f"{self.type} 不支持 evaluation.mode={self.evaluation.mode}")
        if not self.applicable and not self.skip_reason.strip():
            raise ValueError("applicable=false 时必须说明 skipReason")

        payload = self.interaction.payload
        if self.type == "MULTIPLE_CHOICE":
            options = payload.get("options")
            if not isinstance(options, list) or len(options) < 2:
                raise ValueError("选择题至少需要 2 个选项")
            if not payload.get("correctOptionIds"):
                raise ValueError("选择题必须给出 correctOptionIds")
        elif self.type == "FILL_IN_BLANK":
            blanks = payload.get("blanks")
            if not isinstance(blanks, list) or not blanks:
                raise ValueError("填空题至少需要 1 个空")
            if any(not isinstance(item, dict) or not item.get("acceptedAnswers") for item in blanks):
                raise ValueError("每个空至少需要 1 个可接受答案")
        elif self.type == "STEP_ORDERING":
            items = payload.get("items")
            if not isinstance(items, list) or len(items) < 2:
                raise ValueError("排序题至少需要 2 项")
            if not payload.get("correctOrder"):
                raise ValueError("排序题必须给出 correctOrder")

        if len(json.dumps(self.model_dump(mode="json", by_alias=True), ensure_ascii=False).encode()) > MAX_DEFINITION_BYTES:
            raise ValueError("活动定义超出 64 KB 限制")
        return self


class CriterionResult(ProtocolModel):
    criterion_id: str = Field(min_length=1, max_length=64)
    met: bool
    note: str = Field(default="", max_length=1000)


class ActivityResult(ProtocolModel):
    verdict: ActivityVerdict
    score: float = Field(default=0.0, ge=0, le=1)
    evidence: str = Field(default="", max_length=4000)
    feedback: str = Field(min_length=1, max_length=6000)
    misconceptions: list[str] = Field(default_factory=list, max_length=8)
    criteria: list[CriterionResult] = Field(default_factory=list, max_length=20)


class TeachingActivityInstance(ProtocolModel):
    id: int | None = None
    definition: TeachingActivityDefinition
    session_id: int = Field(gt=0)

    status: ActivityStatus = "PENDING"
    attempt_no: int = Field(default=1, ge=1)
    hint_count: int = Field(default=0, ge=0)
    student_input: str = Field(default="", max_length=8000)
    result: ActivityResult | None = None
    ai_feedback: str = Field(default="", max_length=6000)

    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


def definition_from_task(
    *,
    instruction: str,
    question: str,
    rubric: str,
    hint: str,
    summary: str,
    stage: str,
    knowledge_point_id: int,
) -> TeachingActivityDefinition:
    """把 P1.4 的五字段题目适配为通用活动定义（P1.6-B 双写使用）。

    旧题目的结构最接近 SHORT_ANSWER：老师给引导，学生用文字回答，AI 按标准评价。
    """
    return TeachingActivityDefinition(
        type="SHORT_ANSWER",
        stage=stage,
        knowledge_point_id=knowledge_point_id,
        title=question[:120],
        objective=instruction[:1000] or question[:1000],
        content=[{"kind": "markdown", "text": instruction}] if instruction else [],
        interaction={
            "input_kind": "SHORT_TEXT",
            "prompt": question,
            "payload": {"hint": hint} if hint else {},
        },
        evaluation={
            "mode": "RUBRIC_AI",
            "pass_threshold": 0.7,
            "criteria": [
                {"id": "c1", "description": rubric, "weight": 1, "required": True}
            ],
            "evidence_rule": "QUOTE",
            "allow_hints": True,
            "max_hints": 2,
            "hint_penalty": "CAP_GUIDED",
            "feedback_policy": "IMMEDIATE",
        },
        meta={"summary": summary, "legacyTask": True},
    )
