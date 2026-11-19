"""教学活动实例双写与读取（P1.6-B/E）。

原则：只追加、不覆盖历史。
- 任务生成时把 TeachingTask 适配为 `SHORT_ANSWER` 活动实例；
- 评价时把结果写回同一条实例；
- P1.6-E 起教学状态只读当前活动，供前端通用活动渲染器展示；
- 任何写活动失败都只记日志，不回滚教学质量数据。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ChatMessage, TeachingActivityInstance, TeachingOperation, TeachingProgress
from ..schemas.teaching import TeachingJudgment, TeachingTask
from . import activity_protocol, classroom_service, material_library

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "ACTIVE"
STATUS_WAITING = "WAITING_EVALUATION"
STATUS_COMPLETED = "COMPLETED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entities(db: Session, progress: TeachingProgress):
    row = classroom_service.get_session_row(db, progress.session_id)
    course, _chapter, point = classroom_service.load_entities_for_row(db, row)
    return course, point


def record_task(
    db: Session,
    *,
    progress: TeachingProgress,
    operation: TeachingOperation,
    task: TeachingTask,
) -> TeachingActivityInstance | None:
    """把一次题目生成写成活动实例；失败不影响教学主流程。"""
    try:
        course, point = _entities(db, progress)
        definition, warnings = activity_protocol.build_definition_from_task(
            task=task,
            stage=operation.stage,
            knowledge_point_id=point.id,
            point_title=point.title,
            allowed_material_ids=material_library.material_ids_for_course(db, course.id),
        )
        if warnings:
            logger.warning(
                "教学活动已降级或清洗 session=%s operation=%s: %s",
                progress.session_id,
                operation.id,
                "；".join(warnings),
            )
        instance = TeachingActivityInstance(
            session_id=progress.session_id,
            course_id=course.id,
            knowledge_point_id=point.id,
            operation_id=operation.id,
            prompt_message_id=operation.assistant_message_id,
            stage=operation.stage,
            activity_type=definition.type,
            schema_version=definition.schema_version,
            status=STATUS_ACTIVE,
            attempt_no=1,
            hint_count=progress.verify_hint_count if operation.stage == "VERIFY" else progress.hint_count,
            definition_json=definition.model_dump_json(by_alias=True),
            started_at=_now(),
        )
        with db.begin_nested():
            db.add(instance)
            db.flush()
        return instance
    except Exception:  # noqa: BLE001 - 活动双写是审计增强，不能破坏旧教学流程
        logger.exception("教学活动双写失败 session=%s operation=%s", progress.session_id, operation.id)
        return None


def record_evaluation(
    db: Session,
    *,
    progress: TeachingProgress,
    operation: TeachingOperation,
    judgment: TeachingJudgment,
) -> TeachingActivityInstance | None:
    """把评价结果写回对应活动实例；找不到实例时静默跳过。"""
    if operation.question_message_id is None:
        return None
    try:
        instance = db.scalars(
            select(TeachingActivityInstance)
            .where(
                TeachingActivityInstance.session_id == progress.session_id,
                TeachingActivityInstance.prompt_message_id == operation.question_message_id,
            )
            .order_by(TeachingActivityInstance.id.desc())
        ).first()
        if instance is None:
            return None
        answer = db.get(ChatMessage, operation.user_message_id) if operation.user_message_id else None
        passed = judgment.evaluation in ("CORRECT", "PASSED")
        with db.begin_nested():
            instance.status = STATUS_COMPLETED if passed else STATUS_ACTIVE
            instance.student_input = (answer.content if answer else "")[:8000]
            instance.result_json = judgment.model_dump_json()
            instance.ai_feedback = judgment.feedback[:6000]
            instance.hint_count = progress.verify_hint_count if operation.stage == "VERIFY" else progress.hint_count
            instance.answer_message_id = operation.user_message_id
            if passed:
                instance.completed_at = _now()
            instance.updated_at = _now()
            db.flush()
        return instance
    except Exception:  # noqa: BLE001
        logger.exception("教学活动评价回写失败 session=%s operation=%s", progress.session_id, operation.id)
        return None


def _instance_for_question(
    db: Session, session_id: int, question_message_id: int | None
) -> TeachingActivityInstance | None:
    if not question_message_id:
        return None
    return db.scalars(
        select(TeachingActivityInstance)
        .where(
            TeachingActivityInstance.session_id == session_id,
            TeachingActivityInstance.prompt_message_id == question_message_id,
        )
        .order_by(TeachingActivityInstance.id.desc())
    ).first()


def activity_type_for_question(
    db: Session, session_id: int, question_message_id: int | None
) -> str | None:
    try:
        instance = _instance_for_question(db, session_id, question_message_id)
        return instance.activity_type if instance is not None else None
    except Exception:  # noqa: BLE001
        logger.exception("读取活动类型失败 session=%s", session_id)
        return None


def current_activity_payload(db: Session, progress: TeachingProgress) -> dict | None:
    """返回当前待答活动的只读视图；没有实例时返回 None，前端回退到 textarea。"""
    question_message_id = getattr(progress, "question_message_id", None)
    if not question_message_id:
        return None
    try:
        instance = _instance_for_question(db, progress.session_id, question_message_id)
        if instance is None:
            return None
        definition = json.loads(instance.definition_json or "{}")
        material_ids: list[int] = []
        for block in definition.get("content") or []:
            if block.get("kind") in ("image", "audio", "video") and block.get("materialId"):
                material_ids.append(int(block["materialId"]))
        for item in definition.get("materials") or []:
            if item.get("materialId"):
                material_ids.append(int(item["materialId"]))
        return {
            "id": instance.id,
            "activityType": instance.activity_type,
            "stage": instance.stage,
            "status": instance.status,
            "attemptNo": instance.attempt_no,
            "hintCount": instance.hint_count,
            "definition": definition,
            "materials": material_library.resolve_material_refs(db, material_ids, instance.course_id),
            "studentInput": instance.student_input,
            "result": json.loads(instance.result_json or "{}") if instance.result_json else None,
            "aiFeedback": instance.ai_feedback,
        }
    except Exception:  # noqa: BLE001 - 渲染增强失败时回退旧输入框
        logger.exception("读取当前教学活动失败 session=%s", progress.session_id)
        return None


def definition_for_question(
    db: Session, session_id: int, question_message_id: int | None
) -> activity_protocol.TeachingActivityDefinition | None:
    """读取某条待答问题对应的活动定义，供服务端确定性评价使用。"""
    instance = _instance_for_question(db, session_id, question_message_id)
    if instance is None:
        return None
    try:
        return activity_protocol.TeachingActivityDefinition.model_validate(
            json.loads(instance.definition_json or "{}")
        )
    except Exception:  # noqa: BLE001 - 旧数据或损坏定义不影响文字评价回退
        logger.exception("解析活动定义失败 session=%s instance=%s", session_id, instance.id)
        return None


def current_definition(
    db: Session, progress: TeachingProgress
) -> activity_protocol.TeachingActivityDefinition | None:
    return definition_for_question(
        db, progress.session_id, getattr(progress, "question_message_id", None)
    )


def audit_payload(instance: TeachingActivityInstance) -> dict:
    """只读视图，供后续调试或回放；本阶段不接入 API。"""
    return {
        "id": instance.id,
        "sessionId": instance.session_id,
        "stage": instance.stage,
        "activityType": instance.activity_type,
        "status": instance.status,
        "attemptNo": instance.attempt_no,
        "hintCount": instance.hint_count,
        "definition": json.loads(instance.definition_json or "{}"),
        "studentInput": instance.student_input,
        "result": json.loads(instance.result_json or "{}"),
        "aiFeedback": instance.ai_feedback,
    }
