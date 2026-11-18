"""AI 学习教室接口（P1.3）。

普通接口返回统一外壳 `{code, message, data}`；生成接口返回 SSE：
- `meta`：会话与本次助手消息 ID；
- `delta`：真实模型返回的文本增量；
- `done`：最终消息对象（已落库）；
- `error`：可展示的错误信息（已落库为 failed 消息）。

流式生成使用独立的 SessionLocal：FastAPI 的请求级依赖会在响应开始后关闭，
不能拿来持续写数据库。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.response import ApiResponse, ConflictError, ValidationError, success
from ...db import SessionLocal
from ...db.models import ChatMessage, LearningSession, TeachingProgress
from ...schemas.classroom import (
    ChatMessageOut,
    ClassroomContextOut,
    ClassroomSessionOut,
    MessageCreateRequest,
    SessionOpenRequest,
    StopStreamResult,
)
from ...services import classroom_service, stream_registry, teaching_prompt
from ...services.llm_client import LLMStreamError, stream_chat
from ..deps import db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/classroom", tags=["classroom"])
SessionId = Annotated[int, Path(gt=0)]

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"




@dataclass(slots=True)
class PreparedStream:
    session_id: int
    assistant_id: int
    base_url: str
    model_name: str
    api_key: str = field(repr=False)
    messages: list[dict[str, str]] = field(repr=False)


def _prepare_stream(session_id: int, *, content: str | None = None, regenerate: bool = False) -> PreparedStream:
    """校验模型与归属，创建助手占位消息，返回调用模型所需的最小信息。"""
    with SessionLocal() as db:
        row = classroom_service.get_session_row(db, session_id)
        if db.get(TeachingProgress, session_id) is not None:
            raise ConflictError("本会话已启用教学流程，请通过教学操作提问或重试，以保留学习证据")
        classroom_service.load_entities_for_row(db, row)
        model = classroom_service.resolve_model(db, row.model_config_id)
        if model is None:
            raise ValidationError("还没有可用的模型配置，请先到「模型配置」新建并测试一个模型")
        api_key = classroom_service.decrypt_model_key(db, model)
        if regenerate:
            classroom_service.delete_last_assistant(db, row)
        if content is not None:
            classroom_service.add_user_message(db, row, content)
        course, chapter, point, history = classroom_service.load_stream_inputs(db, row)
        for message in history:
            if message.status == "streaming":
                message.status = "interrupted"
        prompt = teaching_prompt.build_messages(course, chapter, point, history)
        assistant = classroom_service.create_assistant_message(db, row, model.model_name)
        row.model_config_id = model.id
        db.commit()
        return PreparedStream(
            session_id=session_id,
            assistant_id=assistant.id,
            base_url=model.base_url,
            model_name=model.model_name,
            api_key=api_key,
            messages=prompt,
        )


async def _register_or_conflict(session_id: int) -> asyncio.Event:
    event = await stream_registry.register(session_id)
    if event is None:
        raise ConflictError("这个知识点正在生成回答，请先等待完成或点击「停止生成」")
    return event


def _start_response(prepared: PreparedStream, event: asyncio.Event, request: Request) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(prepared, event, request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _event_stream(prepared: PreparedStream, event: asyncio.Event, request: Request):
    db = SessionLocal()
    assistant: ChatMessage | None = db.get(ChatMessage, prepared.assistant_id)
    row: LearningSession | None = db.get(LearningSession, prepared.session_id)
    parts: list[str] = []
    status = "completed"
    error_message = ""
    last_flush = time.monotonic()

    def finalize(final_status: str, error: str = "") -> None:
        if assistant is None:
            return
        classroom_service.update_assistant_message(
            db,
            assistant,
            content="".join(parts),
            status=final_status,
            error_message=error,
        )

    try:
        if assistant is None or row is None:
            raise RuntimeError("助手消息或学习会话在生成前被删除")

        yield _sse(
            "meta",
            {
                "sessionId": prepared.session_id,
                "messageId": prepared.assistant_id,
                "modelName": prepared.model_name,
            },
        )

        upstream = stream_chat(
            base_url=prepared.base_url,
            model_name=prepared.model_name,
            api_key=prepared.api_key,
            messages=prepared.messages,
            max_tokens=settings.llm_reply_max_tokens,
        )
        async with aclosing(stream_registry.interruptible(upstream, event)) as stream:
            async for delta in stream:
                parts.append(delta)
                yield _sse("delta", {"text": delta})
                now = time.monotonic()
                if now - last_flush >= 1.2:
                    classroom_service.update_assistant_message(
                        db,
                        assistant,
                        content="".join(parts),
                        status="streaming",
                    )
                    last_flush = now

        if status != "interrupted":
            if event.is_set():
                status = "interrupted"
            elif not parts:
                status = "failed"
                error_message = "模型没有返回任何内容，请检查模型名称或稍后重试"

        finalize(status, error_message)
        yield _sse(
            "done",
            {
                "sessionId": prepared.session_id,
                "messageId": prepared.assistant_id,
                "status": status,
                "message": classroom_service.message_out(assistant, streaming=False).model_dump(
                    mode="json", by_alias=True
                ),
            },
        )
    except asyncio.CancelledError:
        # 浏览器主动断开：保留已经生成的内容，按「中断」落库后继续向上抛，让服务器收尾。
        try:
            finalize("interrupted")
        except Exception:  # noqa: BLE001 - 断开时数据库可能已关闭，不能再影响取消流程
            logger.exception("中断回答时保存部分内容失败 session=%s", prepared.session_id)
        raise
    except LLMStreamError as exc:
        logger.warning("教学回答生成失败 session=%s: %s", prepared.session_id, exc.message)
        try:
            finalize("failed", exc.message)
        except Exception:  # noqa: BLE001
            logger.exception("保存失败消息失败 session=%s", prepared.session_id)
        yield _sse(
            "error",
            {
                "sessionId": prepared.session_id,
                "messageId": prepared.assistant_id,
                "message": exc.message,
                "httpStatus": exc.http_status,
            },
        )
    except Exception as exc:  # noqa: BLE001 - 生成器里的异常必须转成可展示信息
        logger.error("教学回答出现未预期异常 session=%s type=%s", prepared.session_id, type(exc).__name__)
        message = f"生成回答时发生内部错误：{exc.__class__.__name__}"
        try:
            finalize("failed", message)
        except Exception:  # noqa: BLE001
            logger.exception("保存失败消息失败 session=%s", prepared.session_id)
        yield _sse(
            "error",
            {
                "sessionId": prepared.session_id,
                "messageId": prepared.assistant_id,
                "message": message,
            },
        )
    finally:
        db.close()
        await asyncio.shield(stream_registry.unregister(prepared.session_id, event))


# ------------------------------------------------------------------ 普通接口

@router.get("/context", response_model=ApiResponse[ClassroomContextOut], summary="当前课程与知识点的教学上下文")
def get_context(
    course_id: int = Query(..., alias="courseId", gt=0),
    point_id: int = Query(..., alias="pointId", gt=0),
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(classroom_service.get_context(session, course_id, point_id))


@router.post("/sessions", response_model=ApiResponse[ClassroomSessionOut], summary="创建或恢复知识点学习会话")
def open_session(payload: SessionOpenRequest, session: Session = Depends(db_session)) -> ApiResponse:
    detail = classroom_service.open_session(
        session,
        course_id=payload.course_id,
        point_id=payload.knowledge_point_id,
        model_config_id=payload.model_config_id,
    )
    return success(detail, message="会话已就绪")


@router.get("/sessions/{session_id}", response_model=ApiResponse[ClassroomSessionOut], summary="获取会话与历史消息")
def get_session(session_id: SessionId, session: Session = Depends(db_session)) -> ApiResponse:
    return success(classroom_service.get_session(session, session_id))


@router.get("/sessions/{session_id}/messages", response_model=ApiResponse[list[ChatMessageOut]], summary="按 ID 顺序分页读取历史消息")
def get_messages(
    session_id: SessionId,
    after_id: int = Query(default=0, alias="afterId", ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(db_session),
) -> ApiResponse:
    row = classroom_service.get_session_row(session, session_id)
    classroom_service.load_entities_for_row(session, row)
    messages = session.scalars(select(ChatMessage).where(
        ChatMessage.session_id == session_id, ChatMessage.id > after_id,
    ).order_by(ChatMessage.id).limit(limit)).all()
    return success([classroom_service.message_out(message, streaming=stream_registry.is_active(session_id)) for message in messages])


@router.post("/sessions/{session_id}/stop", response_model=ApiResponse[StopStreamResult], summary="停止当前生成")
async def stop_stream(session_id: SessionId, session: Session = Depends(db_session)) -> ApiResponse:
    classroom_service.get_session_row(session, session_id)
    stopped = await stream_registry.cancel(session_id)
    return success(
        StopStreamResult(
            stopped=stopped,
            message="已请求停止，正在保留已生成的内容" if stopped else "当前没有正在生成的回答",
        ),
        message="ok",
    )


# ------------------------------------------------------------------ 流式接口

@router.post("/sessions/{session_id}/start", summary="进入知识点后主动开始教学（SSE）")
async def start_teaching(session_id: SessionId, request: Request) -> StreamingResponse:
    event = await _register_or_conflict(session_id)
    try:
        with SessionLocal() as db:
            row = classroom_service.get_session_row(db, session_id)
            existing = db.scalars(
                select(ChatMessage.id).where(
                    ChatMessage.session_id == row.id,
                    ChatMessage.role == "assistant",
                )
            ).first()
            if existing is not None:
                raise ConflictError("这个知识点已经有教学对话，请直接提问或重新生成")
        prepared = _prepare_stream(session_id)
    except BaseException:
        await stream_registry.unregister(session_id, event)
        raise
    return _start_response(prepared, event, request)


@router.post("/sessions/{session_id}/messages", summary="发送问题并流式获取回答（SSE）")
async def send_message(session_id: SessionId, payload: MessageCreateRequest, request: Request) -> StreamingResponse:
    event = await _register_or_conflict(session_id)
    try:
        prepared = _prepare_stream(session_id, content=payload.content)
    except BaseException:
        await stream_registry.unregister(session_id, event)
        raise
    return _start_response(prepared, event, request)


@router.post("/sessions/{session_id}/regenerate", summary="重新生成最后一条回答（SSE）")
async def regenerate(session_id: SessionId, request: Request) -> StreamingResponse:
    event = await _register_or_conflict(session_id)
    try:
        prepared = _prepare_stream(session_id, regenerate=True)
    except BaseException:
        await stream_registry.unregister(session_id, event)
        raise
    return _start_response(prepared, event, request)
