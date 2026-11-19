"""通用教学活动协议（P1.6-A）。

一个协议承载 14 类活动；差异只体现在 activityType、interaction 和 evaluation。
本阶段只定义模型与校验，不接入状态机（P1.6-C 才按活动编排）。
"""

from __future__ import annotations

import json
import re
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

        # P1.7-A：图表若以图片形式给出，只允许站内素材，禁止任意外部 URL。
        for block in self.content:
            if block.kind == "diagram" and block.format == "image":
                target = block.payload.strip()
                if "://" in target and not target.startswith("material://"):
                    raise ValueError("图片图表只能引用站内素材（material://ID）")

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


# ---------------------------------------------------------------------------
# P1.7-B：结构化活动构建、有限修复、安全降级与素材归属清洗
# ---------------------------------------------------------------------------

DEFAULT_INPUT_KIND: dict[str, InputKind] = {
    "TEXT_EXPLANATION": "REFLECTION",
    "IMAGE_ANALYSIS": "SHORT_TEXT",
    "FORMULA_DERIVATION": "STEPS",
    "DIAGRAM_WALKTHROUGH": "NONE",
    "CODE_DEMO": "PREDICT_OUTPUT",
    "MULTIPLE_CHOICE": "CHOICE",
    "FILL_IN_BLANK": "BLANKS",
    "SHORT_ANSWER": "SHORT_TEXT",
    "STEP_ORDERING": "ORDER",
    "CALCULATION": "CALCULATION",
    "CONVERSATION": "DIALOGUE",
    "PRACTICAL_TASK": "DELIVERABLE",
    "AUDIO_EXERCISE": "CHOICE",
    "VIDEO_ANALYSIS": "SHORT_TEXT",
}

DEFAULT_EVALUATION_MODE: dict[str, EvaluationMode] = {
    "TEXT_EXPLANATION": "NONE",
    "IMAGE_ANALYSIS": "RUBRIC_AI",
    "FORMULA_DERIVATION": "RUBRIC_AI",
    "DIAGRAM_WALKTHROUGH": "RUBRIC_AI",
    "CODE_DEMO": "NONE",
    "MULTIPLE_CHOICE": "EXACT",
    "FILL_IN_BLANK": "NORMALIZED",
    "SHORT_ANSWER": "RUBRIC_AI",
    "STEP_ORDERING": "EXACT",
    "CALCULATION": "NUMERIC",
    "CONVERSATION": "RUBRIC_AI",
    "PRACTICAL_TASK": "RUBRIC_AI",
    "AUDIO_EXERCISE": "NORMALIZED",
    "VIDEO_ANALYSIS": "RUBRIC_AI",
}

# 允许在缺少标准答案时改判为 AI 评价的类型；其余必须给出标准答案，否则整体降级。
_RUBRIC_FALLBACK_TYPES = {
    "CODE_DEMO",
    "AUDIO_EXERCISE",
    "VIDEO_ANALYSIS",
    "DIAGRAM_WALKTHROUGH",
}


def _default_interaction(activity_type: str, prompt: str, hint: str) -> dict:
    return {
        "inputKind": DEFAULT_INPUT_KIND[activity_type],
        "prompt": prompt or "请完成当前任务。",
        "payload": {"hint": hint} if hint else {},
    }


def _default_evaluation(activity_type: str, rubric: str, mode: str | None = None) -> dict:
    return {
        "mode": mode or DEFAULT_EVALUATION_MODE[activity_type],
        "passThreshold": 0.7,
        "criteria": [
            {
                "id": "c1",
                "description": rubric or "能完成当前任务并说明理由",
                "weight": 1,
                "required": True,
            }
        ],
        "evidenceRule": "QUOTE",
        "allowHints": True,
        "maxHints": 2,
        "hintPenalty": "CAP_GUIDED",
        "feedbackPolicy": "IMMEDIATE",
    }


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_choices(payload: dict) -> None:
    raw_options = payload.get("options")
    options: list[dict] = []
    if isinstance(raw_options, list):
        for index, item in enumerate(raw_options):
            if isinstance(item, dict):
                option_id = str(item.get("id") or item.get("value") or index + 1)
                label = str(item.get("label") or item.get("text") or option_id)
            else:
                option_id = chr(65 + index) if index < 26 else str(index + 1)
                label = str(item)
            options.append({"id": option_id, "label": label})
    payload["options"] = options

    raw_correct = (
        payload.get("correctOptionIds")
        or payload.get("correctAnswer")
        or payload.get("answer")
        or payload.get("acceptedAnswers")
    )
    correct: list[str] = []
    for item in _as_list(raw_correct):
        text = str(item).strip()
        for option in options:
            if text in (option["id"], option["label"]):
                correct.append(option["id"])
                break
    payload["correctOptionIds"] = correct


def _normalize_blanks(payload: dict) -> None:
    raw_blanks = payload.get("blanks")
    blanks: list[dict] = []
    if isinstance(raw_blanks, list):
        for index, item in enumerate(raw_blanks):
            if isinstance(item, dict):
                answers = (
                    item.get("acceptedAnswers")
                    or item.get("answers")
                    or item.get("answer")
                    or item.get("value")
                )
                answers = [str(value) for value in _as_list(answers) if str(value).strip()]
                blanks.append(
                    {
                        "id": str(item.get("id") or f"blank-{index + 1}"),
                        "label": str(item.get("label") or f"第 {index + 1} 空"),
                        "acceptedAnswers": answers,
                    }
                )
            else:
                blanks.append(
                    {
                        "id": f"blank-{index + 1}",
                        "label": f"第 {index + 1} 空",
                        "acceptedAnswers": [str(item)],
                    }
                )
    payload["blanks"] = blanks


def _normalize_ordering(payload: dict) -> None:
    raw_items = payload.get("items")
    items: list[dict] = []
    if isinstance(raw_items, list):
        for index, item in enumerate(raw_items):
            if isinstance(item, dict):
                item_id = str(item.get("id") or item.get("value") or index + 1)
                label = str(item.get("label") or item.get("text") or item_id)
            else:
                item_id = str(index + 1)
                label = str(item)
            items.append({"id": item_id, "label": label})
    payload["items"] = items

    raw_order = payload.get("correctOrder") or payload.get("correctAnswer")
    if isinstance(raw_order, str):
        raw_order = [part for part in re.split(r"[,，、;；\s]+", raw_order) if part]
    order: list[str] = []
    for item in _as_list(raw_order):
        text = str(item).strip().strip("[]")
        for entry in items:
            if text in (entry["id"], entry["label"]):
                order.append(entry["id"])
                break
    payload["correctOrder"] = order


def _has_answer(payload: dict) -> bool:
    return bool(
        payload.get("correctAnswer")
        or payload.get("answer")
        or payload.get("acceptedAnswers")
        or payload.get("expectedOutput")
        or payload.get("correctOptionIds")
        or payload.get("correctOrder")
        or payload.get("blanks")
    )


def _normalize_activity_keys(data: dict) -> dict:
    """兼容模型常见的 snake_case 字段与简写键。"""
    for old, new in (
        ("schema_version", "schemaVersion"),
        ("knowledge_point_id", "knowledgePointId"),
        ("skip_reason", "skipReason"),
    ):
        if old in data and new not in data:
            data[new] = data.pop(old)
    interaction = data.get("interaction")
    if isinstance(interaction, dict):
        if "input_kind" in interaction and "inputKind" not in interaction:
            interaction["inputKind"] = interaction.pop("input_kind")
        payload = interaction.get("payload")
        if isinstance(payload, dict):
            for old, new in (
                ("correct_option_ids", "correctOptionIds"),
                ("accepted_answers", "acceptedAnswers"),
                ("correct_order", "correctOrder"),
                ("expected_output", "expectedOutput"),
                ("material_id", "materialId"),
            ):
                if old in payload and new not in payload:
                    payload[new] = payload.pop(old)
    evaluation = data.get("evaluation")
    if isinstance(evaluation, dict):
        for old, new in (
            ("pass_threshold", "passThreshold"),
            ("evidence_rule", "evidenceRule"),
            ("allow_hints", "allowHints"),
            ("max_hints", "maxHints"),
            ("hint_penalty", "hintPenalty"),
            ("feedback_policy", "feedbackPolicy"),
        ):
            if old in evaluation and new not in evaluation:
                evaluation[new] = evaluation.pop(old)
    materials = data.get("materials")
    if isinstance(materials, list):
        for item in materials:
            if isinstance(item, dict) and "material_id" in item and "materialId" not in item:
                item["materialId"] = item.pop("material_id")
    return data


def _normalize_content_blocks(raw: Any) -> list[dict]:
    """把模型常见的 content 变体修复为协议块；未知块直接丢弃，不阻断整个活动。"""
    if not isinstance(raw, list):
        return []
    blocks: list[dict] = []
    for item in raw[:40]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").lower()
        if kind == "markdown":
            text = item.get("text") or item.get("value") or item.get("content")
            if text:
                blocks.append({"kind": "markdown", "text": str(text)[:20000]})
        elif kind == "code":
            code = item.get("code") or item.get("value") or item.get("text")
            if code:
                blocks.append(
                    {
                        "kind": "code",
                        "language": str(item.get("language") or "")[:40],
                        "code": str(code)[:20000],
                        "caption": str(item.get("caption") or "")[:400],
                    }
                )
        elif kind == "latex":
            expression = item.get("expression") or item.get("value") or item.get("text")
            if expression:
                blocks.append(
                    {
                        "kind": "latex",
                        "expression": str(expression)[:4000],
                        "display": bool(item.get("display", True)),
                    }
                )
        elif kind == "callout":
            text = item.get("text") or item.get("value") or item.get("content")
            tone = item.get("tone") if item.get("tone") in ("info", "warning", "tip") else "info"
            if text:
                blocks.append({"kind": "callout", "tone": tone, "text": str(text)[:4000]})
        elif kind == "steps":
            raw_items = item.get("items") or item.get("value") or item.get("steps") or []
            steps: list[dict] = []
            for index, entry in enumerate(raw_items[:20]):
                if isinstance(entry, dict):
                    title = entry.get("title") or entry.get("label") or entry.get("text") or f"第 {index + 1} 步"
                    body = entry.get("body") or entry.get("description") or ""
                else:
                    title, body = str(entry), ""
                steps.append({"title": str(title)[:200], "body": str(body)[:4000]})
            if steps:
                blocks.append({"kind": "steps", "items": steps})
        elif kind == "table":
            headers = item.get("headers") or item.get("columns") or []
            rows = item.get("rows") or []
            if isinstance(headers, list) and headers:
                blocks.append(
                    {
                        "kind": "table",
                        "headers": [str(value)[:200] for value in headers[:20]],
                        "rows": [
                            [str(cell)[:200] for cell in row[:20]]
                            for row in rows[:200]
                            if isinstance(row, list)
                        ],
                    }
                )
        elif kind == "image":
            material_id = item.get("materialId") or item.get("material_id") or item.get("id")
            if material_id:
                blocks.append(
                    {
                        "kind": "image",
                        "materialId": int(material_id),
                        "alt": str(item.get("alt") or item.get("caption") or "素材图片")[:400],
                        "caption": str(item.get("caption") or "")[:400],
                    }
                )
        elif kind == "audio":
            material_id = item.get("materialId") or item.get("material_id") or item.get("id")
            if material_id:
                blocks.append(
                    {
                        "kind": "audio",
                        "materialId": int(material_id),
                        "transcript": str(item.get("transcript") or "")[:20000],
                    }
                )
        elif kind == "video":
            material_id = item.get("materialId") or item.get("material_id") or item.get("id")
            if material_id:
                blocks.append(
                    {
                        "kind": "video",
                        "materialId": int(material_id),
                        "captions": str(item.get("captions") or item.get("caption") or "")[:20000],
                    }
                )
        elif kind == "diagram":
            payload = item.get("payload") or item.get("value") or item.get("content")
            fmt = item.get("format") if item.get("format") in ("mermaid", "svg", "image") else "mermaid"
            if payload:
                blocks.append(
                    {
                        "kind": "diagram",
                        "format": fmt,
                        "payload": str(payload)[:40000],
                        "caption": str(item.get("caption") or "")[:400],
                    }
                )
    return blocks


def _repair_activity_data(
    data: dict,
    *,
    stage: str,
    knowledge_point_id: int,
    question: str,
    instruction: str,
    rubric: str,
    hint: str,
    summary: str,
    point_title: str,
) -> dict | None:
    """把模型输出的活动对象补齐为协议可校验的形态；无法安全修复时返回 None。"""
    if not isinstance(data, dict):
        return None
    data = _normalize_activity_keys(dict(data))
    activity_type = str(data.get("type") or "").upper()
    if activity_type not in ACTIVITY_TYPES:
        return None

    data["schemaVersion"] = 1
    data["type"] = activity_type
    data["stage"] = stage
    data["knowledgePointId"] = knowledge_point_id
    data["title"] = str(data.get("title") or question or "课堂活动")[:200]
    data["objective"] = str(data.get("objective") or instruction or question or "完成当前活动")[:1000]

    normalized_blocks = _normalize_content_blocks(data.get("content"))
    if normalized_blocks:
        data["content"] = normalized_blocks
    elif instruction:
        data["content"] = [{"kind": "markdown", "text": instruction}]
    else:
        data["content"] = []

    interaction = data.get("interaction")
    if not isinstance(interaction, dict):
        interaction = _default_interaction(activity_type, question, hint)
    else:
        interaction = dict(interaction)
        if interaction.get("inputKind") not in INPUT_KINDS_BY_TYPE[activity_type]:
            interaction["inputKind"] = DEFAULT_INPUT_KIND[activity_type]
        interaction["prompt"] = str(interaction.get("prompt") or question or "请完成当前任务。")[:4000]
        payload = interaction.get("payload")
        interaction["payload"] = payload if isinstance(payload, dict) else {}
    data["interaction"] = interaction
    payload = interaction["payload"]

    evaluation = data.get("evaluation")
    if not isinstance(evaluation, dict):
        evaluation = _default_evaluation(activity_type, rubric)
    else:
        evaluation = dict(evaluation)
        if evaluation.get("mode") not in EVALUATION_MODES_BY_TYPE[activity_type]:
            evaluation["mode"] = DEFAULT_EVALUATION_MODE[activity_type]
    data["evaluation"] = evaluation

    if activity_type == "MULTIPLE_CHOICE":
        _normalize_choices(payload)
        if not payload.get("options") or not payload.get("correctOptionIds"):
            return None
    elif activity_type == "FILL_IN_BLANK":
        _normalize_blanks(payload)
        if not payload.get("blanks") or any(not item.get("acceptedAnswers") for item in payload["blanks"]):
            return None
    elif activity_type == "STEP_ORDERING":
        _normalize_ordering(payload)
        if not payload.get("items") or not payload.get("correctOrder"):
            return None
    elif activity_type == "CALCULATION":
        if not _has_answer(payload):
            return None
    elif activity_type == "AUDIO_EXERCISE" and interaction.get("inputKind") == "CHOICE":
        _normalize_choices(payload)
        if not payload.get("options") or not payload.get("correctOptionIds"):
            return None

    # 确定性模式缺少标准答案时，只有允许 AI 评价的类型可以安全改判；否则整体降级。
    mode = evaluation.get("mode")
    if mode in ("EXACT", "NORMALIZED") and not _has_answer(payload) and activity_type != "MULTIPLE_CHOICE":
        if activity_type == "CODE_DEMO":
            evaluation["mode"] = "NONE"
        elif activity_type in _RUBRIC_FALLBACK_TYPES:
            evaluation["mode"] = "RUBRIC_AI"
        else:
            return None
    if mode == "NUMERIC" and not _has_answer(payload):
        return None

    data.setdefault("materials", [])
    if not data.get("source") and point_title:
        data["source"] = [{"sectionPath": point_title[:400]}]
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    meta.setdefault("summary", summary)
    meta["generatedBy"] = "model"
    data["meta"] = meta
    return data


def build_definition_from_task(
    *,
    task,
    stage: str,
    knowledge_point_id: int,
    point_title: str = "",
    allowed_material_ids: set[int] | None = None,
) -> tuple[TeachingActivityDefinition, list[str]]:
    """优先使用模型给出的结构化 activity；失败时记录原因并安全降级。

    返回 (definition, warnings)。warnings 会写入活动 meta，便于前端/审计看到降级原因。
    """
    warnings: list[str] = []
    raw = getattr(task, "activity", None)
    requested_type = str(raw.get("type") or "") if isinstance(raw, dict) else ""
    if raw is not None:
        if not isinstance(raw, dict):
            warnings.append("activity 字段不是对象")
        else:
            repaired = _repair_activity_data(
                dict(raw),
                stage=stage,
                knowledge_point_id=knowledge_point_id,
                question=task.question,
                instruction=task.instruction,
                rubric=task.rubric,
                hint=task.hint,
                summary=task.summary,
                point_title=point_title,
            )
            if repaired is not None:
                try:
                    definition = TeachingActivityDefinition.model_validate(repaired)
                    if allowed_material_ids is not None:
                        definition, material_warnings = sanitize_materials(
                            definition, allowed_ids=allowed_material_ids
                        )
                        warnings.extend(material_warnings)
                        if material_warnings:
                            definition.meta["materialWarnings"] = material_warnings
                    if warnings:
                        definition.meta["warnings"] = warnings
                    return definition, warnings
                except Exception as exc:  # noqa: BLE001 - 交给统一降级
                    warnings.append(f"结构化活动校验失败：{exc}")
            else:
                warnings.append("结构化活动缺少必要字段或类型不受支持")

    definition = definition_from_task(
        instruction=task.instruction,
        question=task.question,
        rubric=task.rubric,
        hint=task.hint,
        summary=task.summary,
        stage=stage,
        knowledge_point_id=knowledge_point_id,
    )
    if requested_type:
        definition.meta["requestedType"] = requested_type
    if warnings:
        definition.meta["degraded"] = True
        definition.meta["fallbackReason"] = "；".join(warnings)[:1500]
    return definition, warnings


def all_material_ids(definition: TeachingActivityDefinition) -> list[int]:
    ids = [item.material_id for item in definition.materials]
    for block in definition.content:
        if block.kind in ("image", "audio", "video"):
            ids.append(block.material_id)
    return ids


def sanitize_materials(
    definition: TeachingActivityDefinition, *, allowed_ids: set[int]
) -> tuple[TeachingActivityDefinition, list[str]]:
    """移除不属于当前课程的素材引用；活动本身保留，前端显示缺失占位。"""
    referenced = set(all_material_ids(definition))
    removed = sorted(referenced - allowed_ids)
    if not removed:
        return definition, []

    data = definition.model_dump(by_alias=False)
    data["materials"] = [
        item for item in data.get("materials", []) if item.get("material_id") not in removed
    ]
    data["content"] = [
        block
        for block in data.get("content", [])
        if not (block.get("kind") in ("image", "audio", "video") and block.get("material_id") in removed)
    ]
    warnings = [f"已移除不属于当前课程的素材引用：{', '.join(str(item) for item in removed)}"]
    repaired = TeachingActivityDefinition.model_validate(data)
    return repaired, warnings


# ---------------------------------------------------------------------------
# P1.7-B：确定性评价（EXACT / NORMALIZED / NUMERIC / NONE）
# ---------------------------------------------------------------------------

_STRIP_CHARS = " \t\r\n。．.，,；;：:！!？?\"'“”‘’()（）[]【】"


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().strip(_STRIP_CHARS).casefold().split())


def _parse_number(value: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", "").replace("，", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _choice_ids(text: str, options: list[dict]) -> list[str]:
    bracketed = re.findall(r"\[([^\]]+)\]", text)
    if bracketed:
        tokens = [item.strip() for part in bracketed for item in re.split(r"[,，、;；\s]+", part) if item.strip()]
    else:
        tokens = [item for item in re.split(r"[,，、;；\s]+", text.strip()) if item]
    selected: list[str] = []
    for token in tokens:
        for option in options:
            if token in (str(option.get("id")), str(option.get("label"))):
                if str(option.get("id")) not in selected:
                    selected.append(str(option.get("id")))
                break
    return selected


def _blank_values(text: str, blanks: list[dict]) -> list[str]:
    values: list[str] = []
    for blank in blanks:
        label = str(blank.get("label") or "")
        match = re.search(rf"{re.escape(label)}\s*[：:]\s*([^；;\n|]+)", text)
        values.append(match.group(1).strip() if match else "")
    if blanks and not any(values):
        parts = [item.strip() for item in re.split(r"[；;\n|]+", text) if item.strip()]
        if len(parts) == len(blanks):
            values = parts
        elif len(blanks) == 1:
            values = [text.strip()]
    return values


def _ordered_ids(text: str, items: list[dict]) -> list[str]:
    bracketed = re.findall(r"\[([^\]]+)\]", text)
    if bracketed:
        tokens = [item.strip() for part in bracketed for item in re.split(r"[,，、;；\s]+", part) if item.strip()]
    else:
        tokens = [
            re.sub(r"^\s*\d+[.)、]\s*", "", line).strip()
            for line in text.splitlines()
            if line.strip()
        ]
        if len(tokens) <= 1:
            tokens = [item for item in re.split(r"[,，、;；]+", text.strip()) if item.strip()]
    result: list[str] = []
    for token in tokens:
        for item in items:
            if token in (str(item.get("id")), str(item.get("label"))):
                if str(item.get("id")) not in result:
                    result.append(str(item.get("id")))
                break
    return result


def _expected_answers(payload: dict) -> list[str]:
    raw = (
        payload.get("acceptedAnswers")
        or payload.get("correctAnswer")
        or payload.get("answer")
        or payload.get("expectedOutput")
        or payload.get("value")
    )
    return [str(item) for item in _as_list(raw) if str(item).strip()]


def evaluate_deterministic(
    definition: TeachingActivityDefinition, student_input: str
) -> ActivityResult | None:
    """服务端确定性判定；RUBRIC_AI/MANUAL 返回 None，由模型评价。"""
    mode = definition.evaluation.mode
    if mode in ("RUBRIC_AI", "MANUAL"):
        return None
    text = (student_input or "").strip()
    payload = definition.interaction.payload
    threshold = definition.evaluation.pass_threshold
    score = 0.0
    note = ""
    expected_text = ""

    if mode == "NONE":
        return ActivityResult(
            verdict="CORRECT",
            score=1.0,
            evidence=text[:200] or "已阅读当前内容",
            feedback="已完成当前活动，继续下一步。",
        )

    if definition.type == "MULTIPLE_CHOICE" or definition.interaction.input_kind == "CHOICE":
        options = payload.get("options") or []
        correct = {str(item) for item in payload.get("correctOptionIds") or []}
        selected = set(_choice_ids(text, options))
        if selected and selected == correct:
            score = 1.0
        elif selected and selected & correct:
            score = len(selected & correct) / max(len(correct), 1)
        expected_text = "、".join(
            label for option in options if str(option.get("id")) in correct
            for label in [str(option.get("label") or option.get("id"))]
        )
    elif definition.type == "FILL_IN_BLANK":
        blanks = payload.get("blanks") or []
        values = _blank_values(text, blanks)
        hits = 0
        expected_parts: list[str] = []
        for blank, value in zip(blanks, values):
            accepted = {_normalize_text(str(item)) for item in blank.get("acceptedAnswers") or []}
            if accepted:
                expected_parts.append(str((blank.get("acceptedAnswers") or [""])[0]))
            if _normalize_text(value) in accepted:
                hits += 1
        score = hits / max(len(blanks), 1)
        expected_text = "；".join(expected_parts)
    elif definition.type == "STEP_ORDERING":
        items = payload.get("items") or []
        correct = [str(item) for item in payload.get("correctOrder") or []]
        answered = _ordered_ids(text, items)
        hits = sum(1 for index, item in enumerate(answered) if index < len(correct) and item == correct[index])
        score = hits / max(len(correct), 1)
        expected_text = " → ".join(
            str(item.get("label") or item.get("id"))
            for item in items
            if str(item.get("id")) in correct
        )
    elif definition.type == "CALCULATION":
        expected = _expected_answers(payload)
        expected_text = expected[0] if expected else ""
        expected_number = _parse_number(expected_text) if expected else None
        actual_number = _parse_number(text)
        tolerance = float(payload.get("tolerance") or 1e-6)
        if expected_number is not None and actual_number is not None:
            score = 1.0 if abs(expected_number - actual_number) <= tolerance else 0.0
        elif expected:
            score = 1.0 if _normalize_text(text) in {_normalize_text(item) for item in expected} else 0.0
    else:
        expected = _expected_answers(payload)
        expected_text = expected[0] if expected else ""
        accepted = {_normalize_text(item) for item in expected}
        score = 1.0 if accepted and _normalize_text(text) in accepted else 0.0

    if score >= threshold:
        verdict = "CORRECT"
        note = "回答与标准答案一致。"
    elif score > 0:
        verdict = "PARTIAL"
        note = "回答部分正确，注意遗漏或顺序。"
    else:
        verdict = "INCORRECT"
        note = "回答与标准答案不一致。"

    feedback = note
    if expected_text:
        feedback += f"\n参考答案：{expected_text}"
    return ActivityResult(
        verdict=verdict,
        score=round(score, 4),
        evidence=text[:200],
        feedback=feedback,
    )


def to_judgment(result: ActivityResult, *, is_verify: bool, student_input: str):
    """把确定性结果转换成现有的 TeachingJudgment，复用原状态机。"""
    from ..schemas.teaching import TeachingJudgment

    if is_verify:
        verdict = "PASSED" if result.verdict in ("CORRECT", "PASSED") else (
            "NEEDS_REVIEW" if result.verdict == "PARTIAL" else "FAILED"
        )
    else:
        verdict = result.verdict if result.verdict in ("CORRECT", "PARTIAL", "INCORRECT", "UNCLEAR") else "INCORRECT"
    evidence = result.evidence or (student_input or "")[:200] or "已阅读当前内容"
    return TeachingJudgment(
        evaluation=verdict,
        reason=f"服务端按 {result.score:.0%} 的匹配度判定",
        misconceptions=[],
        suggested_action="CONTINUE",
        feedback=result.feedback,
        evidence_quote=evidence[:200],
        summary=result.feedback[:300],
    )
