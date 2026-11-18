"""PDF 教材解析（P1.1）。

能力边界（不做过度承诺）：
- 只处理"有文本层"的 PDF：pypdf 直接抽文字；
- 扫描版 / 图片型 PDF 抽不到文字时抛 PdfNoTextError，由上层给出明确提示，
  绝不返回伪造的章节结构；
- 章节结构靠启发式识别（第 X 章、1.2 标题、全大写短行等），识别不到就按页组织，
  并在 warnings 里说明。
"""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .md_parser import CodeBlock, ParsedChapter, ParsedMaterial, ParsedSection, _summarize

MIN_TEXT_CHARS = 20
MAX_HEADING_LEN = 42

CN_CHAPTER_RE = re.compile(r"^第\s*[一二三四五六七八九十百零〇\d]{1,4}\s*[章节篇部]\s*[、.:：]?\s*\S")
NUMBERED_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})[\s、.]+\S")
UPPER_RE = re.compile(r"^[A-Z][A-Z0-9 \-_&/]{3,40}$")
CODE_LINE_RE = re.compile(r"^(?: {4,}|\t)\S")
SENTENCE_END = tuple("。！？；，、：:;,.!?")


class PdfNoTextError(RuntimeError):
    """PDF 没有可提取的文本层（多为扫描件）。"""


def _looks_like_heading(line: str) -> tuple[bool, int]:
    text = line.strip()
    if not text or len(text) > MAX_HEADING_LEN:
        return False, 0
    if text.endswith(SENTENCE_END):
        return False, 0
    if CN_CHAPTER_RE.match(text):
        return True, 1
    numbered = NUMBERED_RE.match(text)
    if numbered:
        depth = numbered.group(1).count(".") + 1
        return True, min(depth, 2)
    if UPPER_RE.match(text) and any(ch.isalpha() for ch in text):
        return True, 1
    return False, 0


def _collect_code(lines: list[str], sink: list[str], blocks: list[CodeBlock]) -> None:
    """把缩进文本行收成代码块，其余行原样写入 sink。

    注意：非代码行必须无条件写入 sink，早期版本只在「刚关闭一个代码块」时才写，
    导致 PDF 正文在有代码块的段落里被静默丢弃。
    """

    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        sink.extend(["```text", *buffer, "```"])
        blocks.append(CodeBlock(language="text", lines=len(buffer)))
        buffer = []

    for line in lines:
        if CODE_LINE_RE.match(line):
            buffer.append(line)
            continue
        flush()
        sink.append(line)
    flush()


def _read_pages(path: Path) -> list[str]:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 - pypdf 抛的异常类型较杂
        raise PdfNoTextError(f"PDF 无法打开：{exc.__class__.__name__}") from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise PdfNoTextError("PDF 已加密，无法读取内容") from exc

    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - 单页失败不应整份失败
            pages.append("")
    return pages


def parse_pdf(path: Path, fallback_title: str) -> ParsedMaterial:
    pages = _read_pages(path)
    joined = "\n".join(pages)
    if len(joined.strip()) < MIN_TEXT_CHARS:
        raise PdfNoTextError(
            "这个 PDF 没有可提取的文本层（多为扫描件或纯图片），当前版本无法识别其文字。请先用 OCR 工具转成文本，或改用 Markdown 教材。"
        )

    chapters: list[ParsedChapter] = []
    current_chapter: ParsedChapter | None = None
    current_point: ParsedSection | None = None
    chapter_body: list[str] = []
    point_lines: list[str] = []
    title = ""
    saw_heading = False
    took_first_line = False
    empty_pages = 0

    def flush_point() -> None:
        nonlocal current_point, point_lines
        if current_point is not None and current_chapter is not None:
            # 缩进代码的识别要拿到整段行，逐行判断永远凑不成一个代码块
            _collect_code(point_lines, current_point.content, current_point.code_blocks)
            current_chapter.points.append(current_point)
        current_point = None
        point_lines = []

    def flush_chapter() -> None:
        nonlocal current_chapter, chapter_body
        if current_chapter is not None:
            current_chapter.description = _summarize(chapter_body)
            chapters.append(current_chapter)
        current_chapter = None
        chapter_body = []

    for page_index, page_text in enumerate(pages, start=1):
        lines = [line for line in page_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        if not page_text.strip():
            empty_pages += 1

        for raw in lines:
            line = raw.strip()
            if not line:
                if current_point is not None:
                    point_lines.append("")
                elif current_chapter is not None:
                    chapter_body.append("")
                continue

            is_heading, depth = _looks_like_heading(line)
            if is_heading:
                saw_heading = True
                if depth == 1 and not title and not chapters and current_chapter is None:
                    title = line
                    continue
                if depth == 1:
                    flush_point()
                    flush_chapter()
                    current_chapter = ParsedChapter(title=line, description="", points=[])
                else:
                    flush_point()
                    if current_chapter is None:
                        current_chapter = ParsedChapter(title=f"第 {page_index} 页", description="", points=[])
                    current_point = ParsedSection(title=line, level=3)
                continue

            # 首页第一行通常就是书名：没有识别到标题层级时用它做课程名，
            # 而不是让课程名退化成"第 1 页"
            if not took_first_line and page_index == 1 and not title and not chapters and current_chapter is None:
                took_first_line = True
                if len(line) <= 80:
                    title = line
                    continue

            if current_point is not None:
                point_lines.append(raw)
            elif current_chapter is not None:
                chapter_body.append(raw)
            else:
                # 章节之前的内容：单独开一章承载，避免丢内容
                current_chapter = ParsedChapter(title=f"开篇（第 {page_index} 页）", description="", points=[])
                chapter_body.append(raw)
    flush_point()
    flush_chapter()

    # 完全识别不到标题：按页组织，明确告知
    if not saw_heading:
        chapters = []
        for page_index, page_text in enumerate(pages, start=1):
            if not page_text.strip():
                continue
            point = ParsedSection(title=f"第 {page_index} 页", level=3)
            _collect_code([line.rstrip() for line in page_text.split("\n")], point.content, point.code_blocks)
            chapters.append(
                ParsedChapter(
                    title=f"第 {page_index} 页",
                    description=_summarize([line.rstrip() for line in page_text.split("\n")]),
                    points=[point],
                )
            )

    if not chapters:
        raise PdfNoTextError("PDF 有文本层但内容为空，无法生成课程结构")

    for chapter in chapters:
        if not chapter.points:
            filler = ParsedSection(title=chapter.title, level=3)
            filler.content = []
            chapter.points.append(filler)

    warnings: list[str] = []
    if not saw_heading:
        warnings.append("未识别到 PDF 标题层级，已按页生成章节与知识点")
    if empty_pages:
        warnings.append(f"有 {empty_pages} 页没有文字（可能是插图页），已跳过")
    if not title:
        title = chapters[0].title if chapters else fallback_title
        if title.startswith("第 ") and title.endswith(" 页"):
            title = fallback_title

    stats = {
        "chapters": len(chapters),
        "knowledgePoints": sum(len(chapter.points) for chapter in chapters),
        "codeBlocks": sum(chapter.code_count for chapter in chapters),
        "characters": len(joined),
        "pages": len(pages),
    }

    description = next((chapter.description for chapter in chapters if chapter.description), "")
    return ParsedMaterial(title=title, description=description, chapters=chapters, warnings=warnings, stats=stats)
