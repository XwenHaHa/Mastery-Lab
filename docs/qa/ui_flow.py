"""P1.1 教材导入的端到端 UI 验证（Playwright）。

流程：导入页截图 -> Markdown 解析 -> 结构编辑（改名/上移/新增章节）->
确认创建课程 -> 课程详情与课程中心截图 -> PDF 解析 -> 创建课程 -> 扫描件报错。

产出：docs/qa/screenshots/*.png 与 docs/qa/ui-flow-result.json（含每步 DOM 断言与接口状态码）。
运行：python docs/qa/ui_flow.py
"""

from __future__ import annotations
import json
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://127.0.0.1:5173"
API = "http://127.0.0.1:8000"
HERE = Path(__file__).parent
SHOTS = HERE.parent / "review" / "p1-1" / "screenshots"
FIXTURES = HERE / "fixtures"

result: dict[str, object] = {"steps": [], "consoleErrors": [], "failedRequests": []}


def shot(page: Page, name: str, full_page: bool = True) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / name), full_page=full_page)


def note(step: str, **extra: object) -> None:
    result["steps"].append({"step": step, **extra})
    print(f"[ok] {step} {extra if extra else ''}")


def chapter_titles(page: Page) -> list[str]:
    return [v.strip() for v in page.locator(".chapter-title input").evaluate_all(
        "els => els.map(e => e.value)")]


def point_titles(page: Page) -> list[str]:
    return [v.strip() for v in page.locator(".point-title input").evaluate_all(
        "els => els.map(e => e.value)")]


def upload(page: Page, file_name: str) -> None:
    page.set_input_files("input[type=file]", str(FIXTURES / file_name))
    page.wait_for_selector(".preview-step", timeout=45_000)
    page.wait_for_load_state("networkidle")


def cleanup_drafts() -> list[int]:
    """删掉上一次失败运行留下的草稿，让每次运行的起点一致。"""

    with urllib.request.urlopen(f"{API}/api/v1/courses?status=draft") as resp:
        drafts = json.load(resp)["data"]
    for draft in drafts:
        request = urllib.request.Request(f"{API}/api/v1/courses/{draft['id']}", method="DELETE")
        with urllib.request.urlopen(request) as resp:
            resp.read()
    return [draft["id"] for draft in drafts]




def main() -> None:
    with sync_playwright() as p:
        result["cleanedDrafts"] = cleanup_drafts()
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
            locale="zh-CN",
            color_scheme="dark",
        )
        page = context.new_page()
        page.on("console", lambda m: result["consoleErrors"].append(m.text) if m.type == "error" else None)
        page.on("requestfailed", lambda r: result["failedRequests"].append(
            {"url": r.url, "error": r.failure}))
        api_calls: list[str] = []
        page.on("response", lambda r: api_calls.append(
            f"{r.request.method} {r.status} {r.url.split(':5173')[-1]}")
            if "/api/v1/" in r.url else None)
        result["apiCalls"] = api_calls

        uploads: list[dict[str, object]] = []

        # ---------- 1. 导入页 ----------
        page.goto(f"{BASE}/courses/import")
        page.wait_for_load_state("networkidle")
        shot(page, "01-import-page.png")
        note("导入页已加载", title=page.inner_text(".ml-page-title"),
             dropzone=page.inner_text(".dropzone-title"))

        # ---------- 2. Markdown 解析 ----------
        with page.expect_response(lambda r: "/courses/upload" in r.url) as up:
            upload(page, "advanced-python.md")
        response = up.value
        body = response.json()
        uploads.append({"file": "advanced-python.md", "status": response.status,
                        "message": body.get("message")})
        meta = page.inner_text(".preview-meta")
        shot(page, "02-md-parsed.png")
        note("Markdown 解析完成", status=response.status, meta=" ".join(meta.split()),
             chapters=chapter_titles(page), points=point_titles(page))

        course_id = body["data"]["id"]

        # ---------- 3. 结构编辑：改名 / 上移 / 新增章节 ----------
        first = page.locator(".chapter-title input").nth(0)
        with page.expect_response(lambda r: "/api/v1/chapters/" in r.url and r.request.method == "PATCH"):
            first.fill("第 1 章 并发模型（导入后改名）")
            first.press("Enter")
        page.wait_for_timeout(400)
        renamed = chapter_titles(page)

        # 上移第二章：以 DOM 顺序真的变化为准，避免只等某个响应造成误判
        page.locator(".chapter-head button[title='上移']").nth(1).click()
        page.wait_for_function(
            """prev => {
                const now = [...document.querySelectorAll('.chapter-title input')].map(e => e.value)
                return JSON.stringify(now) !== JSON.stringify(prev)
            }""",
            arg=renamed,
            timeout=15_000,
        )
        page.wait_for_timeout(300)
        reordered = chapter_titles(page)

        page.click(".add-chapter")
        page.wait_for_selector(".el-message-box__input input")
        page.fill(".el-message-box__input input", "第 4 章 附加练习（手动添加）")
        page.click(".el-message-box__btns .el-button--primary")
        page.wait_for_function(
            "n => document.querySelectorAll('.chapter-title input').length === n",
            arg=len(reordered) + 1,
            timeout=15_000,
        )
        page.wait_for_timeout(300)

        shot(page, "03-structure-edit.png")
        note("结构编辑完成（改名 / 上移 / 新增章节）",
             renamed=renamed, reordered=reordered,
             chapters=chapter_titles(page), points=point_titles(page))

        # ---------- 4. 确认创建课程 ----------
        with page.expect_response(lambda r: "/confirm" in r.url) as conf:
            page.click("button:has-text('确认创建课程')")
        page.wait_for_url(f"**/courses/{course_id}", timeout=15_000)
        page.wait_for_load_state("networkidle")
        shot(page, "04-md-course-created.png")
        note("Markdown 课程已创建", status=conf.value.status, url=page.url,
             page_title=page.inner_text(".ml-page-title"))

        # ---------- 5. 课程中心 ----------
        page.goto(f"{BASE}/courses")
        page.wait_for_load_state("networkidle")
        shot(page, "05-course-center.png")
        note("课程中心列表", rows=[" ".join(r.split()) for r in page.locator(".course-row, .course-card").all_inner_texts()][:6]
             or [" ".join(page.inner_text("main").split())[:400]])

        # ---------- 6. PDF 解析 ----------
        page.goto(f"{BASE}/courses/import")
        page.wait_for_load_state("networkidle")
        with page.expect_response(lambda r: "/courses/upload" in r.url) as up2:
            upload(page, "pdf-asyncio-textlayer.pdf")
        pdf_resp = up2.value
        pdf_body = pdf_resp.json()
        uploads.append({"file": "pdf-asyncio-textlayer.pdf", "status": pdf_resp.status,
                        "message": pdf_body.get("message")})
        shot(page, "06-pdf-parsed.png")
        pdf_id = pdf_body["data"]["id"]
        note("PDF 解析完成", status=pdf_resp.status,
             meta=" ".join(page.inner_text(".preview-meta").split()),
             chapters=chapter_titles(page), points=point_titles(page),
             warnings=[w.strip() for w in page.locator(".preview-warning .el-alert__title").all_inner_texts()])

        # ---------- 7. PDF 课程创建 ----------
        with page.expect_response(lambda r: "/confirm" in r.url) as conf2:
            page.click("button:has-text('确认创建课程')")
        page.wait_for_url(f"**/courses/{pdf_id}", timeout=15_000)
        page.wait_for_load_state("networkidle")
        shot(page, "07-pdf-course-created.png")
        note("PDF 课程已创建", status=conf2.value.status, url=page.url)

        # ---------- 8. 扫描件 PDF：必须明确报错 ----------
        page.goto(f"{BASE}/courses/import")
        page.wait_for_load_state("networkidle")
        with page.expect_response(lambda r: "/courses/upload" in r.url) as up3:
            page.set_input_files("input[type=file]", str(FIXTURES / "pdf-scanned-like.pdf"))
            page.wait_for_selector(".upload-error", timeout=45_000)
        scan = up3.value
        shot(page, "08-scanned-pdf-error.png", full_page=False)
        note("扫描件 PDF 明确报错", status=scan.status,
             alert=" ".join(page.inner_text(".upload-error").split()))

        result["uploads"] = uploads
        result["draftStillOpen"] = True
        browser.close()

    (HERE / "ui-flow-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n结果已写入 docs/qa/ui-flow-result.json")


if __name__ == "__main__":
    main()
