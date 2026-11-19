"""知识点掌握状态与长期掌握等级（P1.5 / P1.6-F）。

本轮表现（mastery_state）与长期掌握（mastery_level）分开：
- mastery_state：INTRODUCED → UNDERSTANDING → GUIDED_PRACTICE → INDEPENDENT，
  失败进入 NEEDS_REVIEW；一次 VERIFY 通过最多到 INDEPENDENT。
- mastery_level：0 未接触 / 1 已接触 / 2 已理解 / 3 引导练习 / 4 本轮独立 / 5 稳定掌握。
  4 → 5 需要至少两次跨轮/跨会话独立通过（间隔 ≥ 24 小时）且完成巩固。

状态与等级只能由教学证据写入，AI 不能直接声明。所有等级变化写 mastery_history。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    Chapter,
    Course,
    KnowledgePoint,
    LearningEvent,
    MasteryHistory,
    TeachingProgress,
)
from . import teaching_stages

NOT_STARTED = "NOT_STARTED"
INTRODUCED = "INTRODUCED"
UNDERSTANDING = "UNDERSTANDING"
GUIDED_PRACTICE = "GUIDED_PRACTICE"
INDEPENDENT = "INDEPENDENT"
NEEDS_REVIEW = "NEEDS_REVIEW"
STABLE = "STABLE"

STATES: tuple[str, ...] = (
    NOT_STARTED,
    INTRODUCED,
    UNDERSTANDING,
    GUIDED_PRACTICE,
    INDEPENDENT,
    NEEDS_REVIEW,
    STABLE,
)

LABELS: dict[str, str] = {
    NOT_STARTED: "未接触",
    INTRODUCED: "已接触",
    UNDERSTANDING: "理解中",
    GUIDED_PRACTICE: "引导练习",
    INDEPENDENT: "本轮独立完成",
    NEEDS_REVIEW: "需要复习",
    STABLE: "稳定掌握",
}

LEVEL_LABELS: dict[int, str] = {
    0: "未接触",
    1: "已接触",
    2: "已理解",
    3: "引导练习",
    4: "本轮独立",
    5: "稳定掌握",
}

# 旧数据只有 mastery_state、没有 mastery_level；按状态推导一个只读下限，避免回写历史。
_LEVEL_FALLBACK = {
    NOT_STARTED: 0,
    INTRODUCED: 1,
    UNDERSTANDING: 2,
    GUIDED_PRACTICE: 3,
    NEEDS_REVIEW: 2,
    INDEPENDENT: 4,
    STABLE: 5,
}

STABLE_MIN_PASSES = 2
STABLE_MIN_INTERVAL = timedelta(hours=24)


def now() -> datetime:
    return datetime.now(timezone.utc)


def safe_state(value: str | None) -> str:
    return value if value in STATES else NOT_STARTED


def label(value: str | None) -> str:
    return LABELS.get(safe_state(value), LABELS[NOT_STARTED])


def level_label(level: int | None) -> str:
    return LEVEL_LABELS.get(int(level or 0), LEVEL_LABELS[0])


def effective_level(point: KnowledgePoint) -> int:
    """读取长期等级；旧行 mastery_level=0 时按 mastery_state 推导下限，不回写。"""
    stored = int(point.mastery_level or 0)
    if stored:
        return stored
    return _LEVEL_FALLBACK.get(safe_state(point.mastery_state), 0)


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return now()
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _completed_stages(progress: TeachingProgress) -> set[str]:
    try:
        return set(json.loads(progress.completed_stages or "[]"))
    except (TypeError, ValueError):
        return set()


def consolidated(progress: TeachingProgress) -> bool:
    """巩固条件：v2 完成 CONSOLIDATE；v1 以进入 NEXT 作为旧流程的巩固完成。"""
    completed = _completed_stages(progress)
    family = teaching_stages.family_of(progress.current_stage)
    if family == teaching_stages.FAMILY_CONSOLIDATE:
        return progress.current_stage in completed and progress.stage_status == "COMPLETED"
    if family == teaching_stages.FAMILY_NEXT:
        return True
    return "CONSOLIDATE" in completed


def _independent_passes(
    db: Session,
    point_id: int,
    current: dict | None = None,
) -> bool:
    """至少两次跨轮/跨会话独立通过，且最早与最晚一次间隔 ≥ 24 小时。"""
    rows = db.scalars(
        select(MasteryHistory).where(
            MasteryHistory.knowledge_point_id == point_id,
            MasteryHistory.evidence_type == "VERIFY_INDEPENDENT",
            MasteryHistory.hint_count == 0,
        )
    ).all()
    passes: dict[tuple[int | None, int], datetime] = {}
    for row in rows:
        if row.verdict and row.verdict != "PASSED":
            continue
        key = (row.session_id, int(row.round_number or 0))
        created = _aware(row.created_at)
        if key not in passes or created < passes[key]:
            passes[key] = created
    if current:
        key = (current.get("sessionId"), int(current.get("roundNumber") or 0))
        created = _aware(current.get("createdAt"))
        if key not in passes or created < passes[key]:
            passes[key] = created
    if len(passes) < STABLE_MIN_PASSES:
        return False
    dates = sorted(passes.values())
    return dates[-1] - dates[0] >= STABLE_MIN_INTERVAL


def _stage_level(stage: str, verdict: str | None, progress: TeachingProgress, current: int) -> int:
    family = teaching_stages.family_of(stage)
    if family in (teaching_stages.FAMILY_LESSON, teaching_stages.FAMILY_CONSOLIDATE):
        return max(current, 1)
    if family == teaching_stages.FAMILY_CHECK and verdict == "CORRECT":
        return max(current, 2)
    if family == teaching_stages.FAMILY_PRACTICE and verdict == "CORRECT":
        return max(current, 3)
    if (
        family == teaching_stages.FAMILY_VERIFY
        and verdict == "PASSED"
        and not progress.verify_hint_count
    ):
        return max(current, 4)
    return current


def state_from_progress(progress: TeachingProgress) -> str:
    """按当前阶段与验证结果推导本轮状态；没有证据时保持 NOT_STARTED。"""
    stage = teaching_stages.state_stage_key(progress.current_stage)
    if stage == "NEXT":
        if progress.verification_result == "PASSED":
            return INDEPENDENT if not progress.verify_hint_count else GUIDED_PRACTICE
        return NEEDS_REVIEW if progress.verification_result in ("FAILED", "NEEDS_REVIEW") else INTRODUCED
    if progress.verification_result in ("FAILED", "NEEDS_REVIEW") and stage in ("PAIR", "VERIFY"):
        return NEEDS_REVIEW
    if stage in ("TEACH", "DEMO"):
        return INTRODUCED if safe_state(progress.mastery_state) != NEEDS_REVIEW else NEEDS_REVIEW
    if stage == "CHECK":
        return UNDERSTANDING
    if stage == "PAIR":
        return GUIDED_PRACTICE
    if stage == "VERIFY":
        return UNDERSTANDING if not progress.verify_hint_count else GUIDED_PRACTICE
    return safe_state(progress.mastery_state)


def state_for_outcome(progress: TeachingProgress, stage: str, verdict: str | None) -> str:
    """结合刚发生的评价结果推导本轮状态。"""
    stage = teaching_stages.evaluation_stage_key(stage)
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


def _resolve_course(db: Session, point: KnowledgePoint, course: Course | None) -> Course | None:
    if course is not None:
        return course
    chapter = db.get(Chapter, point.chapter_id)
    return db.get(Course, chapter.course_id) if chapter else None


def _record(
    db: Session,
    *,
    point: KnowledgePoint,
    progress: TeachingProgress,
    course: Course | None,
    previous_state: str,
    target: str,
    previous_level: int,
    level: int,
    evidence_type: str,
    stage: str,
    verdict: str | None,
    activity_type: str | None,
    reason: str,
    payload: dict,
) -> None:
    resolved = _resolve_course(db, point, course)
    course_id = resolved.id if resolved is not None else point.chapter.course_id
    if resolved is not None:
        resolved.last_studied_at = now()
    db.add(
        MasteryHistory(
            course_id=course_id,
            knowledge_point_id=point.id,
            session_id=progress.session_id,
            activity_id=payload.get("activityId"),
            from_state=previous_state,
            to_state=target,
            evidence_type=evidence_type,
            stage=stage,
            activity_type=activity_type,
            verdict=verdict,
            hint_count=progress.verify_hint_count if teaching_stages.is_verify(stage) else progress.hint_count,
            round_number=progress.round_number,
            pipeline_version=getattr(progress, "pipeline_version", 1) or 1,
            reason=reason[:2000],
            evidence=json.dumps({**payload, "fromLevel": previous_level, "level": level}, ensure_ascii=False),
        )
    )
    db.add(
        LearningEvent(
            activity_id=payload.get("activityId"),
            course_id=course_id,
            knowledge_point_id=point.id,
            session_id=progress.session_id,
            event_type="MASTERY_CHANGED",
            detail=(
                f"{previous_state} → {target}"
                f"（等级 {previous_level} → {level}）：{reason}"
            )[:4000],
        )
    )


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
    """写入本次评价对应的状态与长期等级，返回 (当前展示状态, 变化前状态)。"""
    stage = stage or progress.current_stage
    stage_key = teaching_stages.evaluation_stage_key(stage)
    previous = safe_state(point.mastery_state)
    previous_level = effective_level(point)
    target_round = state_for_outcome(progress, stage, verdict)
    if previous in (INDEPENDENT, STABLE) and target_round in (NOT_STARTED, INTRODUCED, UNDERSTANDING):
        target_round = previous

    current_pass = None
    if stage_key == "VERIFY" and verdict == "PASSED" and not progress.verify_hint_count:
        current_pass = {
            "sessionId": progress.session_id,
            "roundNumber": progress.round_number,
            "createdAt": now(),
        }

    level = _stage_level(stage, verdict, progress, previous_level)
    if (
        level >= 4
        and consolidated(progress)
        and _independent_passes(db, point.id, current_pass)
    ):
        level = 5
    level = max(level, previous_level)

    target = STABLE if level >= 5 and target_round != NEEDS_REVIEW else target_round
    if previous == STABLE and target_round != NEEDS_REVIEW:
        target = STABLE

    if stage_key == "VERIFY":
        evidence_type = (
            "VERIFY_INDEPENDENT"
            if verdict == "PASSED" and not progress.verify_hint_count
            else "VERIFY_EVIDENCE"
        )
    elif level != previous_level:
        evidence_type = "LEVEL_CHANGED"
    else:
        evidence_type = "STATE_CHANGE"

    if target == previous and level == previous_level and stage_key != "VERIFY":
        return previous, None

    point.mastery_state = target
    point.mastery_level = level
    point.mastery_updated_at = now()

    if target == NEEDS_REVIEW and point.learning_status != "completed":
        point.learning_status = "review"
        point.last_studied_at = now()
    elif target in (INTRODUCED, UNDERSTANDING, GUIDED_PRACTICE) and point.learning_status == "not_started":
        point.learning_status = "in_progress"
        point.last_studied_at = now()

    payload = {
        "stage": stage,
        "action": action,
        "verdict": verdict,
        "checkAttempts": progress.check_attempts,
        "pairAttempts": progress.pair_attempts,
        "verifyAttempts": progress.verify_attempts,
        "hintCount": progress.hint_count,
        "verifyHintCount": progress.verify_hint_count,
        **(evidence or {}),
    }
    activity_type = (evidence or {}).get("activityType")
    _record(
        db,
        point=point,
        progress=progress,
        course=course,
        previous_state=previous,
        target=target,
        previous_level=previous_level,
        level=level,
        evidence_type=evidence_type,
        stage=stage,
        verdict=verdict,
        activity_type=activity_type,
        reason=reason,
        payload=payload,
    )
    return target, previous


def sync_level(
    db: Session,
    *,
    point: KnowledgePoint,
    progress: TeachingProgress,
    course: Course | None = None,
    reason: str = "",
) -> int:
    """在讲解/巩固阶段完成时同步长期等级，不依赖 AI 评价。

    - TEACH/UNDERSTAND/DEMONSTRATE 完成 → 至少 1 级；
    - CONSOLIDATE 完成且已有两次跨轮独立通过 → 5 级；
    - 等级只升不降，失败由 NEEDS_REVIEW 表达。
    """
    previous_level = effective_level(point)
    previous_state = safe_state(point.mastery_state)
    level = _stage_level(progress.current_stage, None, progress, previous_level)
    if level >= 4 and consolidated(progress) and _independent_passes(db, point.id):
        level = 5
    level = max(level, previous_level)

    round_state = state_from_progress(progress)
    target = STABLE if level >= 5 and round_state != NEEDS_REVIEW else round_state
    if target == NOT_STARTED and previous_state != NOT_STARTED:
        target = previous_state
    if level >= 5 and previous_state == STABLE and round_state != NEEDS_REVIEW:
        target = STABLE

    if target == previous_state and level == previous_level:
        return level

    point.mastery_level = level
    point.mastery_state = target
    point.mastery_updated_at = now()
    _record(
        db,
        point=point,
        progress=progress,
        course=course,
        previous_state=previous_state,
        target=target,
        previous_level=previous_level,
        level=level,
        evidence_type="LEVEL_SYNC",
        stage=progress.current_stage,
        verdict=None,
        activity_type=None,
        reason=reason or "阶段完成，同步长期等级",
        payload={"action": "LEVEL_SYNC"},
    )
    return level
