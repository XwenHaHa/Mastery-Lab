from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.response import ConflictError, ValidationError
from ..core.config import settings
from ..db.models import ChatMessage, LearningSession, TeachingEvaluation, TeachingEvent, TeachingOperation, TeachingProgress
from ..schemas.teaching import TeachingAction, TeachingJudgment, TeachingTask
from . import activities, breakpoints, classroom_service, learning_record, mastery, mistakes, stream_registry
from . import teaching_pipeline, teaching_stages

STAGES = teaching_stages.stage_keys(teaching_stages.PIPELINE_V1)
GOALS = {stage.key: stage.goal for stage in teaching_stages.stages_for(teaching_stages.PIPELINE_V1)}


def now():
    return datetime.now(timezone.utc)


def iso(value):
    return classroom_service._utc(value).isoformat() if value else None


class TeachingStateMachine:
    def __init__(self, db: Session):
        self.db = db

    # ---- P1.6-C：流程版本与通用计数 ----
    @staticmethod
    def pipeline(progress) -> teaching_pipeline.TeachingPipeline:
        return teaching_pipeline.TeachingPipeline(getattr(progress, "pipeline_version", 1))

    @staticmethod
    def _bump_stage_counter(progress, stage: str) -> None:
        counters = json.loads(progress.stage_counters or "{}")
        counters[stage] = int(counters.get(stage, 0)) + 1
        progress.stage_counters = json.dumps(counters)

    @staticmethod
    def _clear_question(progress) -> None:
        progress.current_question = ""
        progress.rubric = ""
        progress.hint = ""
        progress.question_message_id = None

    def ensure(self, session_id: int) -> TeachingProgress:
        row = classroom_service.get_session_row(self.db, session_id)
        _course, _chapter, point = classroom_service.load_entities_for_row(self.db, row)
        progress = self.db.get(TeachingProgress, session_id)
        if progress is None:
            version = teaching_stages.normalize_version(settings.teaching_pipeline_version)
            progress = TeachingProgress(
                session_id=session_id,
                legacy_completion=point.learning_status == "completed" and point.completion_source != "verified",
                pipeline_version=version,
                current_stage=teaching_stages.first_lesson_stage(version),
            )
            try:
                with self.db.begin_nested():
                    self.db.add(progress)
                    self.db.flush()
                    self.event(progress, "INITIALIZED", "旧对话已保留；教学验证从本轮开始。" if progress.legacy_completion else "开始本知识点教学。")
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                progress = self.db.get(TeachingProgress, session_id)
        try:
            breakpoints.sync_from_progress(self.db, session_id, progress)
            self.db.commit()
        except Exception:  # noqa: BLE001 - 断点只是辅助，不能阻断教学初始化
            self.db.rollback()
            progress = self.db.get(TeachingProgress, session_id)
        return progress

    def _sync_side_records(self, progress: TeachingProgress) -> None:
        """把阶段、计数同步到学习活动和断点（不单独提交）。"""
        learning_record.sync_from_progress(self.db, progress.session_id, progress)
        breakpoints.sync_from_progress(self.db, progress.session_id, progress)

    def event(self, progress, event_type, detail="", operation=None, from_stage=None):
        self.db.add(TeachingEvent(session_id=progress.session_id, operation_id=operation.id if operation else None,
            round_number=progress.round_number, from_stage=from_stage or progress.current_stage,
            to_stage=progress.current_stage, event_type=event_type, detail=detail[:6000]))

    def allowed(self, progress):
        version = teaching_stages.normalize_version(getattr(progress, "pipeline_version", 1))
        if version >= teaching_stages.PIPELINE_V2:
            return self.pipeline(progress).allowed_actions(progress)
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
        version = teaching_stages.normalize_version(getattr(progress, "pipeline_version", 1))
        pipeline = self.pipeline(progress)
        stage_counters = json.loads(progress.stage_counters or "{}")
        if version >= teaching_stages.PIPELINE_V2:
            check_attempts = int(stage_counters.get("INTERACT", 0))
            pair_attempts = int(stage_counters.get("PRACTICE", 0))
            verify_attempts = int(stage_counters.get("VERIFY", 0))
        else:
            check_attempts = progress.check_attempts
            pair_attempts = progress.pair_attempts
            verify_attempts = progress.verify_attempts
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
            "sessionId": progress.session_id, "revision": progress.revision,
            "pipelineVersion": version,
            "currentStage": progress.current_stage,
            "stageStatus": progress.stage_status, "paused": progress.paused,
            "goal": teaching_stages.goal_for(progress.current_stage, version),
            "nextStep": next_step, "allowedActions": self.allowed(progress), "completedStages": json.loads(progress.completed_stages),
            "currentQuestion": progress.current_question or None, "pairStep": progress.pair_step,
            "currentActivity": activities.current_activity_payload(self.db, progress),            "pairTotalSteps": 2 if version == teaching_stages.PIPELINE_V1 else pipeline.pair_steps(progress.current_stage),
            "checkAttempts": check_attempts, "pairAttempts": pair_attempts, "verifyAttempts": verify_attempts,
            "stageCounters": stage_counters,
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
        version = teaching_stages.normalize_version(getattr(progress, "pipeline_version", 1))
        if version >= teaching_stages.PIPELINE_V2:
            pipeline = self.pipeline(progress)
            if pipeline.index(target) < pipeline.index(previous):
                progress.backtrack_count += 1
                target_index = pipeline.index(target)
                progress.completed_stages = json.dumps([
                    stage for stage in json.loads(progress.completed_stages)
                    if pipeline.index(stage) < target_index
                ])
                progress.mastery_state = "UNDERSTANDING" if pipeline.is_task(target) and not pipeline.is_verify(target) else "INTRODUCED"
                progress.completed_at = None
        else:
            if STAGES.index(target) < STAGES.index(previous):
                progress.backtrack_count += 1
                progress.completed_stages = json.dumps([stage for stage in json.loads(progress.completed_stages) if STAGES.index(stage) < STAGES.index(target)])
                progress.mastery_state = "UNDERSTANDING" if target == "PAIR" else "INTRODUCED"
                progress.completed_at = None
        progress.current_stage = target
        progress.stage_status = "PENDING"
        self._clear_question(progress)
        progress.stage_started_at = now()
        if target in ("PAIR", "PRACTICE"):
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
        learning_record.ensure_activity(self.db, session_id)
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
        version = teaching_stages.normalize_version(getattr(progress, "pipeline_version", 1))
        pipeline = self.pipeline(progress)
        if action in ("CONTINUE", "TRY_MYSELF") and progress.stage_status == "COMPLETED":
            target = pipeline.next_of(progress.current_stage) if version >= teaching_stages.PIPELINE_V2 else {"TEACH": "DEMO", "DEMO": "CHECK"}.get(progress.current_stage)
            if not target:
                raise ConflictError("需要先完成当前验证")
            self.move(progress, target, operation, "用户确认继续")
        elif action in ("EXPLAIN_AGAIN", "DONT_UNDERSTAND"):
            if version >= teaching_stages.PIPELINE_V2:
                target = pipeline.reteach_stage()
                if progress.current_stage != target:
                    if progress.current_stage == "VERIFY":
                        progress.verify_hint_count += 1
                    self.move(progress, target, operation, "用户要求重新讲解")
            elif progress.current_stage not in ("TEACH", "DEMO"):
                if progress.current_stage == "VERIFY":
                    progress.verify_hint_count += 1
                self.move(progress, "TEACH", operation, "用户要求重新讲解")
        operation.stage = progress.current_stage
        operation.previous_status = progress.stage_status
        if action == "ANSWER":
            operation.kind = "evaluation"
            operation.question_message_id = progress.question_message_id
            if version >= teaching_stages.PIPELINE_V2:
                self._bump_stage_counter(progress, progress.current_stage)
            else:
                counter = {"CHECK": "check_attempts", "PAIR": "pair_attempts", "VERIFY": "verify_attempts"}[progress.current_stage]
                setattr(progress, counter, getattr(progress, counter) + 1)
        elif action in ("ASK", "GIVE_HINT") or (action == "TRY_MYSELF" and progress.current_question):
            operation.kind = "explanation"
        elif pipeline.is_task(progress.current_stage) if version >= teaching_stages.PIPELINE_V2 else progress.current_stage in ("CHECK", "PAIR", "VERIFY"):
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
        self._sync_side_records(progress)
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
            # P1.6-F：讲解/巩固阶段完成时同步长期等级（0→1，或巩固后 4→5）。
            row = classroom_service.get_session_row(self.db, progress.session_id)
            course, _chapter, point = classroom_service.load_entities_for_row(self.db, row)
            mastery.sync_level(self.db, point=point, progress=progress, course=course, reason="阶段完成")
        elif operation.kind == "task":
            task: TeachingTask = structured
            progress.current_question = task.question
            progress.rubric = task.rubric
            progress.hint = task.hint
            progress.question_message_id = assistant.id
            progress.stage_status = "WAITING_USER"
            # P1.6-B：旧读取路径不变，同时把题目写成通用活动实例。
            activities.record_task(self.db, progress=progress, operation=operation, task=task)
        elif operation.kind == "explanation":
            progress.stage_status = operation.previous_status
        elif operation.kind == "evaluation":
            self.apply_evaluation(progress, operation, structured)
        operation.status = "completed"
        operation.ended_at = now()
        self.event(progress, "ACTION_COMPLETED", operation.action, operation)
        self._sync_side_records(progress)
        self.db.commit()
        return self.view(progress)

    def apply_evaluation(self, progress, operation, result: TeachingJudgment):
        user = self.db.get(ChatMessage, operation.user_message_id)
        version = teaching_stages.normalize_version(getattr(progress, "pipeline_version", 1))
        if version >= teaching_stages.PIPELINE_V2:
            allowed = self.pipeline(progress).allowed_verdicts(operation.stage)
        else:
            allowed = {"PASSED", "NEEDS_REVIEW", "FAILED", "UNCLEAR"} if operation.stage == "VERIFY" else {"CORRECT", "PARTIAL", "INCORRECT", "UNCLEAR"}
        if result.evaluation not in allowed:
            raise ValidationError("模型评价与当前阶段不匹配，请重新提交")
        if result.evaluation in ("CORRECT", "PASSED"):
            generic = user.content.strip().rstrip("。.!！").lower() in ("我懂了", "懂了", "知道了", "明白了", "ok", "yes", "好的", "会了")
            if generic or not result.evidence_quote.strip() or result.evidence_quote not in user.content:
                result = result.model_copy(update={"evaluation": "UNCLEAR", "feedback": "仅确认理解不足以通过。请针对当前问题给出具体解释或代码片段。", "reason": "缺少可引用的实际回答证据", "suggested_action": "ASK_CLARIFICATION"})
                self.db.get(ChatMessage, operation.assistant_message_id).content = result.feedback
        row = classroom_service.get_session_row(self.db, progress.session_id)
        course, _chapter, point = classroom_service.load_entities_for_row(self.db, row)
        activity = learning_record.active_activity(self.db, progress.session_id)
        teaching_activity_type = activities.activity_type_for_question(
            self.db, progress.session_id, operation.question_message_id
        )

        operation.result_json = result.model_dump_json()
        progress.stage_status = "WAITING_USER"

        mistakes.record_mistake(
            self.db,
            operation=operation,
            progress=progress,
            point=point,
            stage=operation.stage,
            verdict=result.evaluation,
            reason=result.reason,
            feedback=result.feedback,
            misconceptions=list(result.misconceptions),
            activity_type=teaching_activity_type,
        )
        # 评价行最后再登记：若最终提交失败，事件流会把整个事务回滚，不会留下成功评价。
        self.db.add(TeachingEvaluation(operation_id=operation.id, session_id=operation.session_id, stage=operation.stage,
            verdict=result.evaluation, payload=result.model_dump_json(), hint_count=progress.verify_hint_count if operation.stage == "VERIFY" else progress.hint_count))
        # P1.6-B：把评价结果回写到对应活动实例（只写不读）。
        activities.record_evaluation(self.db, progress=progress, operation=operation, judgment=result)

        if result.evaluation != "UNCLEAR":
            if version >= teaching_stages.PIPELINE_V2:
                self._apply_evaluation_v2(progress, operation, result, course, point)
            elif operation.stage == "CHECK":
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
                    point.learning_status = "completed"
                    point.completion_source = "verified"
                    point.last_studied_at = now()
                    course.last_studied_at = now()
                else:
                    self.move(progress, "PAIR", operation, result.reason)
                    progress.mastery_state = "NEEDS_REVIEW"

        # 之前已进入待复习的知识点，错误回答不会把状态“洗白”；正确回答仍可逐步恢复。
        if point.mastery_state == mastery.NEEDS_REVIEW and result.evaluation in (
            "INCORRECT", "PARTIAL", "UNCLEAR", "FAILED", "NEEDS_REVIEW",
        ):
            progress.mastery_state = mastery.NEEDS_REVIEW

        new_mastery_state, _previous_mastery_state = mastery.apply(
            self.db,
            point=point,
            progress=progress,
            course=course,
            stage=operation.stage,
            verdict=result.evaluation,
            action=operation.action,
            reason=result.reason,
            evidence={
                "activityId": activity.id if activity else None,
                "operationId": operation.id,
                "activityType": teaching_activity_type,
            },
        )
        if new_mastery_state:
            progress.mastery_state = new_mastery_state
        if operation.stage == "VERIFY" and result.evaluation == "PASSED":
            learning_record.complete_for_session(self.db, progress.session_id, reason="verified")
        self._sync_side_records(progress)

    def _apply_evaluation_v2(self, progress, operation, result, course, point):
        """v2 活动级评价：由阶段契约决定完成、重试或回退。"""
        pipeline = self.pipeline(progress)
        stage = operation.stage
        transition = pipeline.transition(progress, stage, result.evaluation)
        if pipeline.is_verify(stage):
            progress.verification_result = result.evaluation

        if transition.advance_activity:
            progress.pair_step += 1
            self._clear_question(progress)
            progress.stage_status = "PENDING"
            if transition.mastery_state:
                progress.mastery_state = transition.mastery_state
            self.event(progress, "ACTIVITY_ADVANCED", f"{stage} 进入第 {progress.pair_step} 步", operation)
            return

        if transition.retry:
            self._clear_question(progress)
            progress.stage_status = "PENDING"
            if transition.mastery_state:
                progress.mastery_state = transition.mastery_state
            self.event(progress, "TARGETED_RECHECK", result.reason, operation)
            return

        if transition.complete_stage:
            self.complete_stage(progress, operation)
        if transition.move_to:
            self.move(progress, transition.move_to, operation, result.reason)
        if transition.mastery_state:
            progress.mastery_state = transition.mastery_state

        if transition.finished:
            progress.completed_at = now()
            if transition.summary_from_result:
                progress.summary = result.summary or result.feedback
            point.learning_status = "completed"
            point.completion_source = "verified"
            point.last_studied_at = now()
            course.last_studied_at = now()
            # 旧流程在 NEXT 结束；v2 还会进入可选的巩固总结。
            progress.stage_status = "COMPLETED" if progress.current_stage == "NEXT" else "PENDING"
        elif progress.stage_status == "WAITING_USER" and not progress.current_question:
            progress.stage_status = "PENDING"

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
            try:
                self._sync_side_records(progress)
            except Exception:  # noqa: BLE001 - 断点写入失败不能覆盖原始错误
                self.db.rollback()
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
            learning_record.complete_for_session(self.db, session_id, reason="next_point")
        elif payload.action == "RESTART":
            progress.round_number += 1
            version = teaching_stages.normalize_version(getattr(progress, "pipeline_version", 1))
            target = self.pipeline(progress).first_stage() if version >= teaching_stages.PIPELINE_V2 else "TEACH"
            self.move(progress, target, operation, "用户明确重新学习，保留原证据")
            progress.completed_stages = "[]"
            progress.stage_counters = "{}"
            progress.completed_at = None
            progress.verification_result = None
            progress.summary = ""
            progress.verify_hint_count = 0
            progress.mastery_state = "INTRODUCED"
            row = classroom_service.get_session_row(self.db, session_id)
            _course, _chapter, point = classroom_service.load_entities_for_row(self.db, row)
            point.learning_status = "in_progress"
            learning_record.interrupt_for_session(self.db, session_id, "restarted")
            snapshot = breakpoints.get_or_create(self.db, session_id)
            snapshot.draft_answer = ""
            snapshot.input_mode = "ASK"
        self.event(progress, payload.action, "用户操作", operation)
        self._sync_side_records(progress)
        result = {"teaching": self.view(progress), "nextKnowledgePointId": next_id, "courseComplete": course_complete}
        operation.result_json = json.dumps(result, ensure_ascii=False)
        self.db.commit()
        return result

    def recover(self):
        operations = self.db.scalars(select(TeachingOperation).where(TeachingOperation.status == "active")).all()
        for operation in operations:
            message = self.db.get(ChatMessage, operation.assistant_message_id)
            self.fail(operation.id, "服务曾中断，本阶段未自动推进，请重试。", message.content if message else "", interrupted=True)
