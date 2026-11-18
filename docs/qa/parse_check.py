"""P1.1 教材解析的结构核对脚本（只读：不连数据库、不启动服务）。

直接调用 app.services 下的解析函数，把「Markdown 多级标题 / 代码块」和
「PDF 文本层 / 章节启发式」的结果打印成可核对的 JSON。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# docs/qa/parse_check.py -> 项目根目录在上面两层
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.md_parser import parse_markdown  # noqa: E402
from app.services.pdf_parser import PdfNoTextError, parse_pdf  # noqa: E402
FIXTURES = Path(__file__).parent / "fixtures"



def dump(parsed) -> dict:
    return {
        "title": parsed.title,
        "description": parsed.description,
        "warnings": parsed.warnings,
        "stats": parsed.stats,
        "chapters": [
            {
                "title": chapter.title,
                "description": chapter.description,
                "codeCount": chapter.code_count,
                "points": [
                    {
                        "title": point.title,
                        "level": point.level,
                        "codeCount": point.code_count,
                        "codeLanguages": [block.language for block in point.code_blocks],
                        "codeLines": [block.lines for block in point.code_blocks],
                        "excerpt": point.text[:60],
                    }
                    for point in chapter.points
                ],
            }
            for chapter in parsed.chapters
        ],
    }


def main() -> None:
    report: dict[str, object] = {}

    md_path = FIXTURES / "advanced-python.md"
    report["markdown"] = dump(parse_markdown(md_path.read_text(encoding="utf-8"), md_path.stem))

    pdf_path = FIXTURES / "pdf-asyncio-textlayer.pdf"
    report["pdf"] = dump(parse_pdf(pdf_path, pdf_path.stem))

    # 扫描件：必须明确报错，而不是凭空生成结构
    try:
        result = parse_pdf(FIXTURES / "pdf-scanned-like.pdf", "scan")
        report["scanned_pdf"] = {"raised": False, "chapters": len(result.chapters)}
    except PdfNoTextError as exc:
        report["scanned_pdf"] = {"raised": True, "type": type(exc).__name__, "message": str(exc)}

    out = FIXTURES.parent / "parse-result.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
