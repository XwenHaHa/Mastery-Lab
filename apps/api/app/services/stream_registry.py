"""正在生成的教学回答登记表（P1.3）。

用途：
- 同一个会话不能并发发起两次生成；
- 「停止生成」接口能通知另一个请求里的 SSE 生成器尽快收尾；
- 会话详情能告诉前端当前是否仍在生成。

只适用于单进程本地服务；多进程部署时需要换成跨进程的取消机制（例如 Redis 标记）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

_lock = asyncio.Lock()
_active: dict[int, asyncio.Event] = {}


async def register(session_id: int) -> asyncio.Event | None:
    """登记一个生成任务；已有任务在跑时返回 None。"""
    async with _lock:
        if session_id in _active:
            return None
        event = asyncio.Event()
        _active[session_id] = event
        return event


async def unregister(session_id: int, event: asyncio.Event) -> None:
    async with _lock:
        if _active.get(session_id) is event:
            _active.pop(session_id, None)


async def cancel(session_id: int) -> bool:
    """请求停止；返回当前是否有生成任务。"""
    async with _lock:
        event = _active.get(session_id)
        if event is None:
            return False
        event.set()
        return True


def is_active(session_id: int) -> bool:
    return session_id in _active


async def interruptible(source: AsyncGenerator[str, None], event: asyncio.Event) -> AsyncIterator[str]:
    stop = asyncio.create_task(event.wait())
    pending = None
    try:
        while not event.is_set():
            pending = asyncio.create_task(anext(source))
            done, _waiting = await asyncio.wait((pending, stop), return_when=asyncio.FIRST_COMPLETED)
            if stop in done:
                break
            try:
                yield pending.result()
            except StopAsyncIteration:
                break
    finally:
        tasks = [task for task in (pending, stop) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await source.aclose()
