"""P1.6-F：长期掌握等级与错题活动类型。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update

from app.db.models import KnowledgePoint, MasteryHistory, MistakeRecord
from app.schemas.teaching import TeachingAction, TeachingJudgment, TeachingTask
from app.services import archive
from app.services.teaching_state import TeachingStateMachine


def _begin(machine, session_id, action, content=""):
    view = machine.view(machine.ensure(session_id))
    payload = TeachingAction(
        request_id=uuid4(),
        expected_revision=view["revision"],
        action=action,
        content=content,
    )
    return machine.begin(session_id, payload, "test-model")


def _lesson(machine, session_id, action="START"):
    operation = _begin(machine, session_id, action)
    return machine.finish(operation.id, "讲解或示例内容。")


def _task(machine, session_id, action="START"):
    operation = _begin(machine, session_id, action)
    task = TeachingTask(
        instruction="请回答。",
        question=f"这一步的关键是什么？（{uuid4().hex[:6]}）",
        rubric="能说明关键步骤",
        hint="回看刚才的示例",
        summary="",
    )
    return machine.finish(operation.id, f"{task.instruction}\n\n{task.question}", task)


def _answer(machine, session_id, text, verdict):
    operation = _begin(machine, session_id, "ANSWER", text)
    judgment = TeachingJudgment(
        evaluation=verdict,
        reason="依据回答判断",
        misconceptions=[],
        suggested_action="CONTINUE",
        feedback="老师反馈。",
        evidence_quote=text[:20],
        summary="本节总结。",
    )
    return machine.finish(operation.id, judgment.feedback, judgment)


def _walk_v1_to_verify(machine, session_id, first_action="START"):
    _lesson(machine, session_id, first_action)
    if first_action == "START":
        _lesson(machine, session_id, "CONTINUE")
    _task(machine, session_id, "CONTINUE")
    _answer(machine, session_id, "因为索引表示相对第一个元素的偏移。", "CORRECT")
    _task(machine, session_id)
    _answer(machine, session_id, "第一步：先初始化累加器。", "CORRECT")
    _task(machine, session_id)
    _answer(machine, session_id, "第二步：循环结束后输出结果。", "CORRECT")
    _task(machine, session_id)
    return _answer(machine, session_id, "独立完成：定义变量，循环累加，输出结果。", "PASSED")


def test_one_independent_pass_is_level_four_not_stable(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    _lesson(machine, session_id)
    point = db.get(KnowledgePoint, seeded["point"].id)
    assert point.mastery_level == 1

    view = _walk_v1_to_verify(machine, session_id, first_action="CONTINUE")
    assert view["currentStage"] == "NEXT"
    assert view["masteryState"] == "INDEPENDENT"
    db.refresh(point)
    assert point.mastery_level == 4
    assert point.mastery_state == "INDEPENDENT"


def test_two_passes_across_24h_with_consolidation_become_stable(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    _walk_v1_to_verify(machine, session_id)

    db.execute(
        update(MasteryHistory)
        .where(
            MasteryHistory.knowledge_point_id == seeded["point"].id,
            MasteryHistory.evidence_type == "VERIFY_INDEPENDENT",
        )
        .values(created_at=datetime.now(timezone.utc) - timedelta(hours=25))
    )
    db.commit()

    view = machine.view(machine.ensure(session_id))
    machine.control(
        session_id,
        TeachingAction(
            request_id=uuid4(),
            expected_revision=view["revision"],
            action="RESTART",
        ),
    )
    view = _walk_v1_to_verify(machine, session_id)
    assert view["currentStage"] == "NEXT"
    assert view["masteryState"] == "STABLE"

    point = db.get(KnowledgePoint, seeded["point"].id)
    assert point.mastery_level == 5
    assert point.mastery_state == "STABLE"

    evidence = db.scalars(
        select(MasteryHistory).where(
            MasteryHistory.knowledge_point_id == point.id,
            MasteryHistory.evidence_type == "VERIFY_INDEPENDENT",
        )
    ).all()
    assert len(evidence) >= 2
    assert len({row.round_number for row in evidence}) >= 2


def test_two_passes_within_24h_stay_level_four(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    _walk_v1_to_verify(machine, session_id)

    view = machine.view(machine.ensure(session_id))
    machine.control(
        session_id,
        TeachingAction(
            request_id=uuid4(),
            expected_revision=view["revision"],
            action="RESTART",
        ),
    )
    view = _walk_v1_to_verify(machine, session_id)
    assert view["currentStage"] == "NEXT"
    assert view["masteryState"] == "INDEPENDENT"

    point = db.get(KnowledgePoint, seeded["point"].id)
    assert point.mastery_level == 4


def test_mistake_records_activity_type(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    _lesson(machine, session_id)
    _lesson(machine, session_id, "CONTINUE")
    _task(machine, session_id, "CONTINUE")
    _answer(machine, session_id, "我认为循环一次都不执行。", "INCORRECT")

    db.expire_all()
    record = db.scalars(
        select(MistakeRecord).where(MistakeRecord.knowledge_point_id == seeded["point"].id)
    ).first()
    assert record is not None
    assert record.error_type == "concept"
    assert record.activity_type == "SHORT_ANSWER"


def test_mastery_overview_exposes_levels(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    _walk_v1_to_verify(machine, session_id)

    data = archive.mastery_overview(db)
    entry = next(
        point
        for course in data["courses"]
        for chapter in course["chapters"]
        for point in chapter["points"]
        if point["pointId"] == seeded["point"].id
    )
    assert entry["masteryLevel"] == 4
    assert entry["masteryLevelLabel"] == "本轮独立"
    assert entry["stableMastery"] is False
    assert len(data["levels"]) == 6
