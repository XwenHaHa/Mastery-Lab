"""教材上下文与历史裁剪（P1.6-D 起由 prompt_assembler 统一组装）。

本模块保留：
- build_context_block：课程 → 章节 → 知识点 → 教材原文；
- trim_history：按条数与字数预算裁剪历史。

角色、学科策略、阶段契约与当前活动由 `prompt_assembler` 组装，
避免 P1.3 与 P1.4 各维护一套角色定义。
"""

from __future__ import annotations

from ..core.config import settings
from ..db.models import ChatMessage, Chapter, Course, KnowledgePoint


def _clip(text: str | None, limit: int) -> tuple[str, bool]:
    value = (text or "").strip()
    if len(value) <= limit:
        return value, False
    marker = "\n…（内容截断）…\n"
    available = max(0, limit - len(marker))
    if not available:
        return value[:limit], True
    head = int(available * 0.72)
    tail = available - head
    return value[:head] + marker + (value[-tail:] if tail else ""), True


def build_context_block(
    course: Course,
    chapter: Chapter,
    point: KnowledgePoint,
    *,
    context_chars: int | None = None,
) -> str:
    """把「课程 → 章节 → 知识点 → 教材原文」压成一段可复用的上下文。"""
    limit = context_chars or settings.classroom_context_chars
    content, truncated = _clip(point.content, limit)
    lines = [
        "[课程上下文]",
        f"课程：{(course.title or '')[:200]}",
    ]
    if course.description:
        lines.append(f"课程简介：{course.description[:500]}")
    lines.extend(
        [
            f"章节：{chapter.title[:200]}",
        ]
    )
    if chapter.description:
        lines.append(f"章节简介：{chapter.description[:500]}")
    lines.extend(
        [
            f"当前知识点：{point.title[:200]}",
        ]
    )
    if point.description:
        lines.append(f"知识点摘要：{point.description[:500]}")
    lines.append("")
    lines.append("[当前知识点的教材原文]" + ("（已截断）" if truncated else ""))
    lines.append(content or "（教材没有提供该知识点的正文，请基于标题与课程主题讲解，并明确说明哪些是补充内容。）")
    lines.append("")
    lines.append(
        "请只围绕这个知识点教学；教材原文是事实依据，补充通用知识时必须用「补充：」标明。"
    )
    return "\n".join(lines)


def trim_history(
    messages: list[ChatMessage],
    *,
    max_messages: int | None = None,
    max_chars: int | None = None,
) -> list[ChatMessage]:
    """从最近的消息往前保留，控制在条数与总字数预算内。"""
    limit_messages = max_messages or settings.classroom_history_messages
    limit_chars = max_chars or settings.classroom_history_chars

    recent = [message for message in messages if message.role in ('user', 'assistant') and message.content.strip()][-limit_messages:]
    kept: list[ChatMessage] = []
    total = 0
    for message in reversed(recent):
        available = limit_chars - total
        if available <= 0:
            break
        content, truncated = _clip(message.content, available)
        kept.append(ChatMessage(role=message.role, content=content))
        total += len(content)
        if truncated:
            break
    kept.reverse()
    return kept


def build_messages(
    course: Course,
    chapter: Chapter,
    point: KnowledgePoint,
    history: list[ChatMessage],
    *,
    context_chars: int | None = None,
) -> list[dict[str, str]]:
    """P1.3 自由对话入口；实际组装统一交给 prompt_assembler。"""
    from .prompt_assembler import free_chat_messages

    return free_chat_messages(course, chapter, point, history, context_chars=context_chars)
