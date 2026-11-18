"""P1.2 课程管理 / 课程详情 / 学习状态的端到端 UI 验证（Playwright）。

做法：先用真实 API 造一门专属回归课程（教材仍然走 P1.1 的上传解析 + 确认创建），
再用浏览器操作课程中心与课程详情，最后删除这门课程，不影响库里已有的其它课程。

产出：docs/review/p1-2/*.png 与 docs/qa/p12-ui-flow-result.json
运行：python docs/qa/p12_ui_flow.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = "http://127.0.0.1:5173"
API = "http://127.0.0.1:8000/api/v1"
HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
SHOTS = HERE.parent / "review" / "p1-2"
TITLE = "P1.2 UI 回归课程"

result: dict[str, object] = {"steps": [], "consoleErrors": [], "failedRequests": [], "apiCalls": []}


def note(step: str, **extra: object) -> None:
    result["steps"].append({"step": step, **extra})
    print(f"[ok] {step} {extra if extra else ''}")


def shot(page: Page, name: str, full_page: bool = True) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / name), full_page=full_page)


def api(method: str, path: str, payload: dict | None = None) -> tuple[int, object]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(API + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def upload(name: str) -> dict:
    boundary = "----p12uiboundary"
    content = (FIXTURES / name).read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(API + "/courses/upload", data=body, method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(request) as resp:
        return json.loads(resp.read())["data"]


def cleanup() -> list[int]:
    """删掉上次失败运行残留的回归课程。"""
    removed: list[int] = []
    for status in ("active", "draft"):
        _, listing = api("GET", f"/courses?status={status}")
        for course in listing["data"]:
            if course["title"].startswith("P1.2 UI 回归"):
                api("DELETE", f"/courses/{course['id']}")
                removed.append(course["id"])
    return removed


def point_titles(page: Page) -> list[str]:
    return [" ".join(text.split()) for text in page.locator(".point-title").all_inner_texts()]


def chapter_titles(page: Page) -> list[str]:
    return [" ".join(text.split()) for text in page.locator(".chapter-title").all_inner_texts()]


def dialog(page: Page, title: str):
    return page.locator(".el-dialog").filter(has=page.locator(f".el-dialog__title:text-is('{title}')"))


def main() -> None:
    result["cleaned"] = cleanup()

    draft = upload("advanced-python.md")
    course_id = draft["id"]
    api("PATCH", f"/courses/{course_id}", {"title": TITLE, "description": "P1.2 课程管理与知识点管理 UI 回归"})
    api("POST", f"/courses/{course_id}/confirm")
    note("回归课程已创建", courseId=course_id, chapters=draft["chapterCount"])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
            locale="zh-CN",
            color_scheme="dark",
        )
        page = context.new_page()
        page.on("console", lambda m: result["consoleErrors"].append(m.text) if m.type == "error" else None)
        page.on("requestfailed", lambda r: result["failedRequests"].append({"url": r.url, "error": r.failure}))
        page.on(
            "response",
            lambda r: result["apiCalls"].append(f"{r.request.method} {r.status} {r.url.split(':5173')[-1]}")
            if "/api/v1/" in r.url
            else None,
        )

        # ---------- 1. 课程中心 ----------
        page.goto(f"{BASE}/courses")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".course-row")
        shot(page, "01-course-center.png")
        rows = [" ".join(text.split()) for text in page.locator(".course-row").all_inner_texts()]
        note("课程中心列表", rows=len(rows), first=rows[0][:120] if rows else "")

        # 搜索
        page.fill(".search input", "UI 回归")
        page.wait_for_timeout(700)
        page.wait_for_load_state("networkidle")
        filtered = page.locator(".course-row").count()
        shot(page, "02-course-search.png")
        note("搜索课程", matchedRows=filtered)

        page.fill(".search input", "")
        page.wait_for_timeout(700)
        page.wait_for_load_state("networkidle")

        # 排序切换
        page.click(".el-radio-button:has-text('创建时间')")
        page.wait_for_timeout(500)
        page.wait_for_load_state("networkidle")
        created_order = page.locator(".course-row .course-title").all_inner_texts()
        shot(page, "03-course-sort.png")
        note("按创建时间排序", order=[t.strip() for t in created_order][:4])

        # 编辑课程信息
        target_row = page.locator(".course-row").filter(has=page.locator(f".course-title:text-is('{TITLE}')"))
        target_row.locator("button:has-text('编辑')").click()
        page.wait_for_selector(".el-dialog__title:text-is('编辑课程')")
        edit = dialog(page, "编辑课程")
        edit.locator(".el-textarea__inner").fill("P1.2 UI 回归：简介已被编辑")
        edit.locator(".icon-option").nth(1).click()
        shot(page, "04-course-edit-dialog.png", full_page=False)
        with page.expect_response(lambda r: f"/api/v1/courses/{course_id}" in r.url and r.request.method == "PATCH") as patched:
            edit.locator(".el-dialog__footer button:has-text('保存')").click()
        page.wait_for_timeout(600)
        page.wait_for_load_state("networkidle")
        note("编辑课程信息", status=patched.value.status, icon=target_row.locator(".type-badge").inner_text().strip())

        # ---------- 2. 课程详情 ----------
        target_row.locator("button:has-text('继续学习')").click()
        page.wait_for_url(f"**/courses/{course_id}", timeout=15_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".reader-title")
        shot(page, "05-course-detail.png")
        note(
            "课程详情已加载",
            url=page.url,
            progress=page.inner_text(".overview-progress"),
            chapters=len(chapter_titles(page)),
            points=len(point_titles(page)),
            reader=page.inner_text(".reader-title"),
        )

        # 切换知识点
        page.locator(".point-main").nth(1).click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)
        shot(page, "06-point-reading.png")
        note("切换知识点", reader=page.inner_text(".reader-title"), body=page.inner_text(".reader-body")[:80])

        # 设置学习状态：学习中
        before = page.inner_text(".overview-progress")
        with page.expect_response(lambda r: "/status" in r.url and r.request.method == "PATCH") as st:
            page.click(".status-button:has-text('学习中')")
        page.wait_for_timeout(700)
        page.wait_for_load_state("networkidle")
        shot(page, "07-status-in-progress.png")
        note(
            "标记为学习中",
            status=st.value.status,
            progressBefore=before,
            progressAfter=page.inner_text(".overview-progress"),
            counters=" ".join(page.locator(".counters").inner_text().split()),
        )

        # 设置学习状态：待复习 + 已完成
        page.click(".status-button:has-text('待复习')")
        page.wait_for_timeout(600)
        page.wait_for_load_state("networkidle")
        page.click(".status-button:has-text('已完成')")
        page.wait_for_timeout(600)
        page.wait_for_load_state("networkidle")
        shot(page, "08-status-completed.png")
        note("标记为待复习 / 已完成", progress=page.inner_text(".overview-progress"),
             counters=" ".join(page.locator(".counters").inner_text().split()))

        # 新增章节
        page.click(".toc-head button:has-text('新增章节')")
        page.wait_for_selector(".el-dialog__title:text-is('新增章节')")
        chapter_dialog = dialog(page, "新增章节")
        chapter_dialog.locator("input").first.fill("回归附加章节")
        chapter_dialog.locator(".el-textarea__inner").fill("由 UI 回归脚本创建的章节")
        shot(page, "09-add-chapter-dialog.png", full_page=False)
        with page.expect_response(lambda r: "/chapters" in r.url and r.request.method == "POST") as added:
            chapter_dialog.locator(".el-dialog__footer button:has-text('添加')").click()
        page.wait_for_timeout(700)
        page.wait_for_load_state("networkidle")
        note("新增章节", status=added.value.status, chapters=chapter_titles(page)[-2:])

        # 章节改名
        last_chapter = page.locator(".toc-chapter").last
        last_chapter.locator(".row-tools button").nth(3).click()
        page.wait_for_selector(".el-dialog__title:text-is('编辑章节')")
        rename_dialog = dialog(page, "编辑章节")
        rename_dialog.locator("input").first.fill("回归附加章节（已改名）")
        with page.expect_response(lambda r: "/chapters/" in r.url and r.request.method == "PATCH") as renamed:
            rename_dialog.locator(".el-dialog__footer button:has-text('保存')").click()
        page.wait_for_timeout(600)
        page.wait_for_load_state("networkidle")
        note("章节改名", status=renamed.value.status, chapters=chapter_titles(page)[-2:])

        # 新增知识点（带 Markdown 正文）
        page.locator(".toc-chapter").last.locator(".row-tools button").nth(2).click()
        page.wait_for_selector(".el-dialog__title:text-is('新增知识点')")
        point_dialog = dialog(page, "新增知识点")
        point_dialog.locator("input").first.fill("回归知识点（Markdown）")
        point_dialog.locator(".el-textarea__inner").first.fill("由脚本创建的简介")
        point_dialog.locator(".content-input textarea").fill(
            "## 小标题\n\n- 列表项一\n- 列表项二\n\n```python\nprint('hello mastery lab')\n```\n\n> 引用块\n\n| 列 A | 列 B |\n| --- | --- |\n| 1 | 2 |\n"
        )
        point_dialog.locator(".editor-tabs button:has-text('预览')").click()
        shot(page, "10-point-editor-preview.png", full_page=False)
        with page.expect_response(lambda r: "knowledge-points" in r.url and r.request.method == "POST") as pt_added:
            point_dialog.locator(".el-dialog__footer button:has-text('添加')").click()
        page.wait_for_timeout(900)
        page.wait_for_load_state("networkidle")
        shot(page, "11-markdown-rendered.png")
        note(
            "新增知识点并渲染 Markdown",
            status=pt_added.value.status,
            reader=page.inner_text(".reader-title"),
            hasCode=page.locator(".reader-body .md-code").count(),
            hasTable=page.locator(".reader-body table").count(),
            hasQuote=page.locator(".reader-body blockquote").count(),
        )

        # 调整知识点顺序（把第一个章节的第 2 个知识点上移）→ 刷新验证持久化
        page.locator(".toc-chapter").first.locator(".point-row").nth(1).locator(".row-tools button").first.click()
        page.wait_for_timeout(700)
        page.wait_for_load_state("networkidle")
        order_before = point_titles(page)
        shot(page, "12-point-reordered.png")
        page.reload()
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".reader-title")
        order_after = point_titles(page)
        note("知识点排序并刷新验证", before=order_before, after=order_after, stable=order_before == order_after)

        # 刷新后学习状态仍在
        statuses = [" ".join(t.split()) for t in page.locator(".point-status").all_inner_texts()]
        note("刷新后学习状态仍在", statuses=statuses[:6])

        # ---------- 3. 删除章节 ----------
        chapters_before = len(chapter_titles(page))
        page.locator(".toc-chapter").last.locator(".row-tools button").nth(4).click()
        page.wait_for_selector(".el-message-box")
        shot(page, "13-delete-confirm.png", full_page=False)
        with page.expect_response(lambda r: "/chapters/" in r.url and r.request.method == "DELETE") as del_resp:
            page.click(".el-message-box__btns .el-button--primary")
        page.wait_for_timeout(700)
        page.wait_for_load_state("networkidle")
        note("删除章节（含确认）", status=del_resp.value.status,
             chaptersBefore=chapters_before, chaptersAfter=len(chapter_titles(page)))

        # ---------- 4. 回到课程中心看进度 ----------
        page.goto(f"{BASE}/courses")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".course-row")
        shot(page, "14-course-center-after.png")
        row_text = " ".join(
            page.locator(".course-row").filter(has=page.locator(f".course-title:text-is('{TITLE}')")).inner_text().split()
        )
        note("课程中心显示最新进度", row=row_text[:200])

        result["consoleErrors"] = [e for e in result["consoleErrors"] if "favicon" not in e]
        browser.close()

    # 清理本轮的回归课程
    api("DELETE", f"/courses/{course_id}")
    remaining = api("GET", "/courses")[1]["data"]
    result["cleanup"] = {
        "deletedCourse": course_id,
        "remainingCourses": [c["title"] for c in remaining],
    }
    note("回归课程已清理", remaining=result["cleanup"]["remainingCourses"])

    (HERE / "p12-ui-flow-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n结果已写入 docs/qa/p12-ui-flow-result.json")


if __name__ == "__main__":
    main()
