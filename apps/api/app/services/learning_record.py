"""学习活动与有效学习时间（P1.5）。

时间口径：
- 有效时长 = 客户端在「页面可见且最近有操作」时累计的秒数，按心跳上报；
- 服务端对单次上报做上限裁剪，空闲超过 IDLE_TIMEOUT_SECONDS 直接结束活动；
- 浏览器关闭、后端重启都不会把离线时间算进学习时长，只会留下最后心跳时间。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.response import NotFoundError
from ..db.models import LearningActivity, LearningEvent, LearningSession, TeachingProgress
from . import classroom_service

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30
IDLE_TIMEOUT_SECONDS = 15 * 60
MAX_HEARTBEAT_DELTA_SECONDS = 120

ACTIVITY_ACTIVE = "active"
ACTIVITY_COMPLETED = "completed"
ACTIVITY_INTERRUPTED = "interrupted"
ACTIVITY_FINISHED = "finished"


def now() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime | None) -> datetime | None:
    return classroom_service._utc(value)


def session_entities(db: Session, session_id: int) -> tuple[LearningSession, object, object]:
    row = classroom_service.get_session_row(db, session_id)
    course, _chapter, point = classroom_service.load_entities_for_row(db, row)
    return row, course, point


def active_activity(db: Session, session_id: int) -> LearningActivity | None:
    return db.scalars(
        select(LearningActivity)
        .where(LearningActivity.session_id == session_id, LearningActivity.status == ACTIVITY_ACTIVE)
        .order_by(LearningActivity.id.desc())
    ).first()


def latest_activity(db: Session, session_id: int) -> LearningActivity | None:
    return db.scalars(
        select(LearningActivity)
        .where(LearningActivity.session_id == session_id)
        .order_by(LearningActivity.id.desc())
    ).first()


def record_event(
    db: Session,
    *,
    course_id: int,
    point_id: int,
    session_id: int | None,
    activity_id: int | None,
    event_type: str,
    detail: str = "",
) -> None:
    db.add(
        LearningEvent(
            activity_id=activity_id,
            course_id=course_id,
            knowledge_point_id=point_id,
            session_id=session_id,
            event_type=event_type,
            detail=detail[:4000],
        )
    )


def _close(activity: LearningActivity, *, result: str, reason: str, ended_at: datetime | None = None) -> None:
    activity.status = ACTIVITY_COMPLETED if result == ACTIVITY_COMPLETED else ACTIVITY_FINISHED
    activity.result = result
    activity.end_reason = reason
    activity.ended_at = ended_at or now()


def _sync_counters(activity: LearningActivity, progress: TeachingProgress | None) -> None:
    if progress is None:
        return
    activity.final_stage = progress.current_stage
    activity.completed_stages = progress.completed_stages
    activity.check_attempts = progress.check_attempts
    activity.pair_attempts = progress.pair_attempts
    activity.verify_attempts = progress.verify_attempts
    activity.hint_count = progress.hint_count
    activity.verify_hint_count = progress.verify_hint_count


def start_activity(db: Session, session_id: int, *, commit: bool = True) -> tuple[LearningActivity, bool]:
    """开始或复用一次学习活动。返回 (activity, reused)。"""
    row, course, point = session_entities(db, session_id)
    current = active_activity(db, session_id)
    if current is not None:
        last = utc(current.last_heartbeat_at) or utc(current.started_at) or now()
        if now() - last <= timedelta(seconds=IDLE_TIMEOUT_SECONDS):
            return current, True
        progress = db.get(TeachingProgress, session_id)
        _sync_counters(current, progress)
        _close(current, result=ACTIVITY_INTERRUPTED, reason="idle_timeout", ended_at=last)
        record_event(
            db,
            course_id=current.course_id,
            point_id=current.knowledge_point_id,
            session_id=session_id,
            activity_id=current.id,
            event_type="ACTIVITY_IDLE_CLOSED",
            detail=f"超过 {IDLE_TIMEOUT_SECONDS // 60} 分钟没有心跳，按空闲结束。",
        )
        db.flush()

    activity = LearningActivity(
        course_id=course.id,
        knowledge_point_id=point.id,
        session_id=row.id,
        final_stage="TEACH",
    )
    try:
        with db.begin_nested():
            db.add(activity)
            db.flush()
    except IntegrityError:
        db.rollback()
        existing = active_activity(db, session_id)
        if existing is None:
            raise
        return existing, True
    record_event(
        db,
        course_id=course.id,
        point_id=point.id,
        session_id=row.id,
        activity_id=activity.id,
        event_type="ACTIVITY_STARTED",
        detail="进入学习教室。",
    )
    if commit:
        db.commit()
        db.refresh(activity)
    else:
        db.flush()
    return activity, False


def ensure_activity(db: Session, session_id: int) -> LearningActivity:
    """教学动作开始前保证存在活动记录（前端未上报时也能统计）。"""
    current = active_activity(db, session_id)
    if current is not None:
        last = utc(current.last_heartbeat_at) or utc(current.started_at) or now()
        if now() - last <= timedelta(seconds=IDLE_TIMEOUT_SECONDS):
            return current
    activity, _reused = start_activity(db, session_id, commit=False)
    return activity


def heartbeat(db: Session, activity_id: int, active_seconds_delta: int) -> tuple[LearningActivity, bool]:
    """记录一次心跳。返回 (activity, closed)；closed=True 表示客户端应重新开始活动。"""
    activity = db.get(LearningActivity, activity_id)
    if activity is None:
        raise NotFoundError(f"学习活动 {activity_id} 不存在")
    if activity.status != ACTIVITY_ACTIVE:
        return activity, True

    current = now()
    last = utc(activity.last_heartbeat_at) or utc(activity.started_at) or current
    gap = max(0.0, (current - last).total_seconds())
    if gap > IDLE_TIMEOUT_SECONDS:
        progress = db.get(TeachingProgress, activity.session_id)
        _sync_counters(activity, progress)
        _close(activity, result=ACTIVITY_INTERRUPTED, reason="idle_timeout", ended_at=last)
        record_event(
            db,
            course_id=activity.course_id,
            point_id=activity.knowledge_point_id,
            session_id=activity.session_id,
            activity_id=activity.id,
            event_type="ACTIVITY_IDLE_CLOSED",
            detail=f"心跳间隔 {int(gap)} 秒，超过空闲上限。",
        )
        db.commit()
        db.refresh(activity)
        return activity, True

    try:
        delta = int(active_seconds_delta)
    except (TypeError, ValueError):
        delta = 0
    delta = max(0, min(delta, MAX_HEARTBEAT_DELTA_SECONDS, int(gap) + 5))
    activity.active_seconds += delta
    activity.heartbeat_count += 1
    activity.last_heartbeat_at = current
    progress = db.get(TeachingProgress, activity.session_id)
    _sync_counters(activity, progress)
    db.commit()
    db.refresh(activity)
    return activity, False


def finish_activity(
    db: Session,
    activity_id: int,
    *,
    result: str = ACTIVITY_FINISHED,
    reason: str = "user_exit",
) -> LearningActivity:
    activity = db.get(LearningActivity, activity_id)
    if activity is None:
        raise NotFoundError(f"学习活动 {activity_id} 不存在")
    if activity.status != ACTIVITY_ACTIVE:
        return activity
    progress = db.get(TeachingProgress, activity.session_id)
    _sync_counters(activity, progress)
    _close(activity, result=result, reason=reason)
    record_event(
        db,
        course_id=activity.course_id,
        point_id=activity.knowledge_point_id,
        session_id=activity.session_id,
        activity_id=activity.id,
        event_type="ACTIVITY_FINISHED",
        detail=reason,
    )
    db.commit()
    db.refresh(activity)
    return activity


def sync_from_progress(db: Session, session_id: int, progress: TeachingProgress | None = None) -> None:
    """把教学进度的阶段与计数同步到当前活动（不提交事务）。"""
    activity = active_activity(db, session_id)
    if activity is None:
        return
    _sync_counters(activity, progress if progress is not None else db.get(TeachingProgress, session_id))


def complete_for_session(db: Session, session_id: int, *, reason: str = "verified") -> None:
    activity = active_activity(db, session_id)
    if activity is None:
        return
    _sync_counters(activity, db.get(TeachingProgress, session_id))
    _close(activity, result=ACTIVITY_COMPLETED, reason=reason)
    record_event(
        db,
        course_id=activity.course_id,
        point_id=activity.knowledge_point_id,
        session_id=session_id,
        activity_id=activity.id,
        event_type="ACTIVITY_COMPLETED",
        detail=reason,
    )


def interrupt_for_session(db: Session, session_id: int, reason: str) -> None:
    activity = active_activity(db, session_id)
    if activity is None:
        return
    _sync_counters(activity, db.get(TeachingProgress, session_id))
    _close(activity, result=ACTIVITY_INTERRUPTED, reason=reason)
    record_event(
        db,
        course_id=activity.course_id,
        point_id=activity.knowledge_point_id,
        session_id=session_id,
        activity_id=activity.id,
        event_type="ACTIVITY_INTERRUPTED",
        detail=reason,
    )


def close_stale_activities(db: Session) -> int:
    """启动时关闭空闲超时的活动（后端重启后不会继续累计时间）。"""
    cutoff = now() - timedelta(seconds=IDLE_TIMEOUT_SECONDS)
    stale = db.scalars(
        select(LearningActivity).where(
            LearningActivity.status == ACTIVITY_ACTIVE,
            LearningActivity.last_heartbeat_at < cutoff,
        )
    ).all()
    count = 0
    for activity in stale:
        last = utc(activity.last_heartbeat_at) or utc(activity.started_at) or now()
        _sync_counters(activity, db.get(TeachingProgress, activity.session_id))
        _close(activity, result=ACTIVITY_INTERRUPTED, reason="idle_timeout", ended_at=last)
        record_event(
            db,
            course_id=activity.course_id,
            point_id=activity.knowledge_point_id,
            session_id=activity.session_id,
            activity_id=activity.id,
            event_type="ACTIVITY_IDLE_CLOSED",
            detail="服务重启时发现空闲活动，按最后心跳时间结束。",
        )
        count += 1
    if count:
        db.commit()
        logger.info("已关闭 %s 条空闲学习活动", count)
    return count


def activity_out(activity: LearningActivity) -> dict:
    return {
        "id": activity.id,
        "courseId": activity.course_id,
        "knowledgePointId": activity.knowledge_point_id,
        "sessionId": activity.session_id,
        "status": activity.status,
        "result": activity.result,
        "endReason": activity.end_reason,
        "startedAt": utc(activity.started_at),
        "lastHeartbeatAt": utc(activity.last_heartbeat_at),
        "endedAt": utc(activity.ended_at),
        "activeSeconds": activity.active_seconds,
        "heartbeatCount": activity.heartbeat_count,
        "finalStage": activity.final_stage,
        "completedStages": json.loads(activity.completed_stages or "[]"),
        "checkAttempts": activity.check_attempts,
        "pairAttempts": activity.pair_attempts,
        "verifyAttempts": activity.verify_attempts,
        "hintCount": activity.hint_count,
        "verifyHintCount": activity.verify_hint_count,
        "createdAt": utc(activity.created_at),
    }
