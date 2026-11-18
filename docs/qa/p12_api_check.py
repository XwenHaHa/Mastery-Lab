"""P1.2 后端验收回归（真实 SQLite + 真实 HTTP，不 mock）。

覆盖任务书「十、测试要求」的 12 项：课程中心数据、详情、章节 CRUD、章节排序、
知识点 CRUD、知识点排序、学习状态、进度统计、刷新后持久化、删除课程的数据处理，
以及 P0 模型配置与 P1.1 教材导入/解析的回归。

前置：后端已在 127.0.0.1:8000 运行。
运行：python docs/qa/p12_api_check.py
产出：docs/qa/p12-api-result.json（含每条断言的通过情况与关键响应片段）
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API = "http://127.0.0.1:8000/api/v1"
HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
DB = HERE.parent.parent / "data" / "mastery_lab.db"
RESULT_PATH = HERE / "p12-api-result.json"
TITLE_MARK = "P1.2 回归"

results: list[dict[str, Any]] = []
notes: list[str] = []

# 进度权重：与 apps/api/app/services/learning.py 保持一致，这里独立算一遍做交叉验证
WEIGHTS = {"not_started": 0.0, "in_progress": 0.4, "review": 0.7, "completed": 1.0}
# 响应里 statusCounts 是 camelCase，映射一下再算
CAMEL_KEYS = {"not_started": "notStarted", "in_progress": "inProgress", "review": "review", "completed": "completed"}


def check(name: str, ok: bool, detail: Any = None) -> bool:
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail is not None and not ok else ""))
    return ok


def http(method: str, path: str, payload: dict | None = None, *, expect: int | None = None) -> tuple[int, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    # 查询串里可能出现中文关键词，这里统一做百分号编码
    url = API + urllib.parse.quote(path, safe="/?=&%")
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as resp:
            status, body = resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        status, body = exc.code, json.loads(exc.read() or b"{}")
    if expect is not None and status != expect:
        raise AssertionError(f"{method} {path} 期望 {expect} 实际 {status}: {body}")
    return status, body


def upload(name: str) -> tuple[int, Any]:
    boundary = "----p12boundary"
    content = (FIXTURES / name).read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(API + "/courses/upload", data=body, method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(request) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def expected_progress(counts: dict[str, int]) -> int:
    total = counts["total"]
    if not total:
        return 0
    weighted = sum(WEIGHTS[key] * counts[CAMEL_KEYS[key]] for key in WEIGHTS)
    return int(round(weighted * 100 / total))


def db_rows(sql: str, args: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def point_ids(chapters: list[dict], chapter_id: int) -> list[int]:
    for chapter in chapters:
        if chapter["id"] == chapter_id:
            return [point["id"] for point in chapter["knowledgePoints"]]
    return []


def cleanup() -> None:
    """清掉上次失败运行残留的回归课程，保证起点一致。"""
    for status in ("active", "draft"):
        _, body = http("GET", f"/courses?status={status}")
        for course in body["data"]:
            if course["title"].startswith(TITLE_MARK):
                http("DELETE", f"/courses/{course['id']}")


def main() -> None:
    cleanup()

    # ---------- 0. 基线：P0 + P1.1 仍然可用 ----------
    status, health = http("GET", "/health")
    check("P0 健康检查可用", status == 200 and health["data"]["database"]["ok"], health["data"]["status"])

    _, models = http("GET", "/models")
    check("P0 模型配置列表可读", isinstance(models["data"], list), len(models["data"]))

    created_model_id = None
    status, body = http(
        "POST",
        "/models",
        {"name": "P1.2 回归配置", "baseUrl": "http://127.0.0.1:9/v1", "modelName": "gpt-x", "apiKey": "sk-regression", "isDefault": False},
        expect=201,
    )
    created_model_id = body["data"]["id"]
    check(
        "P0 模型配置可新建且不回传明文 Key",
        "sk-regression" not in json.dumps(body) and body["data"]["apiKeyHint"] == "****",
        body["data"]["apiKeyHint"],
    )
    status, body = http("PUT", f"/models/{created_model_id}", {"modelName": "gpt-y"}, expect=200)
    check("P0 模型配置可修改", body["data"]["modelName"] == "gpt-y", body["data"]["modelName"])
    http("DELETE", f"/models/{created_model_id}", expect=200)
    check("P0 模型配置可删除", True)

    # ---------- 1. 导入教材 → 草稿（P1.1 回归） ----------
    status, uploaded = upload("advanced-python.md")
    draft = uploaded["data"]
    course_id = draft["id"]
    check("P1.1 Markdown 上传解析成功", status == 201 and draft["chapterCount"] > 0, f"{draft['chapterCount']} 章")
    check(
        "P1.1 解析出的知识点正文仍保存在库（目录不回传正文）",
        all("content" not in point for point in draft["chapters"][0]["knowledgePoints"]),
        list(draft["chapters"][0]["knowledgePoints"][0].keys()),
    )

    status, pdf = upload("pdf-asyncio-textlayer.pdf")
    check("P1.1 PDF 文本层解析仍可用", status == 201 and pdf["data"]["sourceType"] == "pdf", pdf["data"]["chapterCount"])
    http("DELETE", f"/courses/{pdf['data']['id']}", expect=200)

    status, scanned = upload("pdf-scanned-like.pdf")
    check("P1.1 扫描版 PDF 仍然明确报错", status == 422, scanned.get("message"))

    # ---------- 2. 编辑课程信息 ----------
    status, body = http(
        "PATCH",
        f"/courses/{course_id}",
        {"title": f"{TITLE_MARK}课程", "description": "P1.2 课程管理回归用课程", "icon": "🐍"},
        expect=200,
    )
    course = body["data"]
    check("课程名称/简介/图标可修改", course["title"] == f"{TITLE_MARK}课程" and course["icon"] == "🐍", course["title"])

    status, body = http("POST", f"/courses/{course_id}/confirm", expect=200)
    check("确认后课程进入课程中心", body["data"]["status"] == "active", body["data"]["status"])

    # ---------- 3. 课程列表：搜索与排序 ----------
    _, body = http("GET", "/courses")
    titles = [item["title"] for item in body["data"]]
    check("课程出现在列表里", f"{TITLE_MARK}课程" in titles, titles)

    _, body = http("GET", "/courses?sort=studied")
    check("按最近学习排序可用", isinstance(body["data"], list), len(body["data"]))
    _, body = http("GET", "/courses?sort=created")
    created_order = [item["createdAt"] for item in body["data"]]
    check("按创建时间排序（倒序）正确", created_order == sorted(created_order, reverse=True), created_order[:3])
    _, body = http("GET", "/courses?q=zzz-不存在-zzz")
    check("搜索无结果时返回空列表", body["data"] == [], len(body["data"]))

    # ---------- 4. 新增/修改章节 ----------
    _, body = http("POST", f"/courses/{course_id}/chapters", {"title": "回归章节 A"}, expect=200)
    chapter_a = body["data"]["chapters"][-1]
    _, body = http("POST", f"/courses/{course_id}/chapters", {"title": "回归章节 B"}, expect=200)
    chapter_b = body["data"]["chapters"][-1]
    check("新增章节追加到末尾", [c["title"] for c in body["data"]["chapters"]][-2:] == ["回归章节 A", "回归章节 B"], chapter_b["title"])

    _, body = http("PATCH", f"/courses/{course_id}/chapters/{chapter_a['id']}", {"title": "回归章节 A（改名）", "description": "章节简介"}, expect=200)
    renamed = [c for c in body["data"]["chapters"] if c["id"] == chapter_a["id"]][0]
    check("章节名称/简介可修改", renamed["title"] == "回归章节 A（改名）" and renamed["description"] == "章节简介", renamed["title"])

    _, body = http("GET", f"/courses/{course_id}/chapters")
    check("获取课程章节接口可用", len(body["data"]) >= 2, len(body["data"]))

    # ---------- 5. 章节排序（持久化） ----------
    ids = [c["id"] for c in body["data"]]
    reversed_ids = list(reversed(ids))
    _, body = http("PATCH", f"/courses/{course_id}/chapters/reorder", {"ids": reversed_ids}, expect=200)
    new_order = [c["id"] for c in body["data"]["chapters"]]
    _, recheck = http("GET", f"/courses/{course_id}")
    persisted_order = [c["id"] for c in recheck["data"]["chapters"]]
    check("章节排序生效并持久化", new_order == reversed_ids and persisted_order == reversed_ids, persisted_order[:5])

    status, bad = http("PATCH", f"/courses/{course_id}/chapters/reorder", {"ids": reversed_ids[:-1]})
    check("章节排序拒绝不完整 ID 列表", status == 422, bad.get("message"))
    status, bad = http("PATCH", f"/courses/{course_id}/chapters/reorder", {"ids": [reversed_ids[0]] * len(reversed_ids)})
    check("章节排序拒绝重复 ID", status == 422, bad.get("message"))

    # ---------- 6. 知识点 CRUD + 排序 ----------
    _, body = http(
        "POST",
        f"/courses/{course_id}/chapters/{chapter_a['id']}/knowledge-points",
        {"title": "回归知识点 1", "description": "简介 1", "content": "# 标题\n\n正文 **加粗**\n\n```python\nprint(1)\n```"},
        expect=200,
    )
    point_1 = [
        p for c in body["data"]["chapters"] if c["id"] == chapter_a["id"] for p in c["knowledgePoints"]
    ][-1]
    check("新增知识点成功", point_1["title"] == "回归知识点 1", point_1["title"])

    for index in (2, 3):
        http(
            "POST",
            f"/courses/{course_id}/chapters/{chapter_a['id']}/knowledge-points",
            {"title": f"回归知识点 {index}"},
            expect=200,
        )
    _, body = http("GET", f"/courses/{course_id}")
    ids_a = point_ids(body["data"]["chapters"], chapter_a["id"])
    check("章节下知识点数量正确", len(ids_a) == 3, len(ids_a))

    _, body = http(
        "PATCH",
        f"/courses/{course_id}/knowledge-points/{point_1['id']}",
        {"title": "回归知识点 1（改名）", "description": "新简介", "content": "# 改过的正文\n\n- 一\n- 二\n"},
        expect=200,
    )
    _, detail = http("GET", f"/knowledge-points/{point_1['id']}")
    check(
        "知识点名称/简介/正文可修改且正文落库",
        detail["data"]["title"] == "回归知识点 1（改名）" and "改过的正文" in detail["data"]["content"],
        detail["data"]["title"],
    )
    check(
        "知识点详情带来源章节与前后邻居",
        detail["data"]["chapterId"] == chapter_a["id"] and detail["data"]["nextId"] == ids_a[1],
        {"chapterId": detail["data"]["chapterId"], "nextId": detail["data"]["nextId"]},
    )

    _, body = http(
        "PATCH",
        f"/courses/{course_id}/chapters/{chapter_a['id']}/knowledge-points/reorder",
        {"ids": list(reversed(ids_a))},
        expect=200,
    )
    _, recheck = http("GET", f"/courses/{course_id}")
    check(
        "知识点排序生效并持久化",
        point_ids(recheck["data"]["chapters"], chapter_a["id"]) == list(reversed(ids_a)),
        point_ids(recheck["data"]["chapters"], chapter_a["id"]),
    )
    status, bad = http(
        "PATCH", f"/courses/{course_id}/chapters/{chapter_a['id']}/knowledge-points/reorder", {"ids": ids_a[:-1]}
    )
    check("知识点排序拒绝不完整 ID 列表", status == 422, bad.get("message"))

    # ---------- 7. 学习状态与进度 ----------
    first_point = list(reversed(ids_a))[0]
    status, body = http("PATCH", f"/courses/{course_id}/knowledge-points/{first_point}/status", {"status": "in_progress"}, expect=200)
    counts = body["data"]["statusCounts"]
    check("学习状态可改为 in_progress", counts["inProgress"] == 1, counts)

    status, body = http("PATCH", f"/courses/{course_id}/knowledge-points/{ids_a[0]}/status", {"status": "completed"}, expect=409)
    check("P1.4 未验证不能手工完成", status == 409)
    http("PATCH", f"/courses/{course_id}/knowledge-points/{ids_a[0]}/status", {"status": "review"}, expect=200)
    _, body = http("PATCH", f"/courses/{course_id}/knowledge-points/{ids_a[1]}/status", {"status": "review"}, expect=200)
    counts = body["data"]["statusCounts"]
    check("学习中和待复习写入，完成保留验证门槛", (counts["inProgress"], counts["completed"], counts["review"]) == (1, 0, 2), counts)

    status, body = http("PATCH", f"/courses/{course_id}/knowledge-points/{ids_a[0]}/status", {"status": "mastered"}, expect=409)
    check("旧状态别名 mastered 不能绕过验证", status == 409)

    status, bad = http("PATCH", f"/courses/{course_id}/knowledge-points/{ids_a[0]}/status", {"status": "nonsense"})
    check("非法学习状态被拒绝", status == 422, bad.get("message"))

    _, body = http("GET", f"/courses/{course_id}")
    data = body["data"]
    check(
        "课程进度与状态分布交叉验证一致",
        data["progress"] == expected_progress(data["statusCounts"]),
        {"progress": data["progress"], "counts": data["statusCounts"]},
    )
    chapter_progress_ok = all(
        chapter["progress"] == expected_progress(chapter["statusCounts"]) for chapter in data["chapters"]
    )
    check("章节进度与章节状态分布一致", chapter_progress_ok)

    _, body = http("GET", f"/courses/{course_id}/progress")
    progress = body["data"]
    check(
        "进度接口返回总览、分章节与最近学习",
        progress["courseId"] == course_id
        and len(progress["chapters"]) == len(data["chapters"])
        and len(progress["recent"]) >= 3,
        {"chapters": len(progress["chapters"]), "recent": len(progress["recent"])},
    )
    check("最近学习按时间倒序", [r["lastStudiedAt"] for r in progress["recent"]]
          == sorted([r["lastStudiedAt"] for r in progress["recent"]], reverse=True))

    _, body = http("GET", f"/courses/{course_id}/knowledge-points?status=review")
    check("知识点列表支持按状态过滤", all(p["learningStatus"] == "review" for p in body["data"]) and body["data"], len(body["data"]))

    # ---------- 8. 越权/非法关联 ----------
    _, other = http("GET", "/courses")
    other_course = next((item for item in other["data"] if item["id"] != course_id), None)
    if other_course:
        _, other_detail = http("GET", f"/courses/{other_course['id']}")
        foreign_chapter = other_detail["data"]["chapters"][0]["id"]
        status, bad = http("PATCH", f"/courses/{course_id}/chapters/{foreign_chapter}", {"title": "越权改名"})
        check("章节归属校验：别的课程的章节不能被改", status == 404, bad.get("message"))
        foreign_point = other_detail["data"]["chapters"][0]["knowledgePoints"][0]["id"]
        status, bad = http("PATCH", f"/courses/{course_id}/knowledge-points/{foreign_point}/status", {"status": "completed"})
        check("知识点归属校验：别的课程的知识点不能被改状态", status == 404, bad.get("message"))
        status, bad = http("DELETE", f"/courses/{course_id}/knowledge-points/{foreign_point}")
        check("知识点归属校验：别的课程的知识点不能被删", status == 404, bad.get("message"))
    else:
        notes.append("库里只有一门课程，跳过跨课程归属校验")

    status, bad = http("GET", "/courses/999999")
    check("不存在的课程返回 404", status == 404, bad.get("message"))
    status, bad = http("PATCH", f"/courses/{course_id}/chapters/999999", {"title": "x"})
    check("不存在的章节返回 404", status == 404, bad.get("message"))
    status, bad = http("GET", "/knowledge-points/999999")
    check("不存在的知识点返回 404", status == 404, bad.get("message"))
    status, bad = http("POST", f"/courses/{course_id}/chapters", {"title": "   "})
    check("空章节名被参数校验拦下", status == 422, bad.get("message"))

    # ---------- 9. 删除章节 / 知识点 ----------
    _, body = http("GET", f"/courses/{course_id}")
    before_chapters = len(body["data"]["chapters"])
    victim = ids_a[1]
    _, body = http("DELETE", f"/courses/{course_id}/knowledge-points/{victim}", expect=200)
    chapter_now = [c for c in body["data"]["chapters"] if c["id"] == chapter_a["id"]][0]
    remaining = [p["id"] for p in chapter_now["knowledgePoints"]]
    orders = [p["sortOrder"] for p in chapter_now["knowledgePoints"]]
    check(
        "删除知识点后列表与序号同步",
        victim not in remaining and orders == list(range(len(orders))),
        {"ids": remaining, "orders": orders},
    )

    _, body = http("DELETE", f"/courses/{course_id}/chapters/{chapter_b['id']}", expect=200)
    check("删除章节后章节数减少", len(body["data"]["chapters"]) == before_chapters - 1, len(body["data"]["chapters"]))
    check(
        "删除章节不留孤儿知识点",
        db_rows("SELECT COUNT(*) FROM knowledge_points WHERE chapter_id = ?", (chapter_b["id"],))[0][0] == 0,
    )

    # ---------- 10. 刷新后仍然存在（重新读取 + 直接查库） ----------
    _, body = http("GET", f"/courses/{course_id}")
    fresh = body["data"]
    db_points = db_rows(
        "SELECT COUNT(*) FROM knowledge_points WHERE chapter_id IN (SELECT id FROM chapters WHERE course_id = ?)",
        (course_id,),
    )[0][0]
    expected_chapter_ids = [cid for cid in reversed_ids if cid != chapter_b["id"]]
    fresh_status = {p["id"]: p["learningStatus"] for c in fresh["chapters"] for p in c["knowledgePoints"]}
    check(
        "刷新后章节顺序仍在",
        [c["id"] for c in fresh["chapters"]] == expected_chapter_ids,
        [c["id"] for c in fresh["chapters"]],
    )
    check(
        "刷新后学习状态仍在",
        fresh_status.get(ids_a[0]) == "review" and fresh_status.get(ids_a[2]) == "in_progress",
        fresh_status,
    )
    check(
        "接口统计与数据库行数一致",
        fresh["knowledgePointCount"] == db_points,
        {"api": fresh["knowledgePointCount"], "db": db_points},
    )

    # ---------- 11. 删除课程：级联清理 ----------
    _, body = http("GET", f"/courses/{course_id}")
    kept_points = body["data"]["knowledgePointCount"]
    http("DELETE", f"/courses/{course_id}", expect=200)
    status, _ = http("GET", f"/courses/{course_id}")
    orphan_chapters = db_rows("SELECT COUNT(*) FROM chapters WHERE course_id = ?", (course_id,))[0][0]
    orphan_points = db_rows(
        "SELECT COUNT(*) FROM knowledge_points WHERE chapter_id NOT IN (SELECT id FROM chapters)", ()
    )[0][0]
    check("删除课程后详情返回 404", status == 404)
    check("删除课程后章节被级联删除", orphan_chapters == 0, orphan_chapters)
    check("删除课程后没有孤儿知识点", orphan_points == 0, orphan_points)
    notes.append(f"删除的课程含 {kept_points} 个知识点，全部随课程删除")

    passed = sum(1 for item in results if item["ok"])
    report = {
        "generatedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "notes": notes,
        "checks": results,
    }
    RESULT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果：{passed}/{len(results)} 通过")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
