"""AI 学习教室的业务逻辑（P1.3）。

职责：
- 把「课程 → 章节 → 知识点」的归属关系校验清楚；
- 复用/创建知识点会话，读写消息；
- 计算右侧面板需要的课程进度与已学习数量；
- 不直接调用模型，也不处理 HTTP/SSE（分别由 llm_client 与路由负责）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..core.response import ConflictError, NotFoundError, ValidationError
from ..db.models import Chapter, ChatMessage, Course, KnowledgePoint, LearningSession, ModelConfig
from ..schemas.classroom import (
    ChatMessageOut,
    ClassroomContextOut,
    ClassroomCourseInfo,
    ClassroomModelInfo,
    ClassroomPointInfo,
    ClassroomSessionOut,
)
from ..schemas.course import StatusCounts
from . import learning, stream_registry

logger = logging.getLogger(__name__)

ACTIVE_COURSE_STATUS = "active"


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _counts_model(counts: dict[str, int]) -> StatusCounts:
    return StatusCounts(
        total=counts.get("total", 0),
        not_started=counts.get(learning.STATUS_NOT_STARTED, 0),
        in_progress=counts.get(learning.STATUS_IN_PROGRESS, 0),
        review=counts.get(learning.STATUS_REVIEW, 0),
        completed=counts.get(learning.STATUS_COMPLETED, 0),
    )


def _all_points(course: Course) -> list[KnowledgePoint]:
    return [point for chapter in course.chapters for point in chapter.knowledge_points]


def load_entities(session: Session, course_id: int, point_id: int) -> tuple[Course, Chapter, KnowledgePoint]:
    """校验课程存在、课程已创建完成、知识点确实属于该课程。"""
    course = session.get(Course, course_id)
    if course is None or course.status != ACTIVE_COURSE_STATUS:
        raise NotFoundError(f"课程 {course_id} 不存在或尚未创建完成")
    point = session.get(KnowledgePoint, point_id)
    if point is None:
        raise NotFoundError(f"知识点 {point_id} 不存在")
    chapter = session.get(Chapter, point.chapter_id)
    if chapter is None or chapter.course_id != course.id:
        # 不暴露「这个 ID 在别的课程里」，统一按不属于当前课程处理
        raise NotFoundError(f"知识点 {point_id} 不属于课程 {course_id}")
    return course, chapter, point


def load_entities_for_row(session: Session, row: LearningSession) -> tuple[Course, Chapter, KnowledgePoint]:
    return load_entities(session, row.course_id, row.knowledge_point_id)


def get_session_row(session: Session, session_id: int) -> LearningSession:
    row = session.get(LearningSession, session_id)
    if row is None:
        raise NotFoundError(f"学习会话 {session_id} 不存在")
    return row


def resolve_model(session: Session, preferred_id: int | None = None) -> ModelConfig | None:
    """优先用会话指定的模型；否则用默认配置；再否则用第一条。没有配置返回 None。"""
    if preferred_id is not None:
        config = session.get(ModelConfig, preferred_id)
        if config is None:
            raise NotFoundError(f"模型配置 {preferred_id} 不存在")
        return config
    default = session.scalars(select(ModelConfig).where(ModelConfig.is_default.is_(True))).first()
    if default is not None:
        return default
    return session.scalars(select(ModelConfig).order_by(ModelConfig.id)).first()


def _course_info(course: Course) -> ClassroomCourseInfo:
    points = _all_points(course)
    counts = learning.status_counts(points)
    total = counts.get("total", 0)
    return ClassroomCourseInfo(
        id=course.id,
        title=course.title,
        description=course.description,
        icon=course.icon or "",
        progress=learning.progress_from_counts(counts),
        chapter_count=len(course.chapters),
        knowledge_point_count=total,
        learned_count=max(0, total - counts.get(learning.STATUS_NOT_STARTED, 0)),
        status_counts=_counts_model(counts),
    )


def _point_info(course: Course, point: KnowledgePoint) -> ClassroomPointInfo:
    chapter = next((item for item in course.chapters if item.id == point.chapter_id), None)
    flat = _all_points(course)
    index = next((i for i, item in enumerate(flat) if item.id == point.id), -1)
    previous_id = flat[index - 1].id if index > 0 else None
    next_id = flat[index + 1].id if 0 <= index < len(flat) - 1 else None
    return ClassroomPointInfo(
        id=point.id,
        chapter_id=point.chapter_id,
        chapter_title=chapter.title if chapter else "",
        title=point.title,
        description=point.description,
        content_length=len(point.content or ""),
        sort_order=point.sort_order,
        learning_status=learning.safe_status(point.learning_status),
        previous_id=previous_id,
        next_id=next_id,
    )


def message_out(message: ChatMessage, *, streaming: bool) -> ChatMessageOut:
    status = message.status
    if status == "streaming" and not streaming:
        # 进程异常退出后残留的占位消息：内容就是已经生成的部分，按中断展示。
        status = "interrupted"
    if status not in ("streaming", "completed", "interrupted", "failed"):
        status = "completed"
    return ChatMessageOut(
        id=message.id,
        role=message.role if message.role in ("user", "assistant") else "assistant",
        content=message.content or "",
        status=status,
        model_name=message.model_name or "",
        error_message=message.error_message or "",
        created_at=_utc(message.created_at) or message.created_at,
    )


def to_context_out(session: Session, course: Course, point: KnowledgePoint) -> ClassroomContextOut:
    model = resolve_model(session)
    return ClassroomContextOut(
        course=_course_info(course),
        point=_point_info(course, point),
        model=ClassroomModelInfo(id=model.id, name=model.name, model_name=model.model_name) if model else None,
    )


def to_session_out(session: Session, row: LearningSession) -> ClassroomSessionOut:
    course, _chapter, point = load_entities_for_row(session, row)
    model = resolve_model(session, row.model_config_id)
    streaming = stream_registry.is_active(row.id)
    return ClassroomSessionOut(
        id=row.id,
        course=_course_info(course),
        point=_point_info(course, point),
        model=ClassroomModelInfo(id=model.id, name=model.name, model_name=model.model_name) if model else None,
        messages=[message_out(message, streaming=streaming) for message in row.messages],
        streaming=streaming,
        created_at=_utc(row.created_at) or row.created_at,
        updated_at=_utc(row.updated_at) or row.updated_at,
        last_message_at=_utc(row.last_message_at),
    )


def get_context(session: Session, course_id: int, point_id: int) -> ClassroomContextOut:
    course, _chapter, point = load_entities(session, course_id, point_id)
    return to_context_out(session, course, point)


def get_session(session: Session, session_id: int) -> ClassroomSessionOut:
    return to_session_out(session, get_session_row(session, session_id))


def open_session(
    session: Session,
    *,
    course_id: int,
    point_id: int,
    model_config_id: int | None = None,
) -> ClassroomSessionOut:
    """按「课程 + 知识点」恢复会话；不存在则创建。

    同一知识点只有一个会话，重新进入教室不会丢历史。
    """
    load_entities(session, course_id, point_id)
    row = session.scalars(
        select(LearningSession).where(
            LearningSession.course_id == course_id,
            LearningSession.knowledge_point_id == point_id,
        )
    ).first()
    if row is None:
        row = LearningSession(course_id=course_id, knowledge_point_id=point_id)
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            row = session.scalars(select(LearningSession).where(
                LearningSession.course_id == course_id,
                LearningSession.knowledge_point_id == point_id,
            )).one()

    if model_config_id is not None and model_config_id != row.model_config_id and stream_registry.is_active(row.id):
        raise ConflictError("请先停止当前生成，再切换模型")
    model = resolve_model(session, model_config_id or row.model_config_id)
    row.model_config_id = model.id if model else None
    session.commit()
    session.refresh(row)
    return to_session_out(session, row)


def add_user_message(session: Session, row: LearningSession, content: str) -> ChatMessage:
    now = datetime.now(timezone.utc)
    message = ChatMessage(
        session_id=row.id,
        role="user",
        content=content.strip(),
        status="completed",
    )
    row.last_message_at = now
    session.add(message)
    session.flush()
    return message


def create_assistant_message(session: Session, row: LearningSession, model_name: str) -> ChatMessage:
    message = ChatMessage(
        session_id=row.id,
        role="assistant",
        content="",
        status="streaming",
        model_name=model_name,
    )
    row.last_message_at = datetime.now(timezone.utc)
    session.add(message)
    session.flush()
    return message


def update_assistant_message(
    session: Session,
    message: ChatMessage,
    *,
    content: str,
    status: str,
    error_message: str = "",
) -> None:
    message.content = content
    message.status = status
    message.error_message = error_message[:500]
    message.session.last_message_at = datetime.now(timezone.utc)
    session.commit()


def delete_last_assistant(session: Session, row: LearningSession) -> ChatMessage | None:
    """重新生成前移除最后一条助手消息；用户消息保留，作为新的回答对象。"""
    last = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == row.id)
        .order_by(ChatMessage.id.desc())
        .limit(1)
    ).first()
    if last is None or last.role != "assistant":
        return None
    session.delete(last)
    session.flush()
    return last


def load_stream_inputs(
    session: Session, row: LearningSession
) -> tuple[Course, Chapter, KnowledgePoint, list[ChatMessage]]:
    course, chapter, point = load_entities_for_row(session, row)
    history = session.scalars(
        select(ChatMessage).where(ChatMessage.session_id == row.id).order_by(ChatMessage.id)
    ).all()
    return course, chapter, point, list(history)


def decrypt_model_key(session: Session, model: ModelConfig) -> str:
    """读取并解密 API Key；失败时给出可操作的中文提示（不包含密文）。"""
    from ..core.security import SecretError, decrypt_secret

    try:
        return decrypt_secret(model.api_key_cipher)
    except SecretError as exc:
        raise ValidationError(f"无法读取模型「{model.name}」的 API Key：{exc}") from exc
