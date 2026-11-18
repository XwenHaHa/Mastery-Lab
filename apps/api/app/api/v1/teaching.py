import asyncio
from contextlib import aclosing
import json
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ...core.config import settings
from ...core.response import ApiResponse, AppError, ConflictError, ValidationError, success
from ...db import SessionLocal
from ...db.models import ChatMessage, TeachingEvaluation, TeachingEvent, TeachingOperation, TeachingProgress
from ...schemas.teaching import TeachingAction
from ...services import classroom_service, stream_registry, teaching_protocol
from ...services.llm_client import LLMStreamError, stream_chat
from ...services.teaching_state import TeachingStateMachine, iso
from .classroom import SSE_HEADERS, _sse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/classroom/sessions/{session_id}/teaching", tags=["teaching"])
SessionId = Annotated[int, Path(gt=0)]


@router.get("")
def get_teaching(session_id: SessionId):
    with SessionLocal() as db:
        machine = TeachingStateMachine(db)
        return success(machine.view(machine.ensure(session_id)))


@router.get("/events")
def get_events(session_id: SessionId):
    with SessionLocal() as db:
        classroom_service.get_session_row(db, session_id)
        events = db.scalars(select(TeachingEvent).where(TeachingEvent.session_id == session_id).order_by(TeachingEvent.id)).all()
        evaluations = db.execute(select(TeachingEvaluation, TeachingOperation).join(TeachingOperation, TeachingEvaluation.operation_id == TeachingOperation.id)
            .where(TeachingEvaluation.session_id == session_id).order_by(TeachingEvaluation.id)).all()
        message_ids = {message_id for _evaluation, operation in evaluations
            for message_id in (operation.question_message_id, operation.user_message_id) if message_id is not None}
        messages = {message.id: message for message in db.scalars(select(ChatMessage).where(ChatMessage.id.in_(message_ids))).all()}
        return success({"events": [{"id": item.id, "operationId": item.operation_id, "roundNumber": item.round_number, "fromStage": item.from_stage,
            "toStage": item.to_stage, "type": item.event_type, "detail": item.detail, "createdAt": iso(item.created_at)} for item in events],
            "evaluations": [{"id": item.id, "operationId": item.operation_id, "stage": item.stage, "hintCount": item.hint_count,
                "questionMessageId": operation.question_message_id, "userMessageId": operation.user_message_id,
                "assistantMessageId": operation.assistant_message_id,
                "question": messages[operation.question_message_id].content if operation.question_message_id in messages else "",
                "answer": messages[operation.user_message_id].content if operation.user_message_id in messages else "",
                "result": json.loads(item.payload), "createdAt": iso(item.created_at)} for item, operation in evaluations]})


@router.post("/control")
async def control(session_id: SessionId, payload: TeachingAction):
    with SessionLocal() as db:
        result = TeachingStateMachine(db).control(session_id, payload)
    if payload.action == "PAUSE":
        await stream_registry.cancel(session_id)
    return success(result)


@router.post("/actions")
async def action(session_id: SessionId, payload: TeachingAction, request: Request):
    with SessionLocal() as db:
        machine = TeachingStateMachine(db)
        machine.ensure(session_id)
        previous = machine.lookup(session_id, payload)
        if previous:
            message = db.get(ChatMessage, previous.assistant_message_id)
            if not message:
                raise ConflictError("该操作已执行，请同步当前进度")
            data = {"sessionId": session_id, "messageId": message.id, "status": message.status,
                "message": classroom_service.message_out(message, streaming=False).model_dump(mode="json", by_alias=True),
                "teaching": machine.view(machine.ensure(session_id))}
            return StreamingResponse(iter([_sse("done", data)]), media_type="text/event-stream", headers=SSE_HEADERS)
    event = await stream_registry.register(session_id)
    if event is None:
        raise ConflictError("当前会话仍有生成任务，请等待或暂停")
    operation_id = None
    try:
        with SessionLocal() as db:
            machine = TeachingStateMachine(db)
            row = classroom_service.get_session_row(db, session_id)
            model = classroom_service.resolve_model(db, row.model_config_id)
            if model is None:
                raise ValidationError("还没有可用的模型配置，请先配置模型")
            key = classroom_service.decrypt_model_key(db, model)
            operation = machine.begin(session_id, payload, model.model_name)
            operation_id = operation.id
            progress = db.get(TeachingProgress, session_id)
            messages = teaching_protocol.build_messages(db, row, progress, operation, payload.content)
            prepared = {"operation_id": operation.id, "assistant_id": operation.assistant_message_id, "kind": operation.kind,
                "model_name": model.model_name, "base_url": model.base_url, "api_key": key, "messages": messages, "teaching": machine.view(progress)}
    except BaseException as error:
        try:
            if operation_id is not None:
                with SessionLocal() as db:
                    TeachingStateMachine(db).fail(operation_id, "教学准备失败，本阶段未完成，请重试。", interrupted=isinstance(error, asyncio.CancelledError))
        finally:
            await asyncio.shield(stream_registry.unregister(session_id, event))
        raise
    return StreamingResponse(event_stream(session_id, prepared, event, request), media_type="text/event-stream", headers=SSE_HEADERS)


async def event_stream(session_id, prepared, event, request):
    parts = []
    structured = prepared["kind"] in ("task", "evaluation")
    last_flush = time.monotonic()
    persisted = False
    try:
        yield _sse("meta", {"sessionId": session_id, "messageId": prepared["assistant_id"], "modelName": prepared["model_name"], "teaching": prepared["teaching"]})
        upstream = stream_chat(base_url=prepared["base_url"], model_name=prepared["model_name"], api_key=prepared["api_key"], messages=prepared["messages"], max_tokens=settings.llm_reply_max_tokens)
        async with aclosing(stream_registry.interruptible(upstream, event)) as stream:
            async for delta in stream:
                parts.append(delta)
                if sum(len(part) for part in parts) > 100000:
                    raise ValidationError("模型输出超出本阶段长度限制，请重试")
                if not structured:
                    yield _sse("delta", {"text": delta})
                    if time.monotonic() - last_flush >= 1.2:
                        with SessionLocal() as db:
                            message = db.get(ChatMessage, prepared["assistant_id"])
                            message.content = ''.join(parts)
                            db.commit()
                        last_flush = time.monotonic()
        if event.is_set():
            raise asyncio.CancelledError()
        text = ''.join(parts)
        if not text.strip():
            raise ValidationError("模型没有返回内容，请重试")
        with SessionLocal() as db:
            operation = db.get(TeachingOperation, prepared["operation_id"])
            parsed = None
            if structured:
                parsed, text = teaching_protocol.parse_result(text, operation, db)
                operation.result_json = parsed.model_dump_json()
            teaching = TeachingStateMachine(db).finish(operation.id, text, parsed)
            message = db.get(ChatMessage, prepared["assistant_id"])
            output = classroom_service.message_out(message, streaming=False).model_dump(mode="json", by_alias=True)
        persisted = True
        if structured:
            yield _sse("delta", {"text": output["content"]})
        yield _sse("done", {"sessionId": session_id, "messageId": output["id"], "status": "completed", "message": output, "teaching": teaching})
    except asyncio.CancelledError:
        if not persisted:
            with SessionLocal() as db:
                TeachingStateMachine(db).fail(prepared["operation_id"], "生成已中断，本阶段未推进。", '' if structured else ''.join(parts), interrupted=True)
        if not await request.is_disconnected():
            with SessionLocal() as db:
                machine = TeachingStateMachine(db)
                message = db.get(ChatMessage, prepared["assistant_id"])
                yield _sse("done", {"sessionId": session_id, "messageId": message.id, "status": message.status,
                    "message": classroom_service.message_out(message, streaming=False).model_dump(mode="json", by_alias=True), "teaching": machine.view(machine.ensure(session_id))})
    except Exception as error:
        safe = error.message if isinstance(error, AppError) else str(error) if isinstance(error, LLMStreamError) else "教学保存或生成失败，阶段未推进，请重试"
        try:
            with SessionLocal() as db:
                TeachingStateMachine(db).fail(prepared["operation_id"], safe, '' if structured else ''.join(parts))
        except Exception:
            logger.error("教学失败状态暂未保存：operation=%s", prepared["operation_id"])
        yield _sse("error", {"sessionId": session_id, "messageId": prepared["assistant_id"], "message": safe})
    finally:
        await asyncio.shield(stream_registry.unregister(session_id, event))
