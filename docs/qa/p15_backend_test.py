"""P1.5 学习档案、学习历史与断点续学测试（隔离数据库，不使用真实密钥）。

运行：python docs/qa/p15_backend_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = tempfile.TemporaryDirectory(prefix="mastery-p15-")
os.environ["MASTERY_LAB_DATA_DIR"] = SANDBOX.name
os.environ["MASTERY_LAB_DATABASE_URL"] = f"sqlite:///{Path(SANDBOX.name).as_posix()}/test.db"
sys.path.insert(0, str(ROOT / "apps/api"))

from fastapi.testclient import TestClient

from app.api.v1 import teaching as teaching_api
from app.core.security import encrypt_secret
from app.db import Base, SessionLocal, engine
from app.db.models import (
    Chapter,
    Course,
    KnowledgePoint,
    LearningActivity,
    LearningBreakpoint,
    MasteryHistory,
    MistakeOccurrence,
    MistakeRecord,
    ModelConfig,
)
from app.main import app
from app.services import learning_record, teaching_state


def seed():
    with SessionLocal() as db:
        course = Course(title="P1.5 学习档案测试", status="active", description="fixture", source_type="md", source_file="qa.md")
        chapter = Chapter(title="变量", sort_order=0)
        first = KnowledgePoint(title="变量与赋值", content="price = 12\nprint(price)", sort_order=0)
        second = KnowledgePoint(title="条件判断", content="if price > 10:\n    print(price)", sort_order=1)
        chapter.knowledge_points = [first, second]
        course.chapters = [chapter]
        model = ModelConfig(
            name="P1.5 fixture",
            model_name="p15-fixture",
            base_url="http://mock.invalid/v1",
            api_key_cipher=encrypt_secret("qa-key-not-real"),
            is_default=True,
        )
        db.add_all([course, model])
        db.commit()
        return course.id, [first.id, second.id]


class P15Base(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        engine.dispose()

    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.course_id, self.point_ids = seed()
        self.point_id = self.point_ids[0]
        self.client = TestClient(app)
        self.sid = self.client.post(
            "/api/v1/classroom/sessions",
            json={"courseId": self.course_id, "knowledgePointId": self.point_id},
        ).json()["data"]["id"]
        self.teaching_path = f"/api/v1/classroom/sessions/{self.sid}/teaching"

    # ---------- 教学动作辅助（与 P1.4 测试一致） ----------

    def state(self):
        response = self.client.get(self.teaching_path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def action(self, action, content="", output=None, request_id=None, revision=None):
        current = self.state()
        payload = {
            "requestId": request_id or str(uuid4()),
            "expectedRevision": current["revision"] if revision is None else revision,
            "action": action,
            "content": content,
        }
        async def fake_stream(**kwargs):
            yield output or "当前知识点的完整讲解。\n\n```python\nprice = 12\nprint(price)\n```\n预期输出：12。"
        with patch.object(teaching_api, "stream_chat", fake_stream):
            return self.client.post(self.teaching_path + "/actions", json=payload)

    def task(self, question="请说明变量 price 表示什么？"):
        return json.dumps(
            {
                "instruction": "围绕刚才的案例回答一个小问题。",
                "question": question,
                "rubric": "指出变量保存价格数值",
                "hint": "观察赋值号右侧",
                "summary": "",
            },
            ensure_ascii=False,
        )

    def evaluation(self, verdict="CORRECT", answer="price 保存价格 12", reason="依据实际回答判断"):
        return json.dumps(
            {
                "evaluation": verdict,
                "reason": reason,
                "misconceptions": ["把赋值当成相等判断"] if verdict in ("PARTIAL", "INCORRECT") else [],
                "suggested_action": "CONTINUE",
                "feedback": "你指出了变量保存价格数值。",
                "evidence_quote": answer,
                "summary": "变量保存可复用的数值。",
            },
            ensure_ascii=False,
        )

    def reach_check(self):
        self.assertEqual(self.action("START").status_code, 200)
        self.assertEqual(self.action("CONTINUE").status_code, 200)
        self.assertEqual(self.action("CONTINUE", output=self.task()).status_code, 200)
        self.assertEqual(self.state()["currentStage"], "CHECK")

    def reach_verify(self):
        self.reach_check()
        self.action("ANSWER", "price 保存价格 12", self.evaluation())
        for question in ["请把价格赋值给 price？", "请用 print 显示价格？"]:
            self.action("START", output=self.task(question))
            self.action("ANSWER", "price 保存价格 12", self.evaluation())
        self.assertEqual(self.state()["currentStage"], "VERIFY")
        self.action("START", output=self.task("如果价格变成 18，你会如何修改并解释这段程序？"))

    def verify_pass(self):
        return self.action("ANSWER", "price 保存价格 12", self.evaluation("PASSED"))

    # ---------- 学习活动与时间 ----------

    def start_activity(self, point_id=None, session_id=None):
        return self.client.post(
            "/api/v1/learning/activities/start",
            json={
                "courseId": self.course_id,
                "knowledgePointId": point_id or self.point_id,
                "sessionId": session_id or self.sid,
            },
        )

    def test_activity_heartbeat_counts_effective_time_and_caps_delta(self):
        response = self.start_activity()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["status"], "active")
        self.assertFalse(data["reused"])
        activity_id = data["id"]
        with SessionLocal() as db:
            row = db.get(LearningActivity, activity_id)
            row.last_heartbeat_at = (datetime.now(timezone.utc) - timedelta(seconds=30)).replace(tzinfo=None)
            db.commit()
        first = self.client.post(
            f"/api/v1/learning/activities/{activity_id}/heartbeat", json={"activeSecondsDelta": 30}
        ).json()["data"]
        self.assertGreaterEqual(first["activeSeconds"], 29)
        self.assertLessEqual(first["activeSeconds"], 36)
        capped = self.client.post(
            f"/api/v1/learning/activities/{activity_id}/heartbeat", json={"activeSecondsDelta": 600}
        ).json()["data"]
        self.assertLessEqual(capped["activeSeconds"] - first["activeSeconds"], 120)
        again = self.start_activity().json()["data"]
        self.assertTrue(again["reused"])
        self.assertEqual(again["id"], activity_id)

    def test_idle_activity_is_closed_not_counted(self):
        activity_id = self.start_activity().json()["data"]["id"]
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        with SessionLocal() as db:
            row = db.get(LearningActivity, activity_id)
            row.last_heartbeat_at = old.replace(tzinfo=None)
            row.active_seconds = 45
            db.commit()
        heartbeat = self.client.post(
            f"/api/v1/learning/activities/{activity_id}/heartbeat", json={"activeSecondsDelta": 30}
        ).json()["data"]
        self.assertTrue(heartbeat["closed"])
        self.assertEqual(heartbeat["activeSeconds"], 45)
        fresh = self.start_activity().json()["data"]
        self.assertFalse(fresh["reused"])
        self.assertNotEqual(fresh["id"], activity_id)

    def test_finish_and_server_restart_do_not_add_offline_time(self):
        activity_id = self.start_activity().json()["data"]["id"]
        self.client.post(f"/api/v1/learning/activities/{activity_id}/heartbeat", json={"activeSecondsDelta": 20})
        finished = self.client.post(
            f"/api/v1/learning/activities/{activity_id}/finish",
            json={"result": "finished", "reason": "browser_closed"},
        ).json()["data"]
        self.assertEqual(finished["status"], "finished")
        with SessionLocal() as db:
            before = db.get(LearningActivity, activity_id).active_seconds
            row = db.get(LearningActivity, activity_id)
            row.status = "active"
            row.last_heartbeat_at = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None)
            db.commit()
            closed = learning_record.close_stale_activities(db)
            self.assertGreaterEqual(closed, 1)
        with SessionLocal() as db:
            after = db.get(LearningActivity, activity_id)
            self.assertEqual(after.active_seconds, before)
            self.assertEqual(after.status, "finished")
            self.assertEqual(after.end_reason, "idle_timeout")

    # ---------- 断点 ----------

    def test_breakpoint_saves_draft_and_rejects_older_sequence(self):
        path = f"/api/v1/learning/sessions/{self.sid}/breakpoint"
        first = self.client.put(path, json={"clientSeq": 2, "draftAnswer": "我的回答", "inputMode": "ANSWER"}).json()["data"]
        self.assertTrue(first["accepted"])
        self.assertEqual(first["draftAnswer"], "我的回答")
        stale = self.client.put(path, json={"clientSeq": 1, "draftAnswer": "旧草稿", "inputMode": "ASK"}).json()["data"]
        self.assertFalse(stale["accepted"])
        self.assertEqual(stale["draftAnswer"], "我的回答")
        latest = self.client.get(path).json()["data"]
        self.assertEqual(latest["clientSeq"], 2)
        self.assertEqual(latest["inputMode"], "ANSWER")

    def test_breakpoint_tracks_server_teaching_state(self):
        self.reach_check()
        data = self.client.get(f"/api/v1/learning/sessions/{self.sid}/breakpoint").json()["data"]
        self.assertEqual(data["currentStage"], "CHECK")
        self.assertEqual(data["stageStatus"], "WAITING_USER")
        self.assertTrue(data["currentQuestion"])
        self.assertEqual(data["checkAttempts"], 0)

    def test_resume_returns_latest_position_and_advances_completed_point(self):
        self.reach_verify()
        self.verify_pass()
        resume = self.client.get("/api/v1/learning/resume").json()["data"]
        self.assertIsNotNone(resume)
        self.assertEqual(resume["courseId"], self.course_id)
        self.assertEqual(resume["knowledgePointId"], self.point_ids[1])
        self.assertEqual(resume["stageStatus"], "COMPLETED")

    # ---------- 完整学习与档案 ----------

    def test_full_flow_records_mistake_mastery_history_and_reports(self):
        # CHECK 答错 → 错题 + 理解中
        self.reach_check()
        self.action("ANSWER", "价格是字符串", self.evaluation("INCORRECT", "价格是字符串", "把数值当成了字符串"))
        state = self.state()
        self.assertEqual(state["currentStage"], "TEACH")
        mistakes = self.client.get("/api/v1/learning/mistakes").json()["data"]
        self.assertEqual(mistakes["total"], 1)
        record = mistakes["items"][0]
        self.assertEqual(record["stage"], "CHECK")
        self.assertEqual(record["errorType"], "concept")
        self.assertEqual(record["status"], "open")
        self.assertEqual(record["occurrenceCount"], 1)
        self.assertIn("价格是字符串", record["userAnswer"])
        mastery = self.client.get("/api/v1/learning/mastery").json()["data"]
        point = next(
            item
            for course in mastery["courses"]
            for chapter in course["chapters"]
            for item in chapter["points"]
            if item["pointId"] == self.point_id
        )
        self.assertIn(point["masteryState"], ("UNDERSTANDING", "NEEDS_REVIEW"))

        # 再讲解后重新走完 DEMO/CHECK → PAIR；两个小步通过 → VERIFY；失败 → NEEDS_REVIEW
        self.action("START")
        self.action("CONTINUE")
        self.action("CONTINUE", output=self.task())
        self.action("ANSWER", "price 保存价格 12", self.evaluation())
        for question in ["请把价格赋值给 price？", "请用 print 显示价格？"]:
            self.action("START", output=self.task(question))
            self.action("ANSWER", "price 保存价格 12", self.evaluation())
        self.assertEqual(self.state()["currentStage"], "VERIFY")
        self.action("START", output=self.task("如果价格变成 18，你会如何修改并解释这段程序？"))
        self.action("ANSWER", "我不知道", self.evaluation("FAILED", "我不知道", "未完成独立验证"))
        self.assertEqual(self.state()["currentStage"], "PAIR")
        self.assertEqual(self.state()["masteryState"], "NEEDS_REVIEW")
        history = self.client.get(f"/api/v1/learning/history?pointId={self.point_id}").json()["data"]
        self.assertGreaterEqual(history["total"], 1)
        activity_id = history["items"][0]["id"]

        # 失败后回到 PAIR：重新完成两个小步，再独立验证通过 → INDEPENDENT
        for question in ["请把价格赋值给 price？", "请用 print 显示价格？"]:
            self.action("START", output=self.task(question))
            self.action("ANSWER", "price 保存价格 12", self.evaluation())
        self.assertEqual(self.state()["currentStage"], "VERIFY")
        self.action("START", output=self.task("写出价格赋值并说明含义。"))
        self.verify_pass()
        self.assertEqual(self.state()["masteryState"], "INDEPENDENT")
        detail = self.client.get(f"/api/v1/courses/{self.course_id}").json()["data"]
        self.assertEqual(detail["progress"], 50)
        mastery = self.client.get("/api/v1/learning/mastery").json()["data"]
        independent = [s for s in mastery["states"] if s["state"] == "INDEPENDENT"][0]
        self.assertEqual(independent["count"], 1)

        overview = self.client.get("/api/v1/learning/overview").json()["data"]
        self.assertEqual(overview["completedPoints"], 1)
        self.assertEqual(overview["independentPoints"], 1)
        self.assertGreaterEqual(overview["activityCount"], 1)
        report = self.client.get("/api/v1/learning/report").json()["data"]
        self.assertEqual(report["weekCompletedPoints"], 1)
        self.assertTrue(report["recentProgress"])
        self.assertTrue(any(item["pointId"] == self.point_id for item in report["recentProgress"]))

        detail_activity = self.client.get(f"/api/v1/learning/history/{activity_id}").json()["data"]
        self.assertEqual(detail_activity["activity"]["knowledgePointId"], self.point_id)
        self.assertTrue(detail_activity["events"])
        self.assertTrue(detail_activity["evaluations"])
        self.assertTrue(detail_activity["mistakes"])
        self.assertEqual(
            detail_activity["activity"]["activeSeconds"], history["items"][0]["activeSeconds"]
        )

    def test_repeated_same_error_is_merged_with_occurrences(self):
        self.reach_check()
        self.action("ANSWER", "价格是字符串", self.evaluation("INCORRECT", "价格是字符串", "把数值当成了字符串"))
        self.action("START")
        self.action("CONTINUE")
        self.action("CONTINUE", output=self.task())
        self.action("ANSWER", "价格是字符串", self.evaluation("INCORRECT", "价格是字符串", "把数值当成了字符串"))
        mistakes = self.client.get("/api/v1/learning/mistakes").json()["data"]
        self.assertEqual(mistakes["total"], 1)
        record = mistakes["items"][0]
        self.assertEqual(record["occurrenceCount"], 2)
        detail = self.client.get(f"/api/v1/learning/mistakes/{record['id']}").json()["data"]
        self.assertEqual(len(detail["occurrences"]), 2)
        marked = self.client.patch(
            f"/api/v1/learning/mistakes/{record['id']}", json={"status": "understood"}
        ).json()["data"]
        self.assertEqual(marked["status"], "understood")
        self.assertIsNotNone(marked["resolvedAt"])
        practice = self.client.post(f"/api/v1/learning/mistakes/{record['id']}/practice").json()["data"]
        self.assertEqual(practice["courseId"], self.course_id)
        self.assertEqual(practice["knowledgePointId"], self.point_id)
        self.assertIn("/classroom", practice["route"])

    def test_restart_keeps_history_and_evidence(self):
        self.reach_verify()
        self.verify_pass()
        with SessionLocal() as db:
            history_before = db.query(MasteryHistory).count()
        state = self.state()
        response = self.client.post(
            self.teaching_path + "/control",
            json={"requestId": str(uuid4()), "expectedRevision": state["revision"], "action": "RESTART"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        with SessionLocal() as db:
            self.assertGreaterEqual(db.query(MasteryHistory).count(), history_before)
            point = db.get(KnowledgePoint, self.point_id)
            self.assertEqual(point.mastery_state, "INDEPENDENT")
        self.assertEqual(self.state()["currentStage"], "TEACH")
        detail = self.client.get(f"/api/v1/courses/{self.course_id}").json()["data"]
        # 用户主动重新学习会把当前知识点置为“学习中”（权重 0.4 / 2 个点 = 20%），但掌握历史不清空。
        self.assertEqual(detail["progress"], 20)

    def test_invalid_ids_and_cross_course_access_are_rejected(self):
        other_course = self.client.post(
            "/api/v1/courses", json={"title": "另一门课"}
        )
        # 课程创建接口在 P1.1 是上传/草稿流程，这里只验证伪造 ID 不会泄露数据
        self.assertIn(other_course.status_code, (404, 405, 422))
        self.assertEqual(self.client.get("/api/v1/learning/mistakes/999999").status_code, 404)
        self.assertEqual(
            self.client.post(
                "/api/v1/learning/activities/start",
                json={"courseId": self.course_id, "knowledgePointId": self.point_ids[1], "sessionId": self.sid},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/api/v1/learning/history?courseId=999999").status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/v1/learning/history/999999").status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
