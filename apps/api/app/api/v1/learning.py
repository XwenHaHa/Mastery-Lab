"""学习档案、学习历史、掌握情况、错题与断点续学接口（P1.5）。

统一返回 `{code, message, data}`；所有查询都校验课程/知识点归属，
不接受伪造 ID 读取其他课程的数据，也不返回任何模型密钥。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.response import ApiResponse, NotFoundError, ValidationError, success
from ...db.models import (
    Chapter,
    Course,
    KnowledgePoint,
    LearningActivity,
    MistakeOccurrence,
    MistakeRecord,
)
from ...schemas.learning import (
    ActivityFinishRequest,
    ActivityHeartbeatRequest,
    ActivityStartRequest,
    BreakpointSaveRequest,
    MistakeStatusRequest,
)
from ...services import archive, breakpoints, classroom_service, learning_record, mistakes
from ..deps import db_session

router = APIRouter(prefix="/learning", tags=["learning"])


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _activity_payload(activity: LearningActivity, *, reused: bool = False, closed: bool = False) -> dict:
    return {
        **learning_record.activity_out(activity),
        "reused": reused,
        "closed": closed,
        "heartbeatIntervalSeconds": learning_record.HEARTBEAT_INTERVAL_SECONDS,
        "idleTimeoutSeconds": learning_record.IDLE_TIMEOUT_SECONDS,
    }


# ------------------------------------------------------------------ 学习活动

@router.post("/activities/start", response_model=ApiResponse, summary="开始或复用一次学习活动")
def start_activity(payload: ActivityStartRequest, session: Session = Depends(db_session)) -> ApiResponse:
    course, _chapter, point = classroom_service.load_entities(
        session, payload.course_id, payload.knowledge_point_id
    )
    if payload.session_id is not None:
        row = classroom_service.get_session_row(session, payload.session_id)
        if row.course_id != course.id or row.knowledge_point_id != point.id:
            raise NotFoundError("学习会话与课程/知识点不匹配")
        session_id = row.id
    else:
        opened = classroom_service.open_session(
            session, course_id=course.id, point_id=point.id
        )
        session_id = opened.id
    activity, reused = learning_record.start_activity(session, session_id)
    return success(_activity_payload(activity, reused=reused))


@router.post("/activities/{activity_id}/heartbeat", response_model=ApiResponse, summary="上报有效学习时长")
def heartbeat(
    activity_id: int,
    payload: ActivityHeartbeatRequest,
    session: Session = Depends(db_session),
) -> ApiResponse:
    activity, closed = learning_record.heartbeat(session, activity_id, payload.active_seconds_delta)
    return success(
        _activity_payload(activity, closed=closed),
        message="已结束空闲学习活动，请重新开始" if closed else "ok",
    )


@router.post("/activities/{activity_id}/finish", response_model=ApiResponse, summary="结束本次学习活动")
def finish_activity(
    activity_id: int,
    payload: ActivityFinishRequest,
    session: Session = Depends(db_session),
) -> ApiResponse:
    activity = learning_record.finish_activity(
        session, activity_id, result=payload.result, reason=payload.reason
    )
    return success(_activity_payload(activity))


# ------------------------------------------------------------------ 断点续学

@router.get("/resume", response_model=ApiResponse, summary="最近一次可恢复的学习位置")
def resume(session: Session = Depends(db_session)) -> ApiResponse:
    return success(breakpoints.resume_info(session))


@router.get("/sessions/{session_id}/breakpoint", response_model=ApiResponse, summary="读取断点快照")
def get_breakpoint(session_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    row = breakpoints.get_or_create(session, session_id)
    session.commit()
    return success(breakpoints.breakpoint_out(session, row))


@router.put("/sessions/{session_id}/breakpoint", response_model=ApiResponse, summary="保存草稿与输入状态")
def save_breakpoint(
    session_id: int,
    payload: BreakpointSaveRequest,
    session: Session = Depends(db_session),
) -> ApiResponse:
    row, accepted = breakpoints.save(
        session,
        session_id,
        client_seq=payload.client_seq,
        draft_answer=payload.draft_answer,
        input_mode=payload.input_mode,
    )
    data = {**breakpoints.breakpoint_out(session, row), "accepted": accepted}
    return success(data, message="ok" if accepted else "服务器已有更新的进度，本次草稿未覆盖")


# ------------------------------------------------------------------ 档案与统计

@router.get("/overview", response_model=ApiResponse, summary="学习档案总览")
def overview(session: Session = Depends(db_session)) -> ApiResponse:
    return success(archive.overview(session))


@router.get("/courses", response_model=ApiResponse, summary="按课程查看学习进度")
def course_progress(session: Session = Depends(db_session)) -> ApiResponse:
    return success(archive.course_progress(session))


@router.get("/mastery", response_model=ApiResponse, summary="知识点掌握情况")
def mastery_overview(
    course_id: int | None = Query(default=None, alias="courseId", gt=0),
    chapter_id: int | None = Query(default=None, alias="chapterId", gt=0),
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(archive.mastery_overview(session, course_id, chapter_id))


@router.get("/history", response_model=ApiResponse, summary="学习历史列表")
def history(
    course_id: int | None = Query(default=None, alias="courseId", gt=0),
    point_id: int | None = Query(default=None, alias="pointId", gt=0),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(
        archive.history(
            session,
            course_id=course_id,
            point_id=point_id,
            date_from=_as_utc(date_from),
            date_to=_as_utc(date_to),
            limit=limit,
            offset=offset,
        )
    )


@router.get("/history/{activity_id}", response_model=ApiResponse, summary="一次学习的详细过程")
def history_detail(activity_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(archive.history_detail(session, activity_id))


@router.get("/report", response_model=ApiResponse, summary="本周学习报告")
def report(
    course_id: int | None = Query(default=None, alias="courseId", gt=0),
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(archive.report(session, course_id=course_id))


# ------------------------------------------------------------------ 错题与薄弱点

def _mistake_out(
    record: MistakeRecord,
    course: Course | None,
    point: KnowledgePoint | None,
    chapter: Chapter | None,
) -> dict:
    return {
        "id": record.id,
        "courseId": record.course_id,
        "courseTitle": course.title if course else "",
        "knowledgePointId": record.knowledge_point_id,
        "pointTitle": point.title if point else "",
        "chapterTitle": chapter.title if chapter else "",
        "sessionId": record.session_id,
        "activityId": record.activity_id,
        "stage": record.stage,
        "errorType": record.error_type,
        "errorTypeLabel": mistakes.ERROR_TYPE_LABELS.get(record.error_type, record.error_type),
        "question": record.question,
        "userAnswer": record.user_answer,
        "correctAnswer": record.correct_answer,
        "errorReason": record.error_reason,
        "correction": record.correction,
        "misconceptions": json.loads(record.misconceptions or "[]"),
        "status": record.status,
        "occurrenceCount": record.occurrence_count,
        "firstSeenAt": classroom_service._utc(record.first_seen_at),
        "lastSeenAt": classroom_service._utc(record.last_seen_at),
        "resolvedAt": classroom_service._utc(record.resolved_at),
    }


@router.get("/mistakes", response_model=ApiResponse, summary="错题与薄弱点列表")
def list_mistakes(
    course_id: int | None = Query(default=None, alias="courseId", gt=0),
    point_id: int | None = Query(default=None, alias="pointId", gt=0),
    error_type: str | None = Query(default=None, alias="errorType", pattern="^(concept|practice|verification)$"),
    status: str | None = Query(default=None, pattern="^(open|understood)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(db_session),
) -> ApiResponse:
    if course_id is not None and session.get(Course, course_id) is None:
        raise NotFoundError(f"课程 {course_id} 不存在")
    if point_id is not None and session.get(KnowledgePoint, point_id) is None:
        raise NotFoundError(f"知识点 {point_id} 不存在")

    stmt = select(MistakeRecord)
    count_stmt = select(func.count(MistakeRecord.id))
    conditions = []
    if course_id is not None:
        conditions.append(MistakeRecord.course_id == course_id)
    if point_id is not None:
        conditions.append(MistakeRecord.knowledge_point_id == point_id)
    if error_type is not None:
        conditions.append(MistakeRecord.error_type == error_type)
    if status is not None:
        conditions.append(MistakeRecord.status == status)
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

    total = session.scalar(count_stmt) or 0
    rows = session.scalars(
        stmt.order_by(MistakeRecord.last_seen_at.desc(), MistakeRecord.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    course_map = {course.id: course for course in session.scalars(select(Course)).all()}
    point_map = {point.id: point for point in session.scalars(select(KnowledgePoint)).all()}
    chapter_map = {chapter.id: chapter for chapter in session.scalars(select(Chapter)).all()}
    items = [
        _mistake_out(
            record,
            course_map.get(record.course_id),
            point_map.get(record.knowledge_point_id),
            chapter_map.get(point_map[record.knowledge_point_id].chapter_id)
            if record.knowledge_point_id in point_map
            else None,
        )
        for record in rows
    ]
    return success({"total": int(total), "items": items})


@router.get("/mistakes/{mistake_id}", response_model=ApiResponse, summary="错题详情与发生历史")
def mistake_detail(mistake_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    record = session.get(MistakeRecord, mistake_id)
    if record is None:
        raise NotFoundError(f"错题 {mistake_id} 不存在")
    course = session.get(Course, record.course_id)
    point = session.get(KnowledgePoint, record.knowledge_point_id)
    chapter = session.get(Chapter, point.chapter_id) if point else None
    occurrences = session.scalars(
        select(MistakeOccurrence)
        .where(MistakeOccurrence.mistake_id == record.id)
        .order_by(MistakeOccurrence.id.desc())
    ).all()
    data = _mistake_out(record, course, point, chapter)
    data["occurrences"] = [
        {
            "id": item.id,
            "activityId": item.activity_id,
            "stage": item.stage,
            "verdict": item.verdict,
            "question": item.question,
            "userAnswer": item.user_answer,
            "feedback": item.feedback,
            "createdAt": classroom_service._utc(item.created_at),
        }
        for item in occurrences
    ]
    return success(data)


@router.patch("/mistakes/{mistake_id}", response_model=ApiResponse, summary="标记错题已理解或重新打开")
def update_mistake(
    mistake_id: int,
    payload: MistakeStatusRequest,
    session: Session = Depends(db_session),
) -> ApiResponse:
    record = session.get(MistakeRecord, mistake_id)
    if record is None:
        raise NotFoundError(f"错题 {mistake_id} 不存在")
    point = session.get(KnowledgePoint, record.knowledge_point_id)
    chapter = session.get(Chapter, point.chapter_id) if point else None
    course = session.get(Course, record.course_id)
    if record.status == payload.status:
        return success(_mistake_out(record, course, point, chapter))
    record = mistakes.mark_status(session, record, payload.status)
    return success(_mistake_out(record, course, point, chapter))


@router.post("/mistakes/{mistake_id}/practice", response_model=ApiResponse, summary="重新练习该知识点")
def practice_mistake(mistake_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    record = session.get(MistakeRecord, mistake_id)
    if record is None:
        raise NotFoundError(f"错题 {mistake_id} 不存在")
    opened = classroom_service.open_session(
        session, course_id=record.course_id, point_id=record.knowledge_point_id
    )
    return success(
        {
            "courseId": record.course_id,
            "knowledgePointId": record.knowledge_point_id,
            "sessionId": opened.id,
            "route": f"/courses/{record.course_id}/classroom?point={record.knowledge_point_id}",
        }
    )
