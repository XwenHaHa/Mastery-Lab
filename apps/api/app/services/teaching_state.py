from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.response import ConflictError, ValidationError
from ..db.models import ChatMessage, LearningSession, TeachingEvaluation, TeachingEvent, TeachingOperation, TeachingProgress
from ..schemas.teaching import TeachingAction, TeachingJudgment, TeachingTask
from . import classroom_service, stream_registry

STAGES = ("TEACH", "DEMO", "CHECK", "PAIR", "VERIFY", "NEXT")
GOALS = {
    "TEACH": "理解这个知识点是什么、为什么需要它。",
    "DEMO": "看完整的小案例，理解关键语句和预期输出。",
    "CHECK": "用一个回答说明你对当前知识点的理解。",
    "PAIR": "在老师引导下，逐步完成两个小步骤。",
    "VERIFY": "独立提交解释或代码片段，验证当前理解。",
    "NEXT": "回顾本节学习结果，自主决定是否学习下一节。",
}


def now():
    return datetime.now(timezone.utc)


def iso(value):
    return classroom_service._utc(value).isoformat() if value else None


class TeachingStateMachine:
    def __init__(self, db: Session):
        self.db = db

    def ensure(self, session_id: int) -> TeachingProgress:
        row = classroom_service.get_session_row(self.db, session_id)
        _course, _chapter, point = classroom_service.load_entities_for_row(self.db, row)
        progress = self.db.get(TeachingProgress, session_id)
        if progress is None:
            progress = TeachingProgress(session_id=session_id, legacy_completion=point.learning_status == "completed" and point.completion_source != "verified")
            try:
                with self.db.begin_nested():
                    self.db.add(progress)
                    self.db.flush()
                    self.event(progress, "INITIALIZED", "旧对话已保留；教学验证从本轮开始。" if progress.legacy_completion else "开始本知识点教学。")
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                progress = self.db.get(TeachingProgress, session_id)
        return progress

    def event(self, progress, event_type, detail="", operation=None, from_stage=None):
        self.db.add(TeachingEvent(session_id=progress.session_id, operation_id=operation.id if operation else None,
            round_number=progress.round_number, from_stage=from_stage or progress.current_stage,
            to_stage=progress.current_stage, event_type=event_type, detail=detail[:6000]))

    def allowed(self, progress):
        if progress.paused:
            return ["RESUME"]
        if progress.stage_status == "ACTIVE":
            return ["PAUSE"]
        actions = ["ASK", "PAUSE"]
        if progress.current_stage == "NEXT":
            return actions + ["NEXT", "RESTART"]
        actions += ["EXPLAIN_AGAIN", "CHANGE_EXAMPLE", "DONT_UNDERSTAND", "GIVE_HINT"]
        if progress.stage_status in ("PENDING", "BLOCKED"):
            actions += ["START", "REGENERATE"]
        elif progress.current_stage in ("TEACH", "DEMO") and progress.stage_status == "COMPLETED":
            actions += ["CONTINUE", "REGENERATE"]
            if progress.current_stage == "DEMO":
                actions += ["TRY_MYSELF"]
        elif progress.current_question:
            actions += ["ANSWER", "REGENERATE", "TRY_MYSELF"]
        return actions

    def view(self, progress):
        if progress.paused:
            next_step = "学习已暂停；继续后恢复当前阶段和问题。"
        elif progress.stage_status == "ACTIVE":
            next_step = "老师正在准备本阶段内容，请稍候。"
        elif progress.current_stage == "NEXT":
            next_step = "本节验证通过，可以继续下一知识点或回顾本节。"
        elif progress.current_question:
            next_step = "提交当前问题的回答；也可以先提问或请求提示。"
        elif progress.stage_status == "COMPLETED":
            next_step = "阅读完成后点击继续下一步。"
        else:
            next_step = "开始或重试当前阶段，未完成的生成不会推进学习。"
        return {
            "sessionId": progress.session_id, "revision": progress.revision, "currentStage": progress.current_stage,
            "stageStatus": progress.stage_status, "paused": progress.paused, "goal": GOALS[progress.current_stage],
            "nextStep": next_step, "allowedActions": self.allowed(progress), "completedStages": json.loads(progress.completed_stages),
            "currentQuestion": progress.current_question or None, "pairStep": progress.pair_step, "pairTotalSteps": 2,
            "checkAttempts": progress.check_attempts, "pairAttempts": progress.pair_attempts, "verifyAttempts": progress.verify_attempts,
            "hintCount": progress.hint_count, "verifyHintCount": progress.verify_hint_count, "backtrackCount": progress.backtrack_count,
            "masteryState": progress.mastery_state, "verificationResult": progress.verification_result,
            "legacyCompletion": progress.legacy_completion, "summary": progress.summary, "errorMessage": progress.error_message,
            "completedAt": iso(progress.completed_at), "lastActivityAt": iso(progress.last_activity_at),
        }

    def lookup(self, session_id, payload):
        operation = self.db.scalar(select(TeachingOperation).where(TeachingOperation.session_id == session_id, TeachingOperation.request_id == str(payload.request_id)))
        if operation:
            if operation.request_hash != self.fingerprint(payload):
                raise ConflictError("同一个请求标识不能用于不同操作")
            if operation.status == "active":
                raise ConflictError("这个操作仍在处理中，请等待或暂停")
        return operation

    @staticmethod
    def fingerprint(payload):
        return hashlib.sha256(payload.model_dump_json().encode()).hexdigest()

    def claim(self, progress, revision):
        result = self.db.execute(update(TeachingProgress).where(TeachingProgress.session_id == progress.session_id,
            TeachingProgress.revision == revision).values(revision=revision + 1).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            self.db.rollback()
            raise ConflictError("学习进度已变化，请同步当前阶段后重试")
        self.db.refresh(progress)
        progress.last_activity_at = now()

    def move(self, progress, target, operation, reason):
        previous = progress.current_stage
        if target == previous:
            return
        if STAGES.index(target) < STAGES.index(previous):
            progress.backtrack_count += 1
            progress.completed_stages = json.dumps([stage for stage in json.loads(progress.completed_stages) if STAGES.index(stage) < STAGES.index(target)])
            progress.mastery_state = "UNDERSTANDING" if target == "PAIR" else "INTRODUCED"
            progress.completed_at = None
        progress.current_stage = target
        progress.stage_status = "PENDING"
        progress.current_question = ""
        progress.rubric = ""
        progress.hint = ""
        progress.question_message_id = None
        progress.stage_started_at = now()
        if target == "PAIR":
            progress.pair_step = 1
        self.event(progress, "STAGE_CHANGED", reason, operation, from_stage=previous)

    def complete_stage(self, progress, operation):
        stages = json.loads(progress.completed_stages)
        if progress.current_stage not in stages:
            stages.append(progress.current_stage)
        progress.completed_stages = json.dumps(stages)
        self.event(progress, "STAGE_COMPLETED", operation.action, operation)

    def begin(self, session_id: int, payload: TeachingAction, model_name: str):
        progress = self.ensure(session_id)
        if payload.action not in self.allowed(progress):
            raise ConflictError("当前阶段不允许此操作，请先完成当前教学步骤")
        if payload.action in ("ANSWER", "ASK") and not payload.content:
            raise ValidationError("请先填写回答或问题")
        if payload.action in ("PAUSE", "RESUME", "NEXT", "RESTART"):
            raise ValidationError("该操作需要使用教学控制接口")
        self.claim(progress, payload.expected_revision)
        operation = TeachingOperation(session_id=session_id, request_id=str(payload.request_id), request_hash=self.fingerprint(payload),
            action=payload.action, stage=progress.current_stage, kind="lesson", revision=progress.revision, previous_status=progress.stage_status)
        self.db.add(operation)
        self.db.flush()
        action = payload.action
        if action in ("CONTINUE", "TRY_MYSELF") and progress.stage_status == "COMPLETED":
            target = {"TEACH": "DEMO", "DEMO": "CHECK"}.get(progress.current_stage)
            if not target:
                raise ConflictError("需要先完成当前验证")
            self.move(progress, target, operation, "用户确认继续")
        elif action in ("EXPLAIN_AGAIN", "DONT_UNDERSTAND") and progress.current_stage not in ("TEACH", "DEMO"):
            if progress.current_stage == "VERIFY":
                progress.verify_hint_count += 1
            self.move(progress, "TEACH", operation, "用户要求重新讲解")
        operation.stage = progress.current_stage
        operation.previous_status = progress.stage_status
        if action == "ANSWER":
            operation.kind = "evaluation"
            operation.question_message_id = progress.question_message_id
            counter = {"CHECK": "check_attempts", "PAIR": "pair_attempts", "VERIFY": "verify_attempts"}[progress.current_stage]
            setattr(progress, counter, getattr(progress, counter) + 1)
        elif action in ("ASK", "GIVE_HINT") or (action == "TRY_MYSELF" and progress.current_question):
            operation.kind = "explanation"
        elif progress.current_stage in ("CHECK", "PAIR", "VERIFY"):
            operation.kind = "task"
        if action in ("GIVE_HINT", "EXPLAIN_AGAIN", "DONT_UNDERSTAND", "ASK", "CHANGE_EXAMPLE", "REGENERATE"):
            progress.hint_count += 1
            if progress.current_stage == "VERIFY":
                progress.verify_hint_count += 1
        row = classroom_service.get_session_row(self.db, session_id)
        _course, _chapter, point = classroom_service.load_entities_for_row(self.db, row)
        if point.learning_status == "not_started":
            point.learning_status = "in_progress"
        if payload.content:
            operation.user_message_id = classroom_service.add_user_message(self.db, row, payload.content).id
        operation.assistant_message_id = classroom_service.create_assistant_message(self.db, row, model_name).id
        progress.stage_status = "ACTIVE"
        progress.error_message = ""
        self.event(progress, "ACTION_STARTED", action, operation)
        self.db.commit()
        return operation

    def finish(self, operation_id, text, structured=None):
        operation = self.db.get(TeachingOperation, operation_id)
        progress = self.db.get(TeachingProgress, operation.session_id)
        if operation.status != "active" or progress.revision != operation.revision or progress.paused:
            raise ConflictError("本次生成已失效，不会推进教学阶段")
        self.claim(progress, operation.revision)
        assistant = self.db.get(ChatMessage, operation.assistant_message_id)
        assistant.content = text
        assistant.status = "completed"
        if operation.kind == "lesson":
            progress.stage_status = "COMPLETED"
            self.complete_stage(progress, operation)
        elif operation.kind == "task":
            task: TeachingTask = structured
            progress.current_question = task.question
            progress.rubric = task.rubric
            progress.hint = task.hint
            progress.question_message_id = assistant.id
            progress.stage_status = "WAITING_USER"
        elif operation.kind == "explanation":
            progress.stage_status = operation.previous_status
        elif operation.kind == "evaluation":
            self.apply_evaluation(progress, operation, structured)
        operation.status = "completed"
        operation.ended_at = now()
        self.event(progress, "ACTION_COMPLETED", operation.action, operation)
        self.db.commit()
        return self.view(progress)

    def apply_evaluation(self, progress, operation, result: TeachingJudgment):
        user = self.db.get(ChatMessage, operation.user_message_id)
        allowed = {"PASSED", "NEEDS_REVIEW", "FAILED", "UNCLEAR"} if operation.stage == "VERIFY" else {"CORRECT", "PARTIAL", "INCORRECT", "UNCLEAR"}
        if result.evaluation not in allowed:
            raise ValidationError("模型评价与当前阶段不匹配，请重新提交")
        if result.evaluation in ("CORRECT", "PASSED"):
            generic = user.content.strip().rstrip("。.!！").lower() in ("我懂了", "懂了", "知道了", "明白了", "ok", "yes", "好的", "会了")
            if generic or not result.evidence_quote.strip() or result.evidence_quote not in user.content:
                result = result.model_copy(update={"evaluation": "UNCLEAR", "feedback": "仅确认理解不足以通过。请针对当前问题给出具体解释或代码片段。", "reason": "缺少可引用的实际回答证据", "suggested_action": "ASK_CLARIFICATION"})
                self.db.get(ChatMessage, operation.assistant_message_id).content = result.feedback
        self.db.add(TeachingEvaluation(operation_id=operation.id, session_id=operation.session_id, stage=operation.stage,
            verdict=result.evaluation, payload=result.model_dump_json(), hint_count=progress.verify_hint_count if operation.stage == "VERIFY" else progress.hint_count))
        operation.result_json = result.model_dump_json()
        progress.stage_status = "WAITING_USER"
        if result.evaluation == "UNCLEAR":
            return
        if operation.stage == "CHECK":
            if result.evaluation == "CORRECT":
                self.complete_stage(progress, operation)
                progress.mastery_state = "UNDERSTANDING"
                self.move(progress, "PAIR", operation, result.reason)
            elif result.evaluation == "INCORRECT":
                self.move(progress, "TEACH", operation, result.reason)
            elif result.evaluation == "PARTIAL":
                progress.current_question = ""
                progress.rubric = ""
                progress.hint = ""
                progress.question_message_id = None
                progress.stage_status = "PENDING"
                self.event(progress, "TARGETED_RECHECK", result.reason, operation)
        elif operation.stage == "PAIR" and result.evaluation == "CORRECT":
            progress.mastery_state = "GUIDED_PRACTICE"
            if progress.pair_step < 2:
                progress.pair_step += 1
                progress.current_question = ""
                progress.question_message_id = None
                progress.stage_status = "PENDING"
            else:
                self.complete_stage(progress, operation)
                self.move(progress, "VERIFY", operation, result.reason)
        elif operation.stage == "VERIFY":
            progress.verification_result = result.evaluation
            if result.evaluation == "PASSED":
                self.complete_stage(progress, operation)
                self.move(progress, "NEXT", operation, result.reason)
                progress.stage_status = "COMPLETED"
                progress.completed_at = now()
                progress.mastery_state = "GUIDED_PRACTICE" if progress.verify_hint_count else "INDEPENDENT"
                progress.summary = result.summary or result.feedback
                row = classroom_service.get_session_row(self.db, progress.session_id)
                course, _chapter, point = classroom_service.load_entities_for_row(self.db, row)
                point.learning_status = "completed"
                point.completion_source = "verified"
                point.last_studied_at = now()
                course.last_studied_at = now()
            else:
                self.move(progress, "PAIR", operation, result.reason)

    def fail(self, operation_id, error, content="", interrupted=False):
        self.db.rollback()
        operation = self.db.get(TeachingOperation, operation_id)
        if not operation or operation.status != "active":
            return
        progress = self.db.get(TeachingProgress, operation.session_id)
        assistant = self.db.get(ChatMessage, operation.assistant_message_id)
        if assistant:
            assistant.content = content
            assistant.status = "interrupted" if interrupted else "failed"
            assistant.error_message = error[:500]
        operation.status = "interrupted" if interrupted else "failed"
        operation.ended_at = now()
        if progress:
            progress.revision += 1
            progress.stage_status = "WAITING_USER" if progress.current_question else "BLOCKED"
            if operation.kind == "explanation":
                progress.stage_status = operation.previous_status
            progress.error_message = error[:500]
            progress.last_activity_at = now()
            self.event(progress, "ACTION_INTERRUPTED" if interrupted else "ACTION_FAILED", error, operation)
        self.db.commit()

    def control(self, session_id, payload):
        previous = self.lookup(session_id, payload)
        if previous:
            return json.loads(previous.result_json)
        progress = self.ensure(session_id)
        if payload.action not in self.allowed(progress):
            raise ConflictError("当前阶段不能执行此操作")
        if payload.action not in ("PAUSE", "RESUME", "NEXT", "RESTART"):
            raise ValidationError("此操作需要通过教学流执行")
        self.claim(progress, payload.expected_revision)
        operation = TeachingOperation(session_id=session_id, request_id=str(payload.request_id), request_hash=self.fingerprint(payload),
            action=payload.action, stage=progress.current_stage, kind="control", status="completed", revision=progress.revision, previous_status=progress.stage_status, ended_at=now())
        self.db.add(operation)
        self.db.flush()
        next_id = None
        course_complete = False
        if payload.action == "PAUSE":
            progress.paused = True
        elif payload.action == "RESUME":
            if stream_registry.is_active(session_id):
                raise ConflictError("正在保存暂停前的回答，请稍后继续")
            progress.paused = False
        elif payload.action == "NEXT":
            if progress.current_stage != "NEXT" or progress.verification_result != "PASSED":
                raise ConflictError("请先通过当前知识点的学习验证")
            row = classroom_service.get_session_row(self.db, session_id)
            course, _chapter, point = classroom_service.load_entities_for_row(self.db, row)
            next_id = classroom_service._point_info(course, point).next_id
            course_complete = next_id is None
        elif payload.action == "RESTART":
            progress.round_number += 1
            self.move(progress, "TEACH", operation, "用户明确重新学习，保留原证据")
            progress.completed_stages = "[]"
            progress.completed_at = None
            progress.verification_result = None
            progress.summary = ""
            progress.verify_hint_count = 0
            progress.mastery_state = "INTRODUCED"
            row = classroom_service.get_session_row(self.db, session_id)
            _course, _chapter, point = classroom_service.load_entities_for_row(self.db, row)
            point.learning_status = "in_progress"
        self.event(progress, payload.action, "用户操作", operation)
        result = {"teaching": self.view(progress), "nextKnowledgePointId": next_id, "courseComplete": course_complete}
        operation.result_json = json.dumps(result, ensure_ascii=False)
        self.db.commit()
        return result

    def recover(self):
        operations = self.db.scalars(select(TeachingOperation).where(TeachingOperation.status == "active")).all()
        for operation in operations:
            message = self.db.get(ChatMessage, operation.assistant_message_id)
            self.fail(operation.id, "服务曾中断，本阶段未自动推进，请重试。", message.content if message else "", interrupted=True)
