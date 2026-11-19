"""P1.6-B：教学任务与评价双写活动实例，旧读取路径保持不变。"""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from app.db.models import TeachingActivityInstance
from app.schemas.teaching import TeachingAction, TeachingJudgment, TeachingTask
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


def _walk_to_check(db, machine, session_id):
    operation = _begin(machine, session_id, "START")
    machine.finish(operation.id, "这是老师对知识点的讲解。")
    operation = _begin(machine, session_id, "CONTINUE")
    machine.finish(operation.id, "这是老师给出的完整示例。")
    operation = _begin(machine, session_id, "CONTINUE")
    task = TeachingTask(
        instruction="请先读题再回答。",
        question="循环变量为什么从 0 开始？",
        rubric="能说明索引从 0 开始的原因",
        hint="想想第一个元素的位置",
        summary="",
    )
    view = machine.finish(operation.id, f"{task.instruction}\n\n{task.question}", task)
    return view, task


def test_task_generation_dual_writes_activity_instance(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id

    view, task = _walk_to_check(db, machine, session_id)
    assert view["currentStage"] == "CHECK"
    assert view["currentQuestion"] == task.question
    assert view["currentActivity"]["activityType"] == "SHORT_ANSWER"
    assert view["currentActivity"]["definition"]["interaction"]["prompt"] == task.question

    db.expire_all()
    instance = db.scalars(
        select(TeachingActivityInstance).where(TeachingActivityInstance.session_id == session_id)
    ).one()
    assert instance.activity_type == "SHORT_ANSWER"
    assert instance.stage == "CHECK"
    assert instance.status == "ACTIVE"
    assert instance.prompt_message_id is not None
    definition = json.loads(instance.definition_json)
    assert definition["interaction"]["prompt"] == task.question
    assert definition["evaluation"]["evidenceRule"] == "QUOTE"


def test_evaluation_updates_instance_without_changing_old_flow(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    _walk_to_check(db, machine, session_id)

    answer = "因为索引表示相对第一个元素的偏移，第一个元素偏移为 0。"
    operation = _begin(machine, session_id, "ANSWER", answer)
    judgment = TeachingJudgment(
        evaluation="CORRECT",
        reason="回答说明了偏移含义",
        misconceptions=[],
        suggested_action="CONTINUE",
        feedback="回答正确，索引表示相对偏移。",
        evidence_quote="索引表示相对第一个元素的偏移",
        summary="",
    )
    view = machine.finish(operation.id, judgment.feedback, judgment)

    # 旧流程仍然按 CHECK 答对进入 PAIR。
    assert view["currentStage"] == "PAIR"
    db.expire_all()
    instance = db.scalars(
        select(TeachingActivityInstance).where(TeachingActivityInstance.session_id == session_id)
    ).one()
    assert instance.status == "COMPLETED"
    assert instance.answer_message_id is not None
    result = json.loads(instance.result_json)
    assert result["evaluation"] == "CORRECT"
    assert "索引" in instance.student_input


def test_teaching_api_exposes_current_activity_for_renderer(client, db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    _walk_to_check(db, machine, session_id)

    response = client.get(f"/api/v1/classroom/sessions/{session_id}/teaching")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["currentActivity"]["activityType"] == "SHORT_ANSWER"
    assert data["currentActivity"]["definition"]["interaction"]["inputKind"] == "SHORT_TEXT"
    assert data["currentActivity"]["definition"]["interaction"]["prompt"]
