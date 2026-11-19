"""错题与薄弱点（P1.5）。

只有真实错误才建记录：CHECK / PAIR 的错误或部分正确、VERIFY 的失败或需复习。
自由提问、空泛回答（UNCLEAR）不记为错题。相同知识点 + 阶段 + 相同错误归并为一条，
每次发生仍写入 mistake_occurrences，可完整追溯。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    ChatMessage,
    KnowledgePoint,
    LearningEvent,
    MistakeOccurrence,
    MistakeRecord,
    TeachingOperation,
    TeachingProgress,
)
from . import learning_record

ERROR_TYPES = {
    "CHECK": "concept",
    "PAIR": "practice",
    "VERIFY": "verification",
}
ERROR_TYPE_LABELS = {
    "concept": "概念理解",
    "practice": "实践操作",
    "verification": "独立验证",
}
STATUS_OPEN = "open"
STATUS_UNDERSTOOD = "understood"


def now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip().lower())
    text = re.sub(r"[，。！？、,.!?;；:：\"'“”‘’（）()\[\]{}]", "", text)
    return text[:120]


def dedupe_key(point_id: int, stage: str, answer: str, misconceptions: list[str]) -> str:
    seed = "|".join(
        [str(point_id), stage, _normalize(answer), _normalize("|".join(misconceptions))]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def is_error(stage: str, verdict: str | None) -> bool:
    if not verdict:
        return False
    if stage == "CHECK":
        return verdict in ("INCORRECT", "PARTIAL")
    if stage == "PAIR":
        return verdict in ("INCORRECT", "PARTIAL")
    if stage == "VERIFY":
        return verdict in ("FAILED", "NEEDS_REVIEW")
    return False


def record_mistake(
    db: Session,
    *,
    operation: TeachingOperation,
    progress: TeachingProgress,
    point: KnowledgePoint,
    stage: str,
    verdict: str,
    reason: str,
    feedback: str,
    misconceptions: list[str],
) -> MistakeRecord | None:
    if not is_error(stage, verdict):
        return None

    question_message = db.get(ChatMessage, operation.question_message_id) if operation.question_message_id else None
    answer_message = db.get(ChatMessage, operation.user_message_id) if operation.user_message_id else None
    question = (progress.current_question or (question_message.content if question_message else "")) or ""
    answer = answer_message.content if answer_message else ""
    key = dedupe_key(point.id, stage, answer, misconceptions)
    activity = learning_record.active_activity(db, operation.session_id)

    record = db.scalars(
        select(MistakeRecord)
        .where(MistakeRecord.dedupe_key == key)
        .order_by(MistakeRecord.id.desc())
    ).first()
    created = record is None
    if record is None:
        record = MistakeRecord(
            course_id=point.chapter.course_id,
            knowledge_point_id=point.id,
            session_id=operation.session_id,
            activity_id=activity.id if activity else None,
            stage=stage,
            error_type=ERROR_TYPES.get(stage, "concept"),
            dedupe_key=key,
            question=question,
            user_answer=answer,
            correct_answer=feedback,
            error_reason=reason,
            correction=feedback,
            misconceptions=json.dumps(misconceptions, ensure_ascii=False),
            status=STATUS_OPEN,
            occurrence_count=1,
            first_seen_at=now(),
            last_seen_at=now(),
        )
        db.add(record)
        db.flush()
    else:
        record.activity_id = activity.id if activity else record.activity_id
        record.question = question or record.question
        record.user_answer = answer or record.user_answer
        record.correct_answer = feedback or record.correct_answer
        record.error_reason = reason or record.error_reason
        record.correction = feedback or record.correction
        record.misconceptions = json.dumps(misconceptions, ensure_ascii=False)
        record.occurrence_count += 1
        record.last_seen_at = now()
        record.status = STATUS_OPEN
        record.resolved_at = None
        record.updated_at = now()

    db.add(
        MistakeOccurrence(
            mistake_id=record.id,
            activity_id=activity.id if activity else None,
            session_id=operation.session_id,
            stage=stage,
            verdict=verdict,
            question=question,
            user_answer=answer,
            feedback=feedback,
        )
    )
    db.add(
        LearningEvent(
            activity_id=activity.id if activity else None,
            course_id=point.chapter.course_id,
            knowledge_point_id=point.id,
            session_id=operation.session_id,
            event_type="MISTAKE_RECORDED",
            detail=f"{stage} {verdict}：{reason}"[:4000],
        )
    )
    return record


def mark_status(db: Session, record: MistakeRecord, status: str) -> MistakeRecord:
    record.status = status
    record.resolved_at = now() if status == STATUS_UNDERSTOOD else None
    record.updated_at = now()
    db.commit()
    db.refresh(record)
    return record
