"""Markdown 教材解析（P1.1）。

只做确定性解析，不依赖任何模型：
- 一级标题 -> 课程名（第一个），其余一级标题 -> 章节
- 二级标题 -> 章节
- 三到六级标题 -> 知识点（归属于最近的上级章节）
- 代码围栏（``` / ~~~）收集语言标识与行数，计入所在知识点的 codeCount
没有标题时退化为"全文"单章节，不凭空编造结构。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*(.*)$")
INLINE_CODE_RE = re.compile(r"`[^`]+`")


@dataclass
class CodeBlock:
    language: str
    lines: int


@dataclass
class ParsedSection:
    title: str
    level: int
    content: list[str] = field(default_factory=list)
    code_blocks: list[CodeBlock] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.content).strip()

    @property
    def code_count(self) -> int:
        return len(self.code_blocks)


@dataclass
class ParsedChapter:
    title: str
    description: str
    points: list[ParsedSection]
    code_blocks: list[CodeBlock] = field(default_factory=list)

    @property
    def code_count(self) -> int:
        return len(self.code_blocks) + sum(point.code_count for point in self.points)


@dataclass
class ParsedMaterial:
    title: str
    description: str
    chapters: list[ParsedChapter]
    warnings: list[str]
    stats: dict[str, int]


def _strip_inline(text: str) -> str:
    cleaned = re.sub(r"[*_~>`]", "", text)
    cleaned = INLINE_CODE_RE.sub(lambda m: m.group(0).strip("`"), cleaned)
    return cleaned.strip()


def _summarize(lines: list[str], limit: int = 120) -> str:
    """取第一段有意义的正文作为简介。"""
    buffer: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            if buffer:
                break
            continue
        if line.startswith(("```", "~~~", "|", "---", "===")):
            if buffer:
                break
            continue
        buffer.append(_strip_inline(line))
        if len(" ".join(buffer)) >= limit:
            break
    summary = re.sub(r"\s+", " ", " ".join(buffer)).strip()
    if len(summary) > limit:
        summary = summary[: limit - 1].rstrip() + "…"
    return summary


def parse_markdown(text: str, fallback_title: str) -> ParsedMaterial:
    """把 Markdown 解析成 章节 -> 知识点 的建议结构。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    title = ""
    chapters: list[ParsedChapter] = []
    current_chapter: ParsedChapter | None = None
    current_point: ParsedSection | None = None
    current_chapter_lines: list[str] = []
    pending_body_before_chapter: list[str] = []

    in_fence = False
    fence_marker = ""
    fence_language = ""
    fence_buffer: list[str] = []

    def flush_point() -> None:
        nonlocal current_point
        if current_point is None:
            return
        if current_chapter is not None:
            current_chapter.points.append(current_point)
        current_point = None

    def flush_chapter() -> None:
        nonlocal current_chapter, current_chapter_lines
        if current_chapter is None:
            return
        current_chapter.description = _summarize(current_chapter_lines)
        chapters.append(current_chapter)
        current_chapter = None
        current_chapter_lines = []

    def ensure_chapter(name: str = "开篇") -> ParsedChapter:
        nonlocal current_chapter
        if current_chapter is None:
            current_chapter = ParsedChapter(title=name, description="", points=[])
        return current_chapter

    def attach_point(name: str) -> ParsedSection:
        nonlocal current_point
        ensure_chapter()
        current_point = ParsedSection(title=name, level=3)
        return current_point

    index = 0
    while index < len(lines):
        raw = lines[index]
        line = raw.rstrip()
        fence_match = FENCE_RE.match(line)

        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker[0]
                fence_language = fence_match.group(2).strip().split(" ")[0] if fence_match.group(2) else ""
                fence_buffer = []
            elif marker[0] == fence_marker:
                in_fence = False
                language = fence_language or "text"
                block = CodeBlock(language=language, lines=len(fence_buffer))
                fenced_lines = [f"```{language}", *fence_buffer, "```"]
                if current_point is not None:
                    current_point.code_blocks.append(block)
                    current_point.content.extend(fenced_lines)
                elif current_chapter is not None:
                    current_chapter_lines.extend(fenced_lines)
                    current_chapter.code_blocks.append(block)
                fence_language = ""
                fence_buffer = []
            else:
                fence_buffer.append(raw)
            index += 1
            continue

        if in_fence:
            fence_buffer.append(raw)
            index += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            name = _strip_inline(heading.group(2)) or "未命名"

            if level == 1 and not title:
                title = name
            elif level <= 2:
                flush_point()
                flush_chapter()
                ensure_chapter(name)
            else:
                flush_point()
                attach_point(name)
            index += 1
            continue

        if current_point is not None:
            current_point.content.append(raw)
        elif current_chapter is not None:
            current_chapter_lines.append(raw)
        else:
            pending_body_before_chapter.append(raw)
        index += 1

    flush_point()

    # 没有标题：退化为单章节单知识点
    if not chapters and current_chapter is None:
        body = "\n".join(pending_body_before_chapter).strip()
        if body:
            point = ParsedSection(title=title or fallback_title, level=3)
            point.content = pending_body_before_chapter
            chapters.append(
                ParsedChapter(title="全文", description=_summarize(pending_body_before_chapter), points=[point])
            )
        else:
            chapters.append(ParsedChapter(title="全文", description="", points=[]))
    else:
        # 章节存在但没有任何正文（例如只有标题）：补一个同名知识点，避免空章节
        if current_chapter is not None:
            current_chapter.description = _summarize(current_chapter_lines)
            if not current_chapter.points:
                filler = ParsedSection(title=current_chapter.title, level=3)
                filler.content = current_chapter_lines
                current_chapter.points.append(filler)
        if current_chapter is not None:
            chapters.append(current_chapter)

    # 章节如果没有知识点（例如只有一行标题），补同名知识点
    for chapter in chapters:
        if not chapter.points:
            filler = ParsedSection(title=chapter.title, level=3)
            chapter.points.append(filler)

    warnings: list[str] = []
    if not title:
        title = fallback_title
    if len(chapters) == 1 and chapters[0].title == "全文":
        warnings.append("教材没有 Markdown 标题层级，已按「全文」单章节处理")

    code_total = sum(chapter.code_count for chapter in chapters)
    stats = {
        "chapters": len(chapters),
        "knowledgePoints": sum(len(chapter.points) for chapter in chapters),
        "codeBlocks": code_total,
        "characters": len(text),
    }

    description = ""
    for chapter in chapters:
        if chapter.description:
            description = chapter.description
            break

    return ParsedMaterial(title=title, description=description, chapters=chapters, warnings=warnings, stats=stats)
