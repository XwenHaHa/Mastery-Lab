"""P1.6-C：双轨状态机。v1 行为不变，v2 按阶段契约运行。"""

from __future__ import annotations

from uuid import uuid4

from app.schemas.teaching import TeachingAction, TeachingJudgment, TeachingTask
from app.services import teaching_pipeline, teaching_stages
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
    return machine.finish(operation.id, "老师的讲解内容。")


def _task(machine, session_id, action="START"):
    operation = _begin(machine, session_id, action)
    task = TeachingTask(
        instruction="请回答下面的问题。",
        question=f"这一步的关键是什么？（{uuid4().hex[:6]}）",
        rubric="能说明关键步骤",
        hint="回看刚才的示例",
        summary="",
    )
    return machine.finish(operation.id, f"{task.instruction}\n\n{task.question}", task), task


def _answer(machine, session_id, text, verdict):
    operation = _begin(machine, session_id, "ANSWER", text)
    judgment = TeachingJudgment(
        evaluation=verdict,
        reason="依据回答内容判断",
        misconceptions=[],
        suggested_action="CONTINUE",
        feedback="老师反馈。",
        evidence_quote=text[:20],
        summary="本节完成，关键点是分步理解。",
    )
    return machine.finish(operation.id, judgment.feedback, judgment)


def test_contracts_cover_both_pipelines():
    v1 = teaching_pipeline.TeachingPipeline(1)
    v2 = teaching_pipeline.TeachingPipeline(2)
    assert v1.next_of("TEACH") == "DEMO"
    assert v2.next_of("UNDERSTAND") == "TEACH"
    assert v2.next_of("VERIFY") == "CONSOLIDATE"
    assert v2.backstage_of("INTERACT") == "TEACH"
    assert v2.backstage_of("VERIFY") == "PRACTICE"
    assert v2.allowed_verdicts("VERIFY") == {"PASSED", "NEEDS_REVIEW", "FAILED", "UNCLEAR"}
    assert v2.allowed_verdicts("INTERACT") == {"CORRECT", "PARTIAL", "INCORRECT", "UNCLEAR"}


def test_v1_flow_is_unchanged(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    progress = machine.ensure(session_id)
    assert progress.pipeline_version == 1

    view = _lesson(machine, session_id)
    assert view["currentStage"] == "TEACH"
    view = _lesson(machine, session_id, "CONTINUE")
    assert view["currentStage"] == "DEMO"
    view, _ = _task(machine, session_id, "CONTINUE")
    assert view["currentStage"] == "CHECK"

    view = _answer(machine, session_id, "因为索引表示从第一个元素开始的偏移量。", "CORRECT")
    assert view["currentStage"] == "PAIR"

    view, _ = _task(machine, session_id)
    view = _answer(machine, session_id, "第一步：先初始化累加器。", "CORRECT")
    assert view["currentStage"] == "PAIR"
    assert view["pairStep"] == 2

    view, _ = _task(machine, session_id)
    view = _answer(machine, session_id, "第二步：循环结束后输出累加结果。", "CORRECT")
    assert view["currentStage"] == "VERIFY"

    view, _ = _task(machine, session_id)
    view = _answer(machine, session_id, "独立完成任务：先定义变量，再循环累加，最后输出。", "PASSED")
    assert view["currentStage"] == "NEXT"
    assert view["stageStatus"] == "COMPLETED"
    assert view["verificationResult"] == "PASSED"
    assert view["masteryState"] == "INDEPENDENT"
    assert seeded["point"].learning_status == "completed"
    assert seeded["point"].completion_source == "verified"


def test_v2_flow_uses_eight_stages(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    progress = machine.ensure(session_id)
    progress.pipeline_version = 2
    progress.current_stage = "UNDERSTAND"
    db.commit()

    view = machine.view(machine.ensure(session_id))
    assert view["pipelineVersion"] == 2
    assert view["currentStage"] == "UNDERSTAND"

    assert _lesson(machine, session_id)["currentStage"] == "UNDERSTAND"
    assert _lesson(machine, session_id, "CONTINUE")["currentStage"] == "TEACH"
    assert _lesson(machine, session_id, "CONTINUE")["currentStage"] == "DEMONSTRATE"
    view, _ = _task(machine, session_id, "CONTINUE")
    assert view["currentStage"] == "INTERACT"

    view = _answer(machine, session_id, "这个例子的关键是先判断条件再执行。", "CORRECT")
    assert view["currentStage"] == "PRACTICE"
    assert view["stageCounters"].get("INTERACT") == 1

    view, _ = _task(machine, session_id)
    view = _answer(machine, session_id, "练习第一步：先写出判断条件。", "CORRECT")
    assert view["currentStage"] == "PRACTICE"
    assert view["pairStep"] == 2

    view, _ = _task(machine, session_id)
    view = _answer(machine, session_id, "练习第二步：再补上执行分支。", "CORRECT")
    assert view["currentStage"] == "VERIFY"

    view, _ = _task(machine, session_id)
    view = _answer(machine, session_id, "独立完成：先判断，再执行，最后检查输出。", "PASSED")
    assert view["currentStage"] == "CONSOLIDATE"
    assert view["stageStatus"] == "PENDING"
    assert view["completedAt"] is not None
    assert seeded["point"].learning_status == "completed"
    assert seeded["point"].completion_source == "verified"

    view = _lesson(machine, session_id)
    assert view["currentStage"] == "CONSOLIDATE"
    assert view["stageStatus"] == "COMPLETED"
    view = _lesson(machine, session_id, "CONTINUE")
    assert view["currentStage"] == "NEXT"
    assert view["stageStatus"] == "COMPLETED"


def test_unknown_v2_stage_degrades_safely(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    progress = machine.ensure(session_id)
    progress.pipeline_version = 2
    progress.current_stage = "FUTURE_STAGE"
    progress.stage_status = "PENDING"
    db.commit()

    view = machine.view(progress)
    assert view["goal"]
    assert view["pipelineVersion"] == 2
    assert "START" in view["allowedActions"]
    assert teaching_stages.is_known("FUTURE_STAGE", 2) is False
