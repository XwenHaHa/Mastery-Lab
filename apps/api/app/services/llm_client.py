"""OpenAI 兼容接口的最小客户端。

P0 只需要两件事：验证配置可用（/chat/completions 发一次极小请求），
以及为后续流式对话留出统一的调用位置。这里不引入官方 SDK，
避免多一层版本耦合，也便于支持任意 OpenAI 兼容网关。
"""

from __future__ import annotations

import json
import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from contextlib import aclosing

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)


def resolve_chat_endpoint(base_url: str) -> str:
    """把用户填写的 Base URL 归一化到 /chat/completions。"""
    url = base_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


@dataclass(slots=True)
class ChatProbeResult:
    ok: bool
    message: str
    latency_ms: int = 0
    model: str = ""
    reply: str = ""
    http_status: int | None = None


def _extract_reply(payload: dict) -> str:
    try:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        content = choices[0].get("message", {}).get("content", "")
        return content.strip() if isinstance(content, str) else ""
    except Exception:  # noqa: BLE001 - 上游返回结构不可控
        return ""


def _describe_http_error(status: int, body: str) -> str:
    hints = {
        400: "请求被拒绝，请检查模型名称是否正确",
        401: "API Key 无效或已过期",
        403: "API Key 无权访问该模型",
        404: "接口地址不存在，请确认 Base URL 是否包含 /v1",
        429: "触发限流或额度不足",
    }
    hint = hints.get(status, "上游服务返回异常")
    return f"{hint}（HTTP {status}）"


async def probe_chat(
    *,
    base_url: str,
    model_name: str,
    api_key: str,
    prompt: str,
) -> ChatProbeResult:
    """调用一次 /chat/completions，返回可展示的结果（异常不外抛）。"""
    endpoint = resolve_chat_endpoint(base_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 32,
        "stream": False,
    }

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(endpoint, headers=headers, json=body)
    except httpx.TimeoutException:
        return ChatProbeResult(
            ok=False,
            message=f"连接超时（超过 {settings.llm_timeout_seconds:g} 秒），请检查网络或接口地址",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except httpx.HTTPError as exc:
        return ChatProbeResult(
            ok=False,
            message=f"无法连接接口：{exc.__class__.__name__}",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        return ChatProbeResult(
            ok=False,
            message=_describe_http_error(response.status_code, response.text),
            latency_ms=latency_ms,
            http_status=response.status_code,
        )

    try:
        payload = response.json()
    except ValueError:
        return ChatProbeResult(
            ok=False,
            message="接口返回的不是 JSON，可能不是 OpenAI 兼容服务",
            latency_ms=latency_ms,
            http_status=response.status_code,
        )

    reply = _extract_reply(payload)
    model = str((payload.get("model") if isinstance(payload, dict) else None) or model_name).replace(api_key, "[已隐藏]")
    if not reply:
        return ChatProbeResult(
            ok=False,
            message="接口连通，但返回内容为空，请检查模型名称是否可用",
            latency_ms=latency_ms,
            model=model,
            http_status=response.status_code,
        )

    return ChatProbeResult(
        ok=True,
        message=f"连接成功，模型响应正常（{latency_ms} ms）",
        latency_ms=latency_ms,
        model=model,
        reply=reply.replace(api_key, "[已隐藏]").strip()[:200],
        http_status=response.status_code,
    )


class LLMStreamError(Exception):
    """流式调用失败（网络、鉴权、上游 4xx/5xx、返回格式异常）。"""

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


def _extract_delta(payload: dict) -> str:
    """兼容 choices[0].delta.content 为字符串或内容块数组两种形态。"""
    try:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts)
        return ""
    except Exception:  # noqa: BLE001 - 上游结构不可控
        return ""


async def _stream_chat(
    *,
    base_url: str,
    model_name: str,
    api_key: str,
    messages: list[dict[str, str]],
    temperature: float = 0.6,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """真实调用 /chat/completions 的流式接口，逐段 yield 文本增量。

    - 连接超时 15 秒，读超时用 settings.llm_stream_timeout_seconds（默认 180 秒）；
    - 上游返回非 SSE 时按一次性 JSON 兼容处理；
    - 任何失败都抛 LLMStreamError，由上层转成 SSE error 事件或 HTTP 422。
    """
    endpoint = resolve_chat_endpoint(base_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    body = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens

    timeout = httpx.Timeout(
        settings.llm_stream_timeout_seconds,
        connect=min(15.0, settings.llm_stream_timeout_seconds),
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", endpoint, headers=headers, json=body) as response:
                if response.status_code >= 400:
                    raw = await response.aread()
                    snippet = raw.decode("utf-8", "replace")
                    raise LLMStreamError(
                        _describe_http_error(response.status_code, snippet),
                        http_status=response.status_code,
                    )

                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type:
                    raw = await response.aread()
                    try:
                        payload = json.loads(raw.decode("utf-8", "replace"))
                    except ValueError as exc:
                        raise LLMStreamError("模型返回不是可解析的流式数据，请确认接口是否兼容 OpenAI") from exc
                    text = _extract_reply(payload)
                    if text:
                        yield text
                    return

                finished = False
                async for line in response.aiter_lines():
                    text = line.strip()
                    if not text or text.startswith(":") or text.startswith("event:"):
                        continue
                    if not text.startswith("data:"):
                        continue
                    data = text[5:].strip()
                    if not data:
                        continue
                    if data == "[DONE]":
                        return
                    try:
                        payload = json.loads(data)
                    except ValueError as exc:
                        raise LLMStreamError("模型返回的流式数据格式无效，请检查接口兼容性") from exc
                    if not isinstance(payload, dict):
                        raise LLMStreamError("模型返回的流式数据结构无效")
                    if isinstance(payload, dict) and payload.get("error"):
                        raise LLMStreamError("模型在生成过程中返回错误，请检查模型配置、额度或稍后重试")
                    delta = _extract_delta(payload)
                    if delta:
                        yield delta
                    choices = payload.get("choices") or []
                    if choices and isinstance(choices[0], dict) and choices[0].get("finish_reason"):
                        reason = choices[0]["finish_reason"]
                        if reason == "length":
                            raise LLMStreamError("回答达到模型输出长度限制，已保留内容；可以要求老师继续讲解")
                        if reason == "content_filter":
                            raise LLMStreamError("模型服务限制了本次回答，请调整问题后重试")
                        finished = True
                if not finished:
                    raise LLMStreamError("模型数据流意外结束，已保留部分回答，请重试或继续提问")
    except LLMStreamError:
        raise
    except httpx.TimeoutException as exc:
        raise LLMStreamError(
            f"模型响应超时（超过 {settings.llm_stream_timeout_seconds:g} 秒），可以点「重新生成」再试"
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMStreamError(f"无法连接模型服务：{exc.__class__.__name__}") from exc


async def stream_chat(
    *, base_url: str, model_name: str, api_key: str, messages: list[dict[str, str]],
    temperature: float = 0.6, max_tokens: int | None = None,
) -> AsyncIterator[str]:
    pending = ""
    first = True
    source = _stream_chat(base_url=base_url, model_name=model_name, api_key=api_key,
                          messages=messages, temperature=temperature, max_tokens=max_tokens)
    try:
        async with asyncio.timeout(settings.llm_stream_total_timeout_seconds), aclosing(source):
            while True:
                try:
                    delta = await asyncio.wait_for(anext(source), timeout=(
                        min(60.0, settings.llm_stream_timeout_seconds) if first else settings.llm_stream_timeout_seconds
                    ))
                except StopAsyncIteration:
                    break
                first = False
                pending += delta
                if api_key:
                    pending = pending.replace(api_key, "[已隐藏]")
                overlap = 0
                for size in range(1, min(len(api_key), len(pending)) + 1):
                    if pending.endswith(api_key[:size]):
                        overlap = size
                output = pending[:-overlap] if overlap else pending
                pending = pending[-overlap:] if overlap else ""
                if output:
                    yield output
            if pending:
                yield "[已隐藏]" if api_key.startswith(pending) else pending
    except TimeoutError as exc:
        raise LLMStreamError("等待模型响应超时，已保留生成内容；请检查服务或重新生成") from exc
