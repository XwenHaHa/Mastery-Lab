"""Real configured model acceptance. --keep-course leaves only the QA course for UI tests."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import httpx

HERE = Path(__file__).parent
BASE = "http://127.0.0.1:8000/api/v1"
RESULT = HERE / "p13-real-result.json"
report = {"kind": "real-configured-model", "startedAt": datetime.now(timezone.utc).isoformat(), "checks": [], "streams": []}


def check(name, condition, detail=None):
    report["checks"].append({"name": name, "passed": bool(condition), "detail": detail})
    print(f"[{'PASS' if condition else 'FAIL'}] {name}", flush=True)
    if not condition:
        raise AssertionError(name)


async def request(client, method, path, **kwargs):
    response = await client.request(method, BASE + path, **kwargs)
    response.raise_for_status()
    return response.json()["data"]


async def collect(client, session_id, action, content=None, stop_after=None):
    started = time.monotonic()
    item = {"action": action, "sessionId": session_id, "deltaCount": 0, "firstDeltaMs": None, "lastDeltaMs": None, "events": [], "content": ""}
    report["streams"].append(item)
    event = ""
    async with client.stream("POST", f"{BASE}/classroom/sessions/{session_id}/{action}", json={"content": content} if content else None) as response:
        response.raise_for_status()
        check(f"{action} SSE content type", "text/event-stream" in response.headers.get("content-type", ""))
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            if not line.startswith("data:"):
                continue
            data = json.loads(line[5:])
            if event != "delta":
                item["events"].append(event)
            if event == "delta":
                item["deltaCount"] += 1
                elapsed = round((time.monotonic() - started) * 1000)
                if item["firstDeltaMs"] is None:
                    item["firstDeltaMs"] = elapsed
                item["lastDeltaMs"] = elapsed
                item["content"] += data["text"]
                if stop_after and item["deltaCount"] == stop_after:
                    stop_started = time.monotonic()
                    await request(client, "POST", f"/classroom/sessions/{session_id}/stop")
                    item["stopRequestedAtMs"] = round((stop_started - started) * 1000)
            elif event == "done":
                item["status"] = data["status"]
                item["savedMessageId"] = data["messageId"]
                check(f"{action} persisted equals visible", item["content"] == data["message"]["content"])
            elif event == "error":
                item["error"] = data["message"]
    item["durationMs"] = round((time.monotonic() - started) * 1000)
    check(f"{action} terminates correctly", item.get("status") == ("interrupted" if stop_after else "completed"), item.get("error"))
    return item


async def main(keep):
    course_id = None
    async with httpx.AsyncClient(timeout=240) as client:
        try:
            models = await request(client, "GET", "/models")
            check("configured model exists", bool(models))
            model = next((item for item in models if item["isDefault"]), models[0])
            report["modelName"] = model["modelName"]
            material = (HERE / "fixtures/p13-python.md").read_bytes()
            course = await request(client, "POST", "/courses/upload", files={"file": ("p13-python.md", material, "text/markdown")})
            course_id = course["id"]
            report["courseId"] = course_id
            course = await request(client, "POST", f"/courses/{course_id}/confirm")
            points = [point for chapter in course["chapters"] for point in chapter["knowledgePoints"]]
            report["pointIds"] = [point["id"] for point in points]
            check("material imported and confirmed", len(points) == 3)
            session = await request(client, "POST", "/classroom/sessions", json={"courseId": course_id, "knowledgePointId": points[0]["id"]})
            sid = session["id"]
            report["sessionId"] = sid
            lesson = await collect(client, sid, "start")
            check("real multi-chunk streaming", lesson["deltaCount"] > 1 and lesson["lastDeltaMs"] > lesson["firstDeltaMs"], lesson["deltaCount"])
            check("lesson grounded in material", "37" in lesson["content"] and "price" in lesson["content"])
            check("lesson contains complete Python example", "```python" in lesson["content"] and "print(" in lesson["content"])
            answer = await collect(client, sid, "messages", "请只解释刚才书店案例里的 price 和 total，并指出为什么输出是 74；不要换例子。")
            check("follow-up understands previous example", all(word in answer["content"] for word in ["price", "total", "74"]))
            stopped = await collect(client, sid, "messages", "请用三个小步骤慢慢解释这个案例。", stop_after=3)
            check("stop retains partial output", bool(stopped["content"]))
            detail = await request(client, "GET", f"/classroom/sessions/{sid}")
            check("stop persisted and lock released", not detail["streaming"] and detail["messages"][-1]["status"] == "interrupted")
            await collect(client, sid, "regenerate")
            restored = await request(client, "POST", "/classroom/sessions", json={"courseId": course_id, "knowledgePointId": points[0]["id"]})
            check("reopen restores same conversation", restored["id"] == sid and len(restored["messages"]) == 5)
            second = await request(client, "POST", "/classroom/sessions", json={"courseId": course_id, "knowledgePointId": points[1]["id"]})
            check("knowledge points isolated", second["id"] != sid and not second["messages"])
            second_lesson = await collect(client, second["id"], "start")
            check("switch changes teaching context", "books" in second_lesson["content"] and "索引" in second_lesson["content"])
            report["passed"] = True
        except Exception as error:
            report["passed"] = False
            report["failure"] = type(error).__name__ + ": " + str(error)[:300]
            raise
        finally:
            if course_id and not keep:
                await request(client, "DELETE", f"/courses/{course_id}")
            report["courseRetainedForUi"] = bool(course_id and keep)
            RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-course", action="store_true")
    asyncio.run(main(parser.parse_args().keep_course))
