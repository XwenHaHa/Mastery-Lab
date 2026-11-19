"""断点续学快照（P1.5）。

- 教学阶段、问题、尝试次数由后端在教学状态变化时同步，前端无法伪造；
- 前端只负责保存草稿、输入模式，并用单调 clientSeq 防止旧请求覆盖新数据；
- 会话本身由 learning_sessions 的唯一约束保证不会重复创建。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.response import NotFoundError
from ..db.models import (
    ChatMessage,
    Course,
    KnowledgePoint,
    LearningActivity,
    LearningBreakpoint,
    LearningSession,
    TeachingProgress,
)
from . import classroom_service, learning_record


def now() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime | None) -> datetime | None:
    return classroom_service._utc(value)


def _last_messages(db: Session, session_id: int) -> tuple[ChatMessage | None, ChatMessage | None]:
    last = db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id.desc()).limit(1)
    ).first()
    last_assistant = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.id.desc())
        .limit(1)
    ).first()
    return last, last_assistant


def get_or_create(db: Session, session_id: int) -> LearningBreakpoint:
    row = db.get(LearningBreakpoint, session_id)
    if row is not None:
        return row
    session_row = classroom_service.get_session_row(db, session_id)
    course, _chapter, point = classroom_service.load_entities_for_row(db, session_row)
    progress = db.get(TeachingProgress, session_id)
    last, last_assistant = _last_messages(db, session_id)
    activity = learning_record.active_activity(db, session_id)
    row = LearningBreakpoint(
        session_id=session_id,
        course_id=course.id,
        knowledge_point_id=point.id,
        activity_id=activity.id if activity else None,
        current_stage=progress.current_stage if progress else "TEACH",
        stage_status=progress.stage_status if progress else "PENDING",
        revision=progress.revision if progress else 0,
        paused=progress.paused if progress else False,
        input_mode="ASK",
        draft_answer="",
        current_question=progress.current_question if progress else "",
        completed_stages=progress.completed_stages if progress else "[]",
        pair_step=progress.pair_step if progress else 1,
        check_attempts=progress.check_attempts if progress else 0,
        pair_attempts=progress.pair_attempts if progress else 0,
        verify_attempts=progress.verify_attempts if progress else 0,
        hint_count=progress.hint_count if progress else 0,
        verify_hint_count=progress.verify_hint_count if progress else 0,
        last_message_id=last.id if last else None,
        last_assistant_message_id=last_assistant.id if last_assistant else None,
        last_assistant_excerpt=(last_assistant.content[:600] if last_assistant else ""),
        client_seq=0,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        # 并发打开教室时，教学状态与断点会同时初始化；后到者复用先写入的快照。
        if row in db:
            db.expunge(row)
        existing = db.get(LearningBreakpoint, session_id)
        if existing is None:
            raise
        return existing
    return row


def sync_from_progress(db: Session, session_id: int, progress: TeachingProgress | None = None) -> LearningBreakpoint:
    """把教学状态同步进断点（不提交事务，由调用方决定）。"""
    row = get_or_create(db, session_id)
    progress = progress if progress is not None else db.get(TeachingProgress, session_id)
    activity = learning_record.active_activity(db, session_id)
    if activity is not None:
        row.activity_id = activity.id
    if progress is not None:
        row.current_stage = progress.current_stage
        row.stage_status = progress.stage_status
        row.revision = progress.revision
        row.paused = progress.paused
        row.current_question = progress.current_question or ""
        row.completed_stages = progress.completed_stages
        row.pair_step = progress.pair_step
        row.check_attempts = progress.check_attempts
        row.pair_attempts = progress.pair_attempts
        row.verify_attempts = progress.verify_attempts
        row.hint_count = progress.hint_count
        row.verify_hint_count = progress.verify_hint_count
    last, last_assistant = _last_messages(db, session_id)
    row.last_message_id = last.id if last else None
    row.last_assistant_message_id = last_assistant.id if last_assistant else None
    if last_assistant is not None:
        row.last_assistant_excerpt = (last_assistant.content or "")[:600]
    row.updated_at = now()
    return row


def save(
    db: Session,
    session_id: int,
    *,
    client_seq: int,
    draft_answer: str,
    input_mode: str,
) -> tuple[LearningBreakpoint, bool]:
    """保存前端草稿。返回 (row, accepted)。旧序号不会覆盖更新的数据。"""
    row = get_or_create(db, session_id)
    if client_seq < row.client_seq:
        return row, False
    if client_seq > row.client_seq:
        row.client_seq = client_seq
    row.draft_answer = (draft_answer or "")[:8000]
    row.input_mode = input_mode if input_mode in ("ASK", "ANSWER") else "ASK"
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return row, True


def _next_point(db: Session, course: Course, point: KnowledgePoint) -> KnowledgePoint | None:
    flat = [item for chapter in course.chapters for item in chapter.knowledge_points]
    index = next((i for i, item in enumerate(flat) if item.id == point.id), -1)
    if 0 <= index < len(flat) - 1:
        return flat[index + 1]
    return None


def resume_info(db: Session) -> dict | None:
    """最近一次可恢复的学习位置。已完成的知识点自动指向下一个合理位置。"""
    row = db.scalars(select(LearningBreakpoint).order_by(LearningBreakpoint.updated_at.desc())).first()
    if row is None:
        activity = db.scalars(
            select(LearningActivity).order_by(LearningActivity.last_heartbeat_at.desc())
        ).first()
        if activity is None:
            return None
        session_row = db.get(LearningSession, activity.session_id)
        if session_row is None:
            return None
        course, _chapter, point = classroom_service.load_entities_for_row(db, session_row)
        return _resume_payload(
            course=course,
            point=point,
            session_id=session_row.id,
            stage=activity.final_stage,
            stage_status="PENDING",
            updated_at=activity.last_heartbeat_at,
            has_draft=False,
            activity_id=activity.id,
        )

    session_row = db.get(LearningSession, row.session_id)
    if session_row is None:
        return None
    try:
        course, _chapter, point = classroom_service.load_entities_for_row(db, session_row)
    except NotFoundError:
        return None
    if point.learning_status == "completed" or row.current_stage == "NEXT":
        next_point = _next_point(db, course, point)
        if next_point is not None:
            point = next_point
    return _resume_payload(
        course=course,
        point=point,
        session_id=row.session_id,
        stage=row.current_stage,
        stage_status=row.stage_status,
        updated_at=row.updated_at,
        has_draft=bool(row.draft_answer.strip()),
        activity_id=row.activity_id,
    )


def _resume_payload(
    *,
    course: Course,
    point: KnowledgePoint,
    session_id: int,
    stage: str,
    stage_status: str,
    updated_at: datetime | None,
    has_draft: bool,
    activity_id: int | None,
) -> dict:
    return {
        "courseId": course.id,
        "courseTitle": course.title,
        "knowledgePointId": point.id,
        "knowledgePointTitle": point.title,
        "chapterTitle": next(
            (chapter.title for chapter in course.chapters if chapter.id == point.chapter_id), ""
        ),
        "sessionId": session_id,
        "currentStage": stage,
        "stageStatus": stage_status,
        "hasDraft": has_draft,
        "activityId": activity_id,
        "updatedAt": utc(updated_at),
    }


def breakpoint_out(db: Session, row: LearningBreakpoint) -> dict:
    session_row = classroom_service.get_session_row(db, row.session_id)
    course, _chapter, point = classroom_service.load_entities_for_row(db, session_row)
    return {
        "sessionId": row.session_id,
        "courseId": row.course_id,
        "courseTitle": course.title,
        "knowledgePointId": row.knowledge_point_id,
        "knowledgePointTitle": point.title,
        "activityId": row.activity_id,
        "currentStage": row.current_stage,
        "stageStatus": row.stage_status,
        "revision": row.revision,
        "paused": row.paused,
        "inputMode": row.input_mode,
        "draftAnswer": row.draft_answer,
        "currentQuestion": row.current_question,
        "completedStages": json.loads(row.completed_stages or "[]"),
        "pairStep": row.pair_step,
        "checkAttempts": row.check_attempts,
        "pairAttempts": row.pair_attempts,
        "verifyAttempts": row.verify_attempts,
        "hintCount": row.hint_count,
        "verifyHintCount": row.verify_hint_count,
        "lastMessageId": row.last_message_id,
        "lastAssistantMessageId": row.last_assistant_message_id,
        "lastAssistantExcerpt": row.last_assistant_excerpt,
        "clientSeq": row.client_seq,
        "updatedAt": utc(row.updated_at),
    }
