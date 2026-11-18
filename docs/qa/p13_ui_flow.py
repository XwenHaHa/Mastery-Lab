"""Playwright real-model classroom acceptance after p13_real_check.py --keep-course."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import urllib.request

from playwright.sync_api import sync_playwright, expect

HERE = Path(__file__).parent
BASE = "http://127.0.0.1:5173"
SHOTS = HERE.parent / "review/p1-3"
seed = json.loads((HERE / "p13-real-result.json").read_text(encoding="utf-8"))
course_id = seed["courseId"]
report = {"kind": "real-browser-and-configured-model", "startedAt": datetime.now(timezone.utc).isoformat(), "steps": [], "pageErrors": []}
MOCK = False


def note(name):
    report["steps"].append({"name": name, "passed": True})
    print(f"[PASS] {name}", flush=True)


def screenshot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    if MOCK:
        name = "mock-" + name
    page.screenshot(path=str(SHOTS / name))


def idle(page):
    page.wait_for_function("() => ![...document.querySelectorAll('button')].some(button => button.textContent.includes('停止生成'))", timeout=180000)
    expect(page.get_by_role("button", name="解释这段代码", exact=True)).to_be_enabled(timeout=10000)


def api(method, path, body=None):
    request = urllib.request.Request("http://127.0.0.1:8000/api/v1" + path, method=method,
        data=json.dumps(body).encode() if body else None, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["data"]


def main(model_id=None):
    course = api("GET", f"/courses/{course_id}")
    assert course["title"].startswith("P1.3 教学验收") and course["sourceName"] == "p13-python.md"
    chapter_id = course["chapters"][0]["id"]
    for point in course["chapters"][0]["knowledgePoints"]:
        if point["title"] == "条件判断":
            api("DELETE", f"/courses/{course_id}/knowledge-points/{point['id']}")
    api("POST", f"/courses/{course_id}/chapters/{chapter_id}/knowledge-points", {
        "title": "条件判断", "content": '根据库存判断能否借书。if 后面写条件，分支内部缩进。\n```python\nstock = 3\nif stock > 0:\n    print("可以借书")\nelse:\n    print("暂无库存")\n```\n预期输出 可以借书。冒号和缩进不能省略。',
    })
    if model_id:
        course = api("GET", f"/courses/{course_id}")
        for chapter in course["chapters"]:
            for point in chapter["knowledgePoints"]:
                api("POST", "/classroom/sessions", {"courseId": course_id, "knowledgePointId": point["id"], "modelConfigId": model_id})
    first_session = api("POST", "/classroom/sessions", {"courseId": course_id, "knowledgePointId": course["chapters"][0]["knowledgePoints"][0]["id"]})
    first_answers = sum(message["role"] == "assistant" for message in first_session["messages"])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda error: report["pageErrors"].append(str(error)))
        try:
            page.goto(f"{BASE}/courses/{course_id}", wait_until="networkidle")
            page.get_by_role("button", name="开始学习", exact=True).click()
            expect(page.locator(".stage-title h1")).to_have_text("变量与赋值")
            expect(page.locator(".turn.assistant")).to_have_count(first_answers)
            screenshot(page, "01-classroom-restored-dark.png")
            note("course detail enters classroom and restores correct course/point/history")

            page.get_by_role("button", name="收起学习信息", exact=True).click()
            expect(page.locator(".info")).to_have_count(0)
            page.get_by_role("button", name="展开学习信息", exact=True).click()
            expect(page.locator(".info")).to_be_visible()
            note("information panel collapses and expands")

            page.locator(".point-row").filter(has_text="条件判断").click()
            expect(page.locator(".stage-title h1")).to_have_text("条件判断")
            expect(page.get_by_role("button", name="停止生成", exact=True)).to_be_visible(timeout=15000)
            page.wait_for_function("() => document.querySelector('.turn.assistant .turn-body')?.textContent.length > 30", timeout=90000)
            screenshot(page, "02-real-streaming.png")
            note("new point proactively streams teaching without a user question")
            page.get_by_role("button", name="停止生成", exact=True).click()
            idle(page)
            expect(page.locator(".turn-flag").filter(has_text="已停止")).to_be_visible()
            before = page.locator(".turn-body").all_text_contents()
            page.reload(wait_until="networkidle")
            expect(page.locator(".turn-flag").filter(has_text="已停止")).to_be_visible()
            assert page.locator(".turn-body").all_text_contents() == before
            screenshot(page, "03-stopped-restored.png")
            note("stop retains partial answer and refresh restores exactly")

            composer = page.get_by_role("textbox", name="向 AI 老师提问")
            composer.fill("请展示当前条件判断的完整案例，解释每句代码和预期输出。")
            composer.press("Shift+Enter")
            assert "\n" in composer.input_value()
            composer.press("Enter")
            expect(page.get_by_role("button", name="停止生成", exact=True)).to_be_visible()
            idle(page)
            expect(page.locator(".turn.assistant").last.locator("pre code").first).to_be_visible()
            screenshot(page, "04-code-example.png")
            note("Enter sends, Shift+Enter inserts newline, example renders highlighted code")

            previous = page.locator(".turn.assistant").count()
            page.get_by_role("button", name="解释这段代码", exact=True).click()
            expect(page.get_by_role("button", name="停止生成", exact=True)).to_be_visible()
            idle(page)
            expect(page.locator(".turn.assistant")).to_have_count(previous + 1)
            assert "stock" in page.locator(".turn.assistant").last.inner_text()
            screenshot(page, "05-contextual-code-explanation.png")
            note("quick action calls configured model and references previous code")

            page.get_by_role("button", name="我有一个问题", exact=True).click()
            expect(composer).to_be_focused()
            composer.fill("只用一小段话说明 if 判断中的大于号，并用 $stock > 0$ 数学公式展示它。")
            composer.press("Enter")
            expect(page.get_by_role("button", name="停止生成", exact=True)).to_be_visible()
            idle(page)
            expect(page.locator(".turn.assistant").last.locator(".katex").first).to_be_visible()
            screenshot(page, "06-math-rendering.png")
            note("free question renders model math using KaTeX")

            page.locator(".point-row").filter(has_text="变量与赋值").click()
            expect(page.locator(".stage-title h1")).to_have_text("变量与赋值")
            expect(page.locator(".turn.assistant")).to_have_count(first_answers)
            note("switch restores isolated conversation without repeating initial lesson")

            page.evaluate("document.documentElement.classList.remove('dark'); document.documentElement.dataset.theme = 'light'")
            screenshot(page, "07-classroom-light.png")
            page.set_viewport_size({"width": 900, "height": 900})
            page.get_by_role("button", name="收起学习信息", exact=True).click()
            if page.locator(".catalog.open").count():
                page.get_by_role("button", name="关闭课程目录", exact=True).click(position={"x": 700, "y": 400})
            page.get_by_role("button", name="打开课程目录", exact=True).click()
            expect(page.locator(".catalog.open")).to_be_visible()
            page.get_by_role("button", name="关闭课程目录", exact=True).click(position={"x": 700, "y": 400})
            screenshot(page, "08-narrow-layout.png")
            note("light theme and narrow-screen catalog collapse")

            page.set_viewport_size({"width": 1440, "height": 900})
            page.get_by_role("textbox", name="向 AI 老师提问").fill("请再解释一遍变量，使用生活例子。")
            page.get_by_role("textbox", name="向 AI 老师提问").press("Enter")
            expect(page.get_by_role("button", name="停止生成", exact=True)).to_be_visible()
            page.locator(".point-row").filter(has_text="列表与索引").click()
            expect(page.locator(".stage-title h1")).to_have_text("列表与索引")
            expect(page.get_by_role("button", name="解释这段代码", exact=True)).to_be_enabled()
            page.get_by_role("textbox", name="向 AI 老师提问").fill("只用一句话回答：books 的第一个索引是多少？")
            page.get_by_role("textbox", name="向 AI 老师提问").press("Enter")
            expect(page.get_by_role("button", name="停止生成", exact=True)).to_be_visible()
            idle(page)
            assert "0" in page.locator(".turn.assistant").last.inner_text()
            note("switch during generation does not contaminate next point or clear its active stream")

            page.route("**/classroom/sessions/*/messages", lambda route: route.fulfill(status=200, content_type="text/event-stream", body='event: error\ndata: {"message":"模型限流测试（模拟）","httpStatus":429}\n\n'))
            composer.fill("测试错误提示")
            composer.press("Enter")
            expect(page.locator(".stream-error")).to_contain_text("模型限流测试（模拟）")
            screenshot(page, "09-model-error-simulated.png")
            page.unroute("**/classroom/sessions/*/messages")
            note("simulated upstream error is shown clearly without unhandled exceptions")

            assert not report["pageErrors"], report["pageErrors"]
            report["passed"] = True
        except Exception as error:
            report["passed"] = False
            report["failure"] = str(error)[:1200]
            screenshot(page, "failure.png")
            raise
        finally:
            (HERE / ("p13-ui-mock-result.json" if MOCK else "p13-ui-result.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true")
    MOCK = parser.parse_args().mock
    if MOCK:
        from p13_mock_gateway import start
        gateway = start()
        report["kind"] = "browser-with-local-simulated-upstream"
        model = api("POST", "/models", {"name": f"P1.3 QA mock {gateway.server_port}", "baseUrl": f"http://127.0.0.1:{gateway.server_port}/v1", "modelName": "qa-simulated", "apiKey": "qa-not-a-real-secret", "isDefault": False})
        try:
            main(model["id"])
        finally:
            api("DELETE", f"/models/{model['id']}")
            gateway.shutdown()
            gateway.server_close()
    else:
        main()
