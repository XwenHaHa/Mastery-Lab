"""学习档案、历史、掌握情况与报告（P1.5）。

所有数字都从 learning_activities / mastery_history / mistake_records /
teaching_events / teaching_evaluations 汇总，不使用任何模拟数据。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.response import NotFoundError
from ..db.models import (
    Chapter,
    ChatMessage,
    Course,
    KnowledgePoint,
    LearningActivity,
    LearningBreakpoint,
    MasteryHistory,
    MistakeRecord,
    TeachingEvaluation,
    TeachingEvent,
    TeachingOperation,
    TeachingProgress,
)
from . import classroom_service, learning, mastery


def now() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime | None) -> datetime | None:
    return classroom_service._utc(value)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _active_courses(db: Session) -> list[Course]:
    return list(db.scalars(select(Course).where(Course.status == "active").order_by(Course.id)).all())


def _points(db: Session, course_id: int | None = None, chapter_id: int | None = None) -> list[KnowledgePoint]:
    stmt = select(KnowledgePoint).join(Chapter, KnowledgePoint.chapter_id == Chapter.id)
    if course_id is not None:
        stmt = stmt.where(Chapter.course_id == course_id)
    if chapter_id is not None:
        stmt = stmt.where(KnowledgePoint.chapter_id == chapter_id)
    return list(db.scalars(stmt.order_by(Chapter.sort_order, KnowledgePoint.sort_order)).all())


def _question_text(content: str | None) -> str:
    if not content:
        return ""
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return content
    if isinstance(payload, dict):
        return str(payload.get("question") or content)
    return content


def _latest_mastery(db: Session, point_ids: list[int]) -> dict[int, MasteryHistory]:
    if not point_ids:
        return {}
    rows = db.scalars(
        select(MasteryHistory)
        .where(MasteryHistory.knowledge_point_id.in_(point_ids))
        .order_by(MasteryHistory.id.desc())
    ).all()
    latest: dict[int, MasteryHistory] = {}
    for row in rows:
        latest.setdefault(row.knowledge_point_id, row)
    return latest


def _latest_breakpoints(db: Session) -> dict[int, LearningBreakpoint]:
    rows = db.scalars(select(LearningBreakpoint).order_by(LearningBreakpoint.updated_at.desc())).all()
    latest: dict[int, LearningBreakpoint] = {}
    for row in rows:
        latest.setdefault(row.course_id, row)
    return latest


def _week_bounds() -> tuple[datetime, datetime]:
    local = datetime.now().astimezone()
    start_local = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc), local.astimezone(timezone.utc)


def overview(db: Session) -> dict:
    courses = _active_courses(db)
    points = _points(db)
    activity_count = db.scalar(select(func.count(LearningActivity.id))) or 0
    effective_seconds = db.scalar(select(func.coalesce(func.sum(LearningActivity.active_seconds), 0))) or 0
    last_activity = db.scalars(select(LearningActivity).order_by(LearningActivity.last_heartbeat_at.desc())).first()

    studied_course_ids = set(
        db.scalars(select(LearningActivity.course_id).distinct()).all()
    ) | {
        chapter.course_id
        for course in courses
        for chapter in course.chapters
        for point in chapter.knowledge_points
        if point.learning_status != "not_started"
    }

    state_counts = {state: 0 for state in mastery.STATES}
    for point in points:
        state_counts[mastery.safe_state(point.mastery_state)] += 1

    completed = sum(1 for point in points if point.learning_status == "completed")
    in_progress = sum(1 for point in points if point.learning_status == "in_progress")
    needs_review = len(
        {
            point.id
            for point in points
            if point.mastery_state == mastery.NEEDS_REVIEW or point.learning_status == "review"
        }
    )
    last_studied = max(
        [value for value in [*(course.last_studied_at for course in courses), *( [last_activity.last_heartbeat_at] if last_activity else [] )] if value is not None],
        default=None,
    )

    week_start, week_end = _week_bounds()
    week_activities = db.scalars(
        select(LearningActivity).where(
            LearningActivity.started_at >= _naive_utc(week_start),
            LearningActivity.started_at <= _naive_utc(week_end),
        )
    ).all()
    week_seconds = sum(activity.active_seconds for activity in week_activities)
    week_points = {activity.knowledge_point_id for activity in week_activities}
    week_completed = db.scalar(
        select(func.count(func.distinct(MasteryHistory.knowledge_point_id))).where(
            MasteryHistory.to_state == mastery.INDEPENDENT,
            MasteryHistory.created_at >= _naive_utc(week_start),
            MasteryHistory.created_at <= _naive_utc(week_end),
        )
    ) or 0

    return {
        "effectiveSeconds": int(effective_seconds),
        "activityCount": int(activity_count),
        "studiedCourseCount": len(studied_course_ids),
        "totalCourseCount": len(courses),
        "totalPoints": len(points),
        "completedPoints": completed,
        "inProgressPoints": in_progress,
        "needsReviewPoints": needs_review,
        "independentPoints": state_counts[mastery.INDEPENDENT],
        "masteryCounts": [{"state": state, "label": mastery.label(state), "count": state_counts[state]} for state in mastery.STATES],
        "lastStudiedAt": utc(last_studied),
        "week": {
            "effectiveSeconds": int(week_seconds),
            "studiedPoints": len(week_points),
            "completedPoints": int(week_completed),
        },
    }


def course_progress(db: Session) -> list[dict]:
    courses = _active_courses(db)
    latest_breakpoints = _latest_breakpoints(db)
    latest_activities: dict[int, LearningActivity] = {}
    for activity in db.scalars(
        select(LearningActivity).order_by(LearningActivity.last_heartbeat_at.desc())
    ).all():
        latest_activities.setdefault(activity.course_id, activity)

    result: list[dict] = []
    for course in courses:
        points = [point for chapter in course.chapters for point in chapter.knowledge_points]
        counts = learning.status_counts(points)
        breakpoint = latest_breakpoints.get(course.id)
        activity = latest_activities.get(course.id)
        position_point = None
        position_chapter = ""
        if breakpoint is not None:
            position_point = next((point for point in points if point.id == breakpoint.knowledge_point_id), None)
        if position_point is None and activity is not None:
            position_point = next((point for point in points if point.id == activity.knowledge_point_id), None)
        if position_point is None:
            position_point = next((point for point in points if point.learning_status != "completed"), None)
        if position_point is not None:
            position_chapter = next(
                (chapter.title for chapter in course.chapters if chapter.id == position_point.chapter_id), ""
            )
        last_studied = max(
            [value for value in (course.last_studied_at, activity.last_heartbeat_at if activity else None) if value is not None],
            default=None,
        )
        result.append(
            {
                "courseId": course.id,
                "title": course.title,
                "icon": course.icon or "",
                "chapterCount": len(course.chapters),
                "knowledgePointCount": len(points),
                "completedPoints": counts.get(learning.STATUS_COMPLETED, 0),
                "inProgressPoints": counts.get(learning.STATUS_IN_PROGRESS, 0),
                "needsReviewPoints": sum(1 for point in points if point.mastery_state == mastery.NEEDS_REVIEW),
                "progress": learning.progress_from_counts(counts),
                "currentPosition": (
                    {
                        "pointId": position_point.id,
                        "title": position_point.title,
                        "chapterTitle": position_chapter,
                    }
                    if position_point
                    else None
                ),
                "lastStudiedAt": utc(last_studied),
            }
        )
    return result


def mastery_overview(db: Session, course_id: int | None = None, chapter_id: int | None = None) -> dict:
    if course_id is not None and db.get(Course, course_id) is None:
        raise NotFoundError(f"课程 {course_id} 不存在")
    if chapter_id is not None and db.get(Chapter, chapter_id) is None:
        raise NotFoundError(f"章节 {chapter_id} 不存在")

    points = _points(db, course_id, chapter_id)
    point_ids = [point.id for point in points]
    latest = _latest_mastery(db, point_ids)
    counts = {state: 0 for state in mastery.STATES}
    for point in points:
        counts[mastery.safe_state(point.mastery_state)] += 1

    courses = _active_courses(db)
    course_map = {course.id: course for course in courses}
    grouped: dict[int, dict] = {}
    for point in points:
        chapter = next(
            (chapter for course in courses for chapter in course.chapters if chapter.id == point.chapter_id), None
        )
        if chapter is None:
            continue
        course = course_map.get(chapter.course_id)
        if course is None:
            continue
        course_entry = grouped.setdefault(
            course.id,
            {"courseId": course.id, "title": course.title, "icon": course.icon or "", "chapters": []},
        )
        chapter_entry = next(
            (item for item in course_entry["chapters"] if item["chapterId"] == chapter.id), None
        )
        if chapter_entry is None:
            chapter_entry = {"chapterId": chapter.id, "title": chapter.title, "points": []}
            course_entry["chapters"].append(chapter_entry)
        history = latest.get(point.id)
        chapter_entry["points"].append(
            {
                "pointId": point.id,
                "title": point.title,
                "masteryState": mastery.safe_state(point.mastery_state),
                "masteryLabel": mastery.label(point.mastery_state),
                "learningStatus": learning.safe_status(point.learning_status),
                "masteryUpdatedAt": utc(point.mastery_updated_at),
                "lastChangedAt": utc(history.created_at) if history else None,
                "lastReason": history.reason if history else "",
            }
        )

    return {
        "total": len(points),
        "states": [{"state": state, "label": mastery.label(state), "count": counts[state]} for state in mastery.STATES],
        "courses": list(grouped.values()),
    }


def history(
    db: Session,
    *,
    course_id: int | None = None,
    point_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    if course_id is not None and db.get(Course, course_id) is None:
        raise NotFoundError(f"课程 {course_id} 不存在")
    if point_id is not None and db.get(KnowledgePoint, point_id) is None:
        raise NotFoundError(f"知识点 {point_id} 不存在")

    stmt = select(LearningActivity)
    count_stmt = select(func.count(LearningActivity.id))
    if course_id is not None:
        stmt = stmt.where(LearningActivity.course_id == course_id)
        count_stmt = count_stmt.where(LearningActivity.course_id == course_id)
    if point_id is not None:
        stmt = stmt.where(LearningActivity.knowledge_point_id == point_id)
        count_stmt = count_stmt.where(LearningActivity.knowledge_point_id == point_id)
    if date_from is not None:
        stmt = stmt.where(LearningActivity.started_at >= _naive_utc(date_from))
        count_stmt = count_stmt.where(LearningActivity.started_at >= _naive_utc(date_from))
    if date_to is not None:
        stmt = stmt.where(LearningActivity.started_at <= _naive_utc(date_to))
        count_stmt = count_stmt.where(LearningActivity.started_at <= _naive_utc(date_to))

    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(LearningActivity.started_at.desc(), LearningActivity.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    course_map = {course.id: course for course in _active_courses(db)}
    point_map = {point.id: point for point in _points(db)}
    chapter_map = {chapter.id: chapter for course in course_map.values() for chapter in course.chapters}

    items = []
    for row in rows:
        point = point_map.get(row.knowledge_point_id)
        course = course_map.get(row.course_id)
        chapter = chapter_map.get(point.chapter_id) if point else None
        items.append(
            {
                "id": row.id,
                "courseId": row.course_id,
                "courseTitle": course.title if course else "",
                "knowledgePointId": row.knowledge_point_id,
                "pointTitle": point.title if point else "",
                "chapterTitle": chapter.title if chapter else "",
                "startedAt": utc(row.started_at),
                "endedAt": utc(row.ended_at),
                "activeSeconds": row.active_seconds,
                "status": row.status,
                "result": row.result,
                "finalStage": row.final_stage,
                "completedStages": json.loads(row.completed_stages or "[]"),
                "checkAttempts": row.check_attempts,
                "pairAttempts": row.pair_attempts,
                "verifyAttempts": row.verify_attempts,
                "hintCount": row.hint_count,
            }
        )
    return {"total": int(total), "items": items}


def history_detail(db: Session, activity_id: int) -> dict:
    activity = db.get(LearningActivity, activity_id)
    if activity is None:
        raise NotFoundError(f"学习活动 {activity_id} 不存在")
    course = db.get(Course, activity.course_id)
    point = db.get(KnowledgePoint, activity.knowledge_point_id)
    chapter = db.get(Chapter, point.chapter_id) if point else None
    start = _naive_utc(utc(activity.started_at) or now())
    end = _naive_utc(utc(activity.ended_at) or now())

    events = db.scalars(
        select(TeachingEvent)
        .where(
            TeachingEvent.session_id == activity.session_id,
            TeachingEvent.created_at >= start,
            TeachingEvent.created_at <= end,
        )
        .order_by(TeachingEvent.id)
    ).all()
    evaluations = db.execute(
        select(TeachingEvaluation, TeachingOperation)
        .join(TeachingOperation, TeachingEvaluation.operation_id == TeachingOperation.id)
        .where(
            TeachingEvaluation.session_id == activity.session_id,
            TeachingEvaluation.created_at >= start,
            TeachingEvaluation.created_at <= end,
        )
        .order_by(TeachingEvaluation.id)
    ).all()
    message_ids = {
        message_id
        for _evaluation, operation in evaluations
        for message_id in (operation.question_message_id, operation.user_message_id)
        if message_id is not None
    }
    messages = {
        message.id: message
        for message in db.scalars(select(ChatMessage).where(ChatMessage.id.in_(message_ids))).all()
    } if message_ids else {}
    mistake_rows = db.scalars(
        select(MistakeRecord)
        .where(MistakeRecord.activity_id == activity.id)
        .order_by(MistakeRecord.id)
    ).all()
    progress = db.get(TeachingProgress, activity.session_id)

    return {
        "activity": {
            "id": activity.id,
            "courseId": activity.course_id,
            "courseTitle": course.title if course else "",
            "knowledgePointId": activity.knowledge_point_id,
            "pointTitle": point.title if point else "",
            "chapterTitle": chapter.title if chapter else "",
            "startedAt": utc(activity.started_at),
            "endedAt": utc(activity.ended_at),
            "activeSeconds": activity.active_seconds,
            "status": activity.status,
            "result": activity.result,
            "endReason": activity.end_reason,
            "finalStage": activity.final_stage,
            "completedStages": json.loads(activity.completed_stages or "[]"),
            "checkAttempts": activity.check_attempts,
            "pairAttempts": activity.pair_attempts,
            "verifyAttempts": activity.verify_attempts,
            "hintCount": activity.hint_count,
            "verifyHintCount": activity.verify_hint_count,
            "summary": progress.summary if progress else "",
        },
        "events": [
            {
                "id": item.id,
                "roundNumber": item.round_number,
                "fromStage": item.from_stage,
                "toStage": item.to_stage,
                "type": item.event_type,
                "detail": item.detail,
                "createdAt": utc(item.created_at),
            }
            for item in events
        ],
        "evaluations": [
            {
                "id": evaluation.id,
                "stage": evaluation.stage,
                "verdict": evaluation.verdict,
                "hintCount": evaluation.hint_count,
                "question": _question_text(messages[operation.question_message_id].content)
                if operation.question_message_id in messages
                else "",
                "answer": messages[operation.user_message_id].content
                if operation.user_message_id in messages
                else "",
                "result": json.loads(evaluation.payload),
                "createdAt": utc(evaluation.created_at),
            }
            for evaluation, operation in evaluations
        ],
        "mistakes": [
            {
                "id": record.id,
                "stage": record.stage,
                "errorType": record.error_type,
                "question": record.question,
                "userAnswer": record.user_answer,
                "errorReason": record.error_reason,
                "correction": record.correction,
                "status": record.status,
                "occurrenceCount": record.occurrence_count,
                "lastSeenAt": utc(record.last_seen_at),
            }
            for record in mistake_rows
        ],
    }


def report(db: Session, *, course_id: int | None = None) -> dict:
    if course_id is not None and db.get(Course, course_id) is None:
        raise NotFoundError(f"课程 {course_id} 不存在")
    week_start, week_end = _week_bounds()
    start_naive = _naive_utc(week_start)
    end_naive = _naive_utc(week_end)

    activity_stmt = select(LearningActivity).where(
        LearningActivity.started_at >= start_naive,
        LearningActivity.started_at <= end_naive,
    )
    if course_id is not None:
        activity_stmt = activity_stmt.where(LearningActivity.course_id == course_id)
    activities = db.scalars(activity_stmt).all()
    week_seconds = sum(activity.active_seconds for activity in activities)
    week_points = {activity.knowledge_point_id for activity in activities}
    per_course: dict[int, int] = {}
    for activity in activities:
        per_course[activity.course_id] = per_course.get(activity.course_id, 0) + activity.active_seconds

    mastery_stmt = select(MasteryHistory).where(
        MasteryHistory.created_at >= start_naive,
        MasteryHistory.created_at <= end_naive,
    )
    if course_id is not None:
        mastery_stmt = mastery_stmt.where(MasteryHistory.course_id == course_id)
    mastery_rows = db.scalars(mastery_stmt.order_by(MasteryHistory.id.desc())).all()
    completed_points = {row.knowledge_point_id for row in mastery_rows if row.to_state == mastery.INDEPENDENT}

    mistake_stmt = select(MistakeRecord).where(MistakeRecord.status == "open")
    if course_id is not None:
        mistake_stmt = mistake_stmt.where(MistakeRecord.course_id == course_id)
    mistakes = db.scalars(
        mistake_stmt.order_by(MistakeRecord.occurrence_count.desc(), MistakeRecord.last_seen_at.desc()).limit(8)
    ).all()

    course_map = {course.id: course for course in _active_courses(db)}
    point_map = {point.id: point for point in _points(db)}

    course_report = None
    if course_id is not None:
        course = course_map.get(course_id)
        if course is not None:
            points = [point for chapter in course.chapters for point in chapter.knowledge_points]
            counts = learning.status_counts(points)
            course_report = {
                "courseId": course.id,
                "title": course.title,
                "progress": learning.progress_from_counts(counts),
                "knowledgePointCount": len(points),
                "completedPoints": counts.get(learning.STATUS_COMPLETED, 0),
                "weekSeconds": per_course.get(course.id, 0),
                "chapters": [
                    {
                        "chapterId": chapter.id,
                        "title": chapter.title,
                        "knowledgePointCount": len(chapter.knowledge_points),
                        "completedPoints": sum(
                            1 for point in chapter.knowledge_points if point.learning_status == "completed"
                        ),
                        "progress": learning.progress_from_counts(learning.status_counts(chapter.knowledge_points)),
                    }
                    for chapter in course.chapters
                ],
            }

    return {
        "period": "week",
        "from": week_start,
        "to": week_end,
        "weekSeconds": int(week_seconds),
        "weekStudiedPoints": len(week_points),
        "weekCompletedPoints": len(completed_points),
        "recentCourses": [
            {
                "courseId": cid,
                "title": course_map[cid].title if cid in course_map else "",
                "seconds": seconds,
            }
            for cid, seconds in sorted(per_course.items(), key=lambda item: item[1], reverse=True)
        ],
        "weakPoints": [
            {
                "mistakeId": record.id,
                "pointId": record.knowledge_point_id,
                "pointTitle": point_map.get(record.knowledge_point_id).title
                if record.knowledge_point_id in point_map
                else "",
                "courseId": record.course_id,
                "courseTitle": course_map.get(record.course_id).title
                if record.course_id in course_map
                else "",
                "stage": record.stage,
                "errorType": record.error_type,
                "occurrenceCount": record.occurrence_count,
                "lastSeenAt": utc(record.last_seen_at),
            }
            for record in mistakes
        ],
        "recentProgress": [
            {
                "pointId": row.knowledge_point_id,
                "pointTitle": point_map.get(row.knowledge_point_id).title
                if row.knowledge_point_id in point_map
                else "",
                "courseId": row.course_id,
                "courseTitle": course_map.get(row.course_id).title if row.course_id in course_map else "",
                "fromState": row.from_state,
                "fromLabel": mastery.label(row.from_state),
                "toState": row.to_state,
                "toLabel": mastery.label(row.to_state),
                "reason": row.reason,
                "createdAt": utc(row.created_at),
            }
            for row in mastery_rows[:8]
        ],
        "courseReport": course_report,
    }
