"""P1.3 isolated regression tests: python docs/qa/p13_backend_test.py."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = tempfile.TemporaryDirectory(prefix="mastery-p13-")
os.environ["MASTERY_LAB_DATA_DIR"] = SANDBOX.name
os.environ["MASTERY_LAB_DATABASE_URL"] = f"sqlite:///{Path(SANDBOX.name).as_posix()}/test.db"
sys.path.insert(0, str(ROOT / "apps/api"))

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1 import classroom
from app.core.security import encrypt_secret
from app.db import Base, SessionLocal, engine
from app.db.models import Chapter, ChatMessage, Course, KnowledgePoint, LearningSession, ModelConfig
from app.main import app
from app.services import classroom_service, llm_client, stream_registry, teaching_prompt
from app.core.response import ConflictError


def seed():
    with SessionLocal() as db:
        course = Course(title="Python course", status="active", description="Python basics", source_type="md", source_file="test.md")
        chapter = Chapter(title="Variables", sort_order=0)
        point = KnowledgePoint(title="Assignment", content="price = 12\nprint(price)", sort_order=0)
        chapter.knowledge_points = [point]
        course.chapters = [chapter]
        cipher = encrypt_secret("sk-test-only-not-real")
        model = ModelConfig(name="Test model", model_name="test-model", base_url="http://mock.invalid/v1", api_key_cipher=cipher, is_default=True)
        db.add_all([course, model])
        db.commit()
        return course.id, point.id, model.id


class PromptTests(unittest.TestCase):
    def test_initial_lesson_is_kept_for_followup(self):
        history = [ChatMessage(role="assistant", content="price = 12"), ChatMessage(role="user", content="Explain that code")]
        kept = teaching_prompt.trim_history(history)
        self.assertEqual([item.content for item in kept], [item.content for item in history])

    def test_single_message_respects_budget(self):
        kept = teaching_prompt.trim_history([ChatMessage(role="user", content="x" * 1000)], max_chars=80)
        self.assertLessEqual(sum(len(item.content) for item in kept), 80)

    def test_clipping_does_not_mutate_persisted_message(self):
        message = ChatMessage(role="user", content="x" * 1000)
        teaching_prompt.trim_history([message], max_chars=80)
        self.assertEqual(len(message.content), 1000)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, content, status=200, content_type="text/event-stream"):
        original = httpx.AsyncClient
        transport = httpx.MockTransport(lambda request: httpx.Response(status, content=content, headers={"content-type": content_type}))
        with patch.object(llm_client.httpx, "AsyncClient", side_effect=lambda **kwargs: original(transport=transport, **kwargs)):
            return [text async for text in llm_client.stream_chat(base_url="http://mock.invalid/v1", model_name="test", api_key="secret-canary", messages=[])]

    async def test_sse_deltas(self):
        content = 'data: {"choices":[{"delta":{"content":"hello"}}]}\r\n\r\ndata: [DONE]\r\n\r\n'
        self.assertEqual(await self.collect(content), ["hello"])

    async def test_secret_split_across_deltas_is_redacted(self):
        content = ''.join('data: ' + json.dumps({"choices": [{"delta": {"content": text}}]}) + '\n\n'
                          for text in ["before sec", "ret-ca", "nary after"])
        output = ''.join(await self.collect(content + 'data: [DONE]\n\n'))
        self.assertNotIn("secret-canary", output)
        self.assertIn("before ", output)
        self.assertTrue(output.endswith(" after"))

    async def test_first_token_timeout(self):
        async def stalled(**kwargs):
            await asyncio.sleep(10)
            yield "late"
        with patch.object(llm_client, "_stream_chat", stalled), patch.object(llm_client.settings, "llm_stream_timeout_seconds", 0.02):
            with self.assertRaises(llm_client.LLMStreamError):
                async for _text in llm_client.stream_chat(base_url="http://mock.invalid", model_name="test", api_key="secret", messages=[]):
                    self.fail("late token")

    async def test_premature_eof_is_not_success(self):
        with self.assertRaises(llm_client.LLMStreamError):
            await self.collect('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')

    async def test_http_error_does_not_echo_secret(self):
        with self.assertRaises(llm_client.LLMStreamError) as caught:
            await self.collect('secret-canary', status=401)
        self.assertNotIn("secret-canary", str(caught.exception))

    async def test_sse_error_does_not_echo_secret(self):
        with self.assertRaises(llm_client.LLMStreamError) as caught:
            await self.collect('data: {"error":{"message":"secret-canary"}}\n\n')
        self.assertNotIn("secret-canary", str(caught.exception))

    async def test_malformed_sse_is_explicit_error(self):
        with self.assertRaises(llm_client.LLMStreamError):
            await self.collect('data: not-json\n\ndata: [DONE]\n\n')


class SessionTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.course_id, self.point_id, self.model_id = seed()
        self.client = TestClient(app)

    def open(self):
        response = self.client.post("/api/v1/classroom/sessions", json={"courseId": self.course_id, "knowledgePointId": self.point_id})
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]["id"]

    def test_reopen_and_wrong_course(self):
        self.assertEqual(self.open(), self.open())
        response = self.client.post("/api/v1/classroom/sessions", json={"courseId": 9999, "knowledgePointId": self.point_id})
        self.assertEqual(response.status_code, 404)

    def test_initial_stream_followup_and_history(self):
        prompts = []

        async def fake_stream(**kwargs):
            prompts.append(kwargs["messages"])
            yield "lesson "
            yield "print(price)"

        sid = self.open()
        with patch.object(classroom, "stream_chat", fake_stream):
            response = self.client.post(f"/api/v1/classroom/sessions/{sid}/start")
            self.assertEqual(response.text.count("event: delta"), 2)
            self.assertIn("event: done", response.text)
            self.client.post(f"/api/v1/classroom/sessions/{sid}/messages", json={"content": "Explain that code"})
        self.assertTrue(any(item["role"] == "assistant" and "print(price)" in item["content"] for item in prompts[-1]))
        detail = self.client.get(f"/api/v1/classroom/sessions/{sid}").json()["data"]
        self.assertEqual(len(detail["messages"]), 3)
        self.assertFalse(detail["streaming"])
        response = self.client.get(f"/api/v1/classroom/sessions/{sid}/messages?limit=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 2)

    def test_manual_status_syncs_course_and_session_without_changing_history(self):
        sid = self.open()
        with SessionLocal() as db:
            db.add(ChatMessage(session_id=sid, role="assistant", content="saved lesson", status="completed"))
            db.commit()
        history = self.client.get(f"/api/v1/classroom/sessions/{sid}").json()["data"]["messages"]
        blocked = self.client.patch(f"/api/v1/courses/{self.course_id}/knowledge-points/{self.point_id}/status", json={"status": "completed"})
        self.assertEqual(blocked.status_code, 409)
        for status, progress in [("review", 70), ("in_progress", 40)]:
            with self.subTest(status=status):
                response = self.client.patch(
                    f"/api/v1/courses/{self.course_id}/knowledge-points/{self.point_id}/status",
                    json={"status": status},
                )
                self.assertEqual(response.status_code, 200)
                course = response.json()["data"]
                self.assertEqual(course["progress"], progress)
                self.assertEqual(course["chapters"][0]["knowledgePoints"][0]["learningStatus"], status)
                self.assertEqual(course["statusCounts"]["notStarted"], 0)
                self.assertEqual(self.open(), sid)
                restored = self.client.get(f"/api/v1/classroom/sessions/{sid}").json()["data"]
                self.assertEqual(restored["point"]["learningStatus"], status)
                self.assertEqual(restored["course"]["progress"], progress)
                self.assertEqual(restored["course"]["learnedCount"], 1)
                self.assertEqual(restored["messages"], history)
                detail = self.client.get(f"/api/v1/courses/{self.course_id}").json()["data"]
                self.assertEqual(detail["progress"], progress)
                self.assertEqual(detail["chapters"][0]["knowledgePoints"][0]["masteryLevel"], 0)

    def test_regenerate_preflight_failure_keeps_old_answer(self):
        sid = self.open()
        with SessionLocal() as db:
            db.add(ChatMessage(session_id=sid, role="assistant", content="previous lesson", status="completed"))
            db.delete(db.get(ModelConfig, self.model_id))
            db.commit()
        response = self.client.post(f"/api/v1/classroom/sessions/{sid}/regenerate")
        self.assertEqual(response.status_code, 422)
        detail = self.client.get(f"/api/v1/classroom/sessions/{sid}").json()["data"]
        self.assertEqual(detail["messages"][0]["content"], "previous lesson")

    def test_missing_model_does_not_save_orphan_question(self):
        sid = self.open()
        with SessionLocal() as db:
            db.delete(db.get(ModelConfig, self.model_id))
            db.commit()
        response = self.client.post(f"/api/v1/classroom/sessions/{sid}/messages", json={"content": "question"})
        self.assertEqual(response.status_code, 422)
        detail = self.client.get(f"/api/v1/classroom/sessions/{sid}").json()["data"]
        self.assertEqual(detail["messages"], [])

    def test_blank_question_rejected(self):
        sid = self.open()
        response = self.client.post(f"/api/v1/classroom/sessions/{sid}/messages", json={"content": "   "})
        self.assertEqual(response.status_code, 422)

    def test_course_association_and_context(self):
        with SessionLocal() as db:
            other = Course(title="Other course", status="active", source_type="md", source_file="other.md")
            db.add(other)
            db.commit()
            other_id = other.id
        response = self.client.get(f"/api/v1/classroom/context?courseId={other_id}&pointId={self.point_id}")
        self.assertEqual(response.status_code, 404)
        detail = self.client.get(f"/api/v1/classroom/context?courseId={self.course_id}&pointId={self.point_id}").json()["data"]
        self.assertEqual(detail["point"]["id"], self.point_id)
        self.assertEqual(set(detail["model"]), {"id", "name", "modelName"})

    def test_no_model_can_open_session_and_read_history(self):
        with SessionLocal() as db:
            db.delete(db.get(ModelConfig, self.model_id))
            db.commit()
        sid = self.open()
        detail = self.client.get(f"/api/v1/classroom/sessions/{sid}").json()["data"]
        self.assertIsNone(detail["model"])
        self.assertEqual(detail["messages"], [])

    def test_regenerate_replaces_only_last_answer(self):
        async def fake_stream(**kwargs):
            yield "new lesson"
        sid = self.open()
        with patch.object(classroom, "stream_chat", fake_stream):
            self.client.post(f"/api/v1/classroom/sessions/{sid}/start")
            self.client.post(f"/api/v1/classroom/sessions/{sid}/messages", json={"content": "question"})
            self.client.post(f"/api/v1/classroom/sessions/{sid}/regenerate")
        detail = self.client.get(f"/api/v1/classroom/sessions/{sid}").json()["data"]
        self.assertEqual([message["role"] for message in detail["messages"]], ["assistant", "user", "assistant"])
        self.assertEqual(detail["messages"][-1]["status"], "completed")

    def test_upstream_error_persists_partial_and_releases_lock(self):
        async def fail_stream(**kwargs):
            yield "partial lesson"
            raise llm_client.LLMStreamError("upstream unavailable", http_status=429)
        sid = self.open()
        with patch.object(classroom, "stream_chat", fail_stream):
            result = self.client.post(f"/api/v1/classroom/sessions/{sid}/start")
        self.assertIn("event: error", result.text)
        detail = self.client.get(f"/api/v1/classroom/sessions/{sid}").json()["data"]
        self.assertFalse(detail["streaming"])
        self.assertEqual(detail["messages"][0]["content"], "partial lesson")
        self.assertEqual(detail["messages"][0]["status"], "failed")

    def test_negative_session_id_rejected(self):
        self.assertEqual(self.client.get("/api/v1/classroom/sessions/-1").status_code, 422)

    def test_crash_leftover_does_not_appear_active_during_next_answer(self):
        sid = self.open()
        with SessionLocal() as db:
            db.add(ChatMessage(session_id=sid, role="assistant", content="saved before crash", status="streaming"))
            db.commit()
        classroom._prepare_stream(sid, content="continue")
        with SessionLocal() as db:
            messages = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == sid).order_by(ChatMessage.id)))
            self.assertEqual(messages[0].status, "interrupted")
            self.assertEqual(messages[0].content, "saved before crash")
            self.assertEqual(messages[-1].status, "streaming")

    def test_delete_course_cascades_history(self):
        sid = self.open()
        with SessionLocal() as db:
            db.add(ChatMessage(session_id=sid, role="user", content="hello"))
            db.commit()
            db.delete(db.get(Course, self.course_id))
            db.commit()
            self.assertEqual(list(db.scalars(select(ChatMessage))), [])
            self.assertEqual(list(db.scalars(select(LearningSession))), [])


class CancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_generation_is_rejected(self):
        event = await stream_registry.register(101)
        try:
            with self.assertRaises(ConflictError):
                await classroom._register_or_conflict(101)
        finally:
            await stream_registry.unregister(101, event)

    async def test_model_switch_during_generation_rejected(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        course_id, point_id, model_id = seed()
        with SessionLocal() as db:
            sid = classroom_service.open_session(db, course_id=course_id, point_id=point_id).id
        event = await stream_registry.register(sid)
        try:
            with SessionLocal() as db:
                with self.assertRaises(ConflictError):
                    classroom_service.open_session(db, course_id=course_id, point_id=point_id, model_config_id=model_id + 1)
        finally:
            await stream_registry.unregister(sid, event)

    async def test_stop_cancels_idle_upstream_and_persists_partial(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        course_id, point_id, _model_id = seed()
        with SessionLocal() as db:
            sid = classroom_service.open_session(db, course_id=course_id, point_id=point_id).id
        event = await stream_registry.register(sid)
        prepared = classroom._prepare_stream(sid)
        waiting = asyncio.Event()
        closed = asyncio.Event()

        async def upstream(**kwargs):
            try:
                yield "saved partial"
                waiting.set()
                await asyncio.Event().wait()
            finally:
                closed.set()

        class Request:
            async def is_disconnected(self):
                return False

        async def consume():
            return [chunk async for chunk in classroom._event_stream(prepared, event, Request())]

        with patch.object(classroom, "stream_chat", upstream):
            task = asyncio.create_task(consume())
            await asyncio.wait_for(waiting.wait(), 2)
            await stream_registry.cancel(sid)
            chunks = await asyncio.wait_for(task, 0.5)
        self.assertTrue(closed.is_set())
        self.assertFalse(stream_registry.is_active(sid))
        self.assertIn('"interrupted"', chunks[-1])
        with SessionLocal() as db:
            last = db.scalars(select(ChatMessage).where(ChatMessage.session_id == sid)).one()
            self.assertEqual(last.content, "saved partial")
            self.assertEqual(last.status, "interrupted")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        engine.dispose()
        SANDBOX.cleanup()
