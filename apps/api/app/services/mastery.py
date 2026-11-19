"""知识点掌握状态（P1.5）。

状态只能由教学状态机的真实事件推导，AI 不能直接写：
NOT_STARTED → INTRODUCED → UNDERSTANDING → GUIDED_PRACTICE → INDEPENDENT，
验证失败或反复出错进入 NEEDS_REVIEW；任何变化都写 mastery_history。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..db.models import Course, KnowledgePoint, LearningEvent, MasteryHistory, TeachingProgress

NOT_STARTED = "NOT_STARTED"
INTRODUCED = "INTRODUCED"
UNDERSTANDING = "UNDERSTANDING"
GUIDED_PRACTICE = "GUIDED_PRACTICE"
INDEPENDENT = "INDEPENDENT"
NEEDS_REVIEW = "NEEDS_REVIEW"

STATES: tuple[str, ...] = (
    NOT_STARTED,
    INTRODUCED,
    UNDERSTANDING,
    GUIDED_PRACTICE,
    INDEPENDENT,
    NEEDS_REVIEW,
)

LABELS: dict[str, str] = {
    NOT_STARTED: "未接触",
    INTRODUCED: "已接触",
    UNDERSTANDING: "理解中",
    GUIDED_PRACTICE: "引导练习",
    INDEPENDENT: "独立完成",
    NEEDS_REVIEW: "需要复习",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def safe_state(value: str | None) -> str:
    return value if value in STATES else NOT_STARTED


def label(value: str | None) -> str:
    return LABELS.get(safe_state(value), LABELS[NOT_STARTED])


def state_from_progress(progress: TeachingProgress) -> str:
    """按当前阶段与验证结果推导状态；没有证据时保持 NOT_STARTED。"""
    if progress.current_stage == "NEXT":
        if progress.verification_result == "PASSED":
            return INDEPENDENT if not progress.verify_hint_count else GUIDED_PRACTICE
        return NEEDS_REVIEW if progress.verification_result in ("FAILED", "NEEDS_REVIEW") else INTRODUCED
    if progress.verification_result in ("FAILED", "NEEDS_REVIEW") and progress.current_stage in ("PAIR", "VERIFY"):
        return NEEDS_REVIEW
    if progress.current_stage in ("TEACH", "DEMO"):
        return INTRODUCED if safe_state(progress.mastery_state) != NEEDS_REVIEW else NEEDS_REVIEW
    if progress.current_stage == "CHECK":
        return UNDERSTANDING
    if progress.current_stage == "PAIR":
        return GUIDED_PRACTICE
    if progress.current_stage == "VERIFY":
        return UNDERSTANDING if not progress.verify_hint_count else GUIDED_PRACTICE
    return safe_state(progress.mastery_state)


def state_for_outcome(progress: TeachingProgress, stage: str, verdict: str | None) -> str:
    """结合刚发生的评价结果推导状态。"""
    if stage == "VERIFY":
        if verdict in ("FAILED", "NEEDS_REVIEW"):
            return NEEDS_REVIEW
        if verdict == "PASSED":
            return INDEPENDENT if not progress.verify_hint_count else GUIDED_PRACTICE
    if stage == "CHECK":
        if verdict == "CORRECT":
            return GUIDED_PRACTICE
        if verdict in ("INCORRECT", "PARTIAL", "UNCLEAR"):
            return NEEDS_REVIEW if safe_state(progress.mastery_state) == NEEDS_REVIEW else UNDERSTANDING
    if stage == "PAIR":
        if verdict in ("INCORRECT", "PARTIAL", "UNCLEAR"):
            return NEEDS_REVIEW if safe_state(progress.mastery_state) == NEEDS_REVIEW else GUIDED_PRACTICE
        if verdict == "CORRECT":
            return GUIDED_PRACTICE
    return state_from_progress(progress)


def apply(
    db: Session,
    *,
    point: KnowledgePoint,
    progress: TeachingProgress,
    course: Course | None = None,
    stage: str | None = None,
    verdict: str | None = None,
    action: str = "",
    reason: str = "",
    evidence: dict | None = None,
) -> tuple[str, str | None]:
    """把推导出的状态写入知识点并记录历史。返回 (当前状态, 变化前的状态)。"""
    target = state_for_outcome(progress, stage or progress.current_stage, verdict)
    previous = safe_state(point.mastery_state)
    # 已独立完成的知识点不会因为一次模糊回答被降回“理解中”；只有明确失败或新的练习才改变状态。
    if previous == INDEPENDENT and target in (NOT_STARTED, INTRODUCED, UNDERSTANDING):
        target = INDEPENDENT
    if target == previous:
        return previous, None

    point.mastery_state = target
    point.mastery_updated_at = now()
    current_course = course
    if current_course is None:
        from ..db.models import Chapter

        chapter = db.get(Chapter, point.chapter_id)
        current_course = db.get(Course, chapter.course_id) if chapter else None
    if current_course is not None:
        current_course.last_studied_at = now()

    # 待复习写入课程进度；不把已完成知识点降级，保留历史完成证据。
    if target == NEEDS_REVIEW and point.learning_status != "completed":
        point.learning_status = "review"
        point.last_studied_at = now()
    elif target in (INTRODUCED, UNDERSTANDING, GUIDED_PRACTICE) and point.learning_status == "not_started":
        point.learning_status = "in_progress"
        point.last_studied_at = now()

    payload = {
        "stage": stage or progress.current_stage,
        "action": action,
        "verdict": verdict,
        "checkAttempts": progress.check_attempts,
        "pairAttempts": progress.pair_attempts,
        "verifyAttempts": progress.verify_attempts,
        "hintCount": progress.hint_count,
        "verifyHintCount": progress.verify_hint_count,
        **(evidence or {}),
    }
    db.add(
        MasteryHistory(
            course_id=current_course.id if current_course is not None else point.chapter.course_id,
            knowledge_point_id=point.id,
            session_id=progress.session_id,
            activity_id=payload.get("activityId"),
            from_state=previous,
            to_state=target,
            reason=reason[:2000],
            evidence=json.dumps(payload, ensure_ascii=False),
        )
    )
    db.add(
        LearningEvent(
            activity_id=payload.get("activityId"),
            course_id=current_course.id if current_course is not None else point.chapter.course_id,
            knowledge_point_id=point.id,
            session_id=progress.session_id,
            event_type="MASTERY_CHANGED",
            detail=f"{previous} → {target}：{reason}"[:4000],
        )
    )
    return target, previous
