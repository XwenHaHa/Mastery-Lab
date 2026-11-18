"""Classroom status regression with isolated, explicitly simulated API responses."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

HERE = Path(__file__).parent
BASE = "http://127.0.0.1:5173"
SHOTS = HERE.parent / "review/p1-3"
REPORT = {"kind": "browser-with-isolated-mocked-api", "startedAt": datetime.now(timezone.utc).isoformat(), "steps": [], "pageErrors": []}


def note(name):
    REPORT["steps"].append({"name": name, "passed": True})
    print(f"[PASS] {name}", flush=True)


class ClassroomFixture:
    def __init__(self):
        self.statuses = {801: ["not_started", "not_started"], 802: ["not_started", "not_started"]}
        self.patches = []
        self.pending = []
        self.delay = False
        self.fail = False
        self.stale_session = None
        self.unexpected = []
        self.streaming = False

    def course(self, course_id):
        statuses = self.statuses[course_id]
        counts = {"total": 2, "notStarted": statuses.count("not_started"), "inProgress": statuses.count("in_progress"), "review": 0, "completed": statuses.count("completed")}
        progress = round(sum({"not_started": 0, "in_progress": 0.4, "completed": 1}[status] for status in statuses) * 50)
        points = [{"id": course_id * 10 + index, "chapterId": course_id, "title": title, "description": "隔离测试知识点", "contentLength": 20, "sortOrder": index, "codeCount": 1, "masteryLevel": 0, "learningStatus": statuses[index], "lastStudiedAt": None} for index, title in enumerate(["变量与赋值", "列表与索引"])]
        return {"id": course_id, "title": f"状态交互隔离测试 {course_id}", "description": "不写入真实课程", "status": "active", "icon": "", "sourceType": "markdown", "sourceName": "status-fixture.md", "sourceBytes": 100, "chapterCount": 1, "knowledgePointCount": 2, "codeCount": 2, "progress": progress, "statusCounts": counts, "lastStudiedAt": None, "createdAt": "2026-11-17T08:00:00Z", "updatedAt": "2026-11-17T08:00:00Z", "warnings": [], "stats": {}, "chapters": [{"id": course_id, "courseId": course_id, "title": "Python 基础", "description": "", "sortOrder": 0, "codeCount": 2, "knowledgePoints": points, "statusCounts": counts, "progress": progress}]}

    def session(self, point_id):
        course_id, index = divmod(point_id, 10)
        course = self.course(course_id)
        point = deepcopy(course["chapters"][0]["knowledgePoints"][index])
        point.update(chapterTitle="Python 基础", previousId=point_id - 1 if index else None, nextId=point_id + 1 if not index else None)
        course["learnedCount"] = 2 - course["statusCounts"]["notStarted"]
        return {"id": point_id, "course": course, "point": point, "model": None, "messages": [{"id": point_id, "role": "assistant", "content": "【模拟历史】这段讲解和代码不应因为标记完成而丢失。\n\n```python\nprice = 37\nprint(price)\n```", "status": "completed", "modelName": "fixture", "errorMessage": "", "createdAt": "2026-11-17T08:00:00Z"}], "streaming": self.streaming, "createdAt": "2026-11-17T08:00:00Z", "updatedAt": "2026-11-17T08:00:00Z", "lastMessageAt": "2026-11-17T08:00:00Z"}

    def reply(self, route, data, status=200):
        route.fulfill(status=status, json={"code": 0 if status == 200 else status, "message": "模拟保存失败，请重试" if status != 200 else "ok", "data": data})

    def release(self):
        route, data = self.pending.pop(0)
        self.reply(route, data)

    def route(self, route):
        request = route.request
        path = urlparse(request.url).path.removeprefix("/api/v1")
        if request.method == "GET" and path == "/models":
            return self.reply(route, [])
        if request.method == "GET" and re.fullmatch(r"/courses/80[12]", path):
            return self.reply(route, self.course(int(path.split("/")[-1])))
        if request.method == "POST" and path == "/classroom/sessions":
            return self.reply(route, self.session(request.post_data_json["knowledgePointId"]))
        if request.method == "GET" and re.fullmatch(r"/classroom/sessions/\d+", path):
            data = self.stale_session or self.session(int(path.split("/")[-1]))
            if self.stale_session:
                self.pending.append((route, data))
                self.stale_session = None
                return
            return self.reply(route, data)
        match = re.fullmatch(r"/courses/(\d+)/knowledge-points/(\d+)/status", path)
        if request.method == "PATCH" and match:
            course_id, point_id = map(int, match.groups())
            status = request.post_data_json["status"]
            self.patches.append((course_id, point_id, status))
            if self.fail:
                return self.reply(route, None, 503)
            self.statuses[course_id][point_id % 10] = status
            if self.delay:
                self.pending.append((route, self.course(course_id)))
                return
            return self.reply(route, self.course(course_id))
        self.unexpected.append(f"{request.method} {path}")
        self.reply(route, None, 500)


def main():
    fixture = ClassroomFixture()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.route("**/api/v1/**", fixture.route)
        page = context.new_page()
        page.on("pageerror", lambda error: REPORT["pageErrors"].append(str(error)))
        complete = page.get_by_role("button", name="标记为已完成", exact=True)
        resume = page.get_by_role("button", name="改为学习中", exact=True)
        badge = page.locator(".stage-actions .ml-status")
        draft = page.get_by_role("textbox", name="向 AI 老师提问")
        try:
            page.goto(f"{BASE}/courses/801/classroom?point=8010", wait_until="networkidle")
            expect(page.locator(".stage-title h1")).to_have_text("变量与赋值")
            expect(complete).to_be_visible(timeout=5000)
            before = page.locator(".turn-body").all_text_contents()
            draft.fill("这段代码我还想继续问")
            complete.click()
            expect(badge).to_have_text("已完成")
            expect(page.locator(".point-row.active .point-dot")).to_have_class(re.compile("is-completed"))
            expect(page.locator(".catalog-progress > span")).to_have_text("50%")
            expect(page.locator(".info-progress > span")).to_have_text("50%")
            expect(page.locator(".info-stats dt").first).to_have_text("1")
            expect(draft).to_have_value("这段代码我还想继续问")
            assert page.locator(".turn-body").all_text_contents() == before
            assert page.url.endswith("?point=8010")
            assert fixture.patches == [(801, 8010, "completed")]
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / "status-completed-mock.png"))
            note("mark completed without navigation or losing transcript/draft; synchronize catalog/progress/counts")

            page.reload(wait_until="networkidle")
            expect(badge).to_have_text("已完成")
            assert page.locator(".turn-body").all_text_contents() == before
            resume.click()
            expect(badge).to_have_text("学习中")
            expect(page.locator(".catalog-progress > span")).to_have_text("20%")
            expect(page.locator(".info-progress > span")).to_have_text("20%")
            expect(page.locator(".point-row.active .point-dot")).to_have_class(re.compile("is-in-progress"))
            note("reload keeps completion/history; explicit resume restores weighted progress")

            fixture.fail = True
            complete.click()
            expect(page.get_by_role("alert").filter(has_text="模拟保存失败")).to_be_visible()
            expect(badge).to_have_text("学习中")
            expect(complete).to_be_enabled()
            expect(page.locator(".catalog-progress > span")).to_have_text("20%")
            fixture.fail = False
            complete.click()
            expect(badge).to_have_text("已完成")
            expect(page.get_by_role("alert").filter(has_text="模拟保存失败")).to_have_count(0)
            note("failed save preserves status and progress; retry succeeds without replacing conversation")

            fixture.delay = True
            patch_count = len(fixture.patches)
            resume.click()
            expect(resume).to_be_disabled()
            resume.evaluate("button => button.click()")
            expect(badge).to_have_text("已完成")
            assert len(fixture.patches) == patch_count + 1
            page.get_by_role("button", name="下一个知识点", exact=True).click()
            expect(page.locator(".stage-title h1")).to_have_text("列表与索引")
            fixture.release()
            expect(badge).to_have_text("未学习")
            expect(page.locator(".point-row").first.locator(".point-state")).to_have_text("学习中")
            expect(page.locator(".catalog-progress > span")).to_have_text("20%")
            expect(complete).to_be_enabled()
            note("pending save prevents duplicate submissions and only changes its original point after navigation")

            complete.click()
            expect(complete).to_be_disabled()
            page.evaluate("() => { history.pushState({}, '', '/courses/802/classroom?point=8020'); dispatchEvent(new PopStateEvent('popstate')); }")
            expect(page.locator(".catalog-title")).to_contain_text("802")
            expect(complete).to_be_enabled()
            complete.click()
            expect(complete).to_be_disabled()
            fixture.release()
            expect(page.locator(".catalog-title")).to_contain_text("802")
            expect(badge).to_have_text("未学习")
            expect(page.locator(".catalog-progress > span")).to_have_text("0%")
            expect(complete).to_be_disabled()
            fixture.release()
            expect(badge).to_have_text("已完成")
            expect(resume).to_be_enabled()
            note("previous-course response cannot overwrite current course or clear its pending save")

            fixture.delay = False
            fixture.streaming = True
            fixture.stale_session = fixture.session(8020)
            fixture.stale_session["streaming"] = False
            page.reload(wait_until="domcontentloaded")
            expect(resume).to_be_enabled()
            expect(page.get_by_role("button", name="停止生成", exact=True)).to_be_visible()
            page.wait_for_timeout(650)
            assert len(fixture.pending) == 1
            resume.click()
            expect(badge).to_have_text("学习中")
            fixture.streaming = False
            fixture.release()
            expect(page.get_by_role("button", name="停止生成", exact=True)).to_have_count(0)
            expect(badge).to_have_text("学习中")
            expect(page.locator(".catalog-progress > span")).to_have_text("20%")
            expect(page.locator(".info-progress > span")).to_have_text("20%")
            assert page.locator(".turn-body").all_text_contents() == before
            note("status can change while generating; stale stream-recovery snapshot cannot undo saved progress")

            page.get_by_role("button", name="收起学习信息", exact=True).click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.reload(wait_until="networkidle")
            expect(complete).to_be_visible()
            complete.click()
            expect(badge).to_have_text("已完成")
            expect(resume).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            bounds = resume.bounding_box()
            assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 390
            page.screenshot(path=str(SHOTS / "status-narrow-mock.png"))
            note("completion and resume remain accessible at narrow width with the information panel closed")

            assert not fixture.unexpected, fixture.unexpected
            assert not REPORT["pageErrors"], REPORT["pageErrors"]
            note("no unexpected API/model requests and no browser runtime errors")
            REPORT["passed"] = True
        except Exception as error:
            REPORT["passed"] = False
            REPORT["error"] = str(error)
            raise
        finally:
            REPORT["finishedAt"] = datetime.now(timezone.utc).isoformat()
            REPORT["statusRequests"] = fixture.patches
            REPORT["unexpectedRequests"] = fixture.unexpected
            (HERE / "classroom-status-ui-result.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
            browser.close()


if __name__ == "__main__":
    main()
