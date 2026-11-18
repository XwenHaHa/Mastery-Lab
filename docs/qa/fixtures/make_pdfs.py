"""生成两份 PDF 测试样本（仅用于 P1.1 教材导入验证）。

1. pdf-asyncio-textlayer.pdf  有文本层、带「第 X 章 / 1.1 标题」结构，用于验证章节识别。
2. pdf-scanned-like.pdf       只有图形没有文字，用于验证「扫描件必须明确报错」。
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent
FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(FONT))

# (页码, [(文本, 字号)])：空字符串表示换段
PAGES = [
    [
        ("Python 异步编程实践手册", 20),
        ("", 12),
        ("第 1 章 协程与事件循环", 16),
        ("协程是可以在中途暂停并恢复的函数，暂停点就是 await 所在的位置。", 11),
        ("1.1 什么是协程", 13),
        ("普通函数调用一次执行到 return 才返回，协程在 await 处让出控制权，", 11),
        ("由事件循环决定何时把控制权交回来，因此单个线程也能同时推进多个任务。", 11),
        ("1.2 事件循环的角色", 13),
        ("事件循环维护就绪队列、定时器与 IO 回调，按顺序取出可运行的任务继续执行。", 11),
    ],
    [
        ("第 2 章 异步 HTTP 请求", 16),
        ("2.1 用 aiohttp 并发", 13),
        ("把每个请求包装成协程，再用 gather 一次性等待全部完成，耗时取决于最慢的那个请求。", 11),
        ("下面的片段固定缩进，用于验证 PDF 中的代码行识别：", 11),
        ("    async with aiohttp.ClientSession() as session:", 10),
        ("        async with session.get(url) as resp:", 10),
        ("2.2 超时与重试", 13),
        ("超时要显式设置，重试要限制次数并加退避，否则故障会把并发放大成雪崩。", 11),
    ],
]


def build_text_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    for index, page in enumerate(PAGES):
        c.setFont(FONT, 12)
        y = 790
        for text, size in page:
            if not text:
                y -= size + 8
                continue
            c.setFont(FONT, size)
            c.drawString(64, y, text)
            y -= size + 10
        c.setFont(FONT, 9)
        c.drawString(64, 40, f"- {index + 1} -")
        c.showPage()
    c.save()


def build_scanned_like_pdf(path: Path) -> None:
    """只有矩形、没有文本对象，模拟扫描件的效果（pypdf 抽不到文字）。"""
    c = canvas.Canvas(str(path), pagesize=A4)
    for _ in range(2):
        c.setFillGray(0.82)
        for row in range(12):
            c.rect(64, 760 - row * 46, 460, 14, stroke=0, fill=1)
        c.showPage()
    c.save()


if __name__ == "__main__":
    text_pdf = OUT / "pdf-asyncio-textlayer.pdf"
    scan_pdf = OUT / "pdf-scanned-like.pdf"
    build_text_pdf(text_pdf)
    build_scanned_like_pdf(scan_pdf)
    for f in (text_pdf, scan_pdf):
        print(f"{f.name}: {f.stat().st_size} bytes")
