"""P1.6 测试基座：隔离临时数据库，绝不接触用户 data 目录。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TEMP_ROOT = Path(tempfile.mkdtemp(prefix="mastery-lab-pytest-"))
os.environ.setdefault("MASTERY_LAB_DATA_DIR", str(_TEMP_ROOT / "data"))
os.environ.setdefault(
    "MASTERY_LAB_DATABASE_URL", f"sqlite:///{(_TEMP_ROOT / 'test.db').as_posix()}"
)
os.environ.setdefault("MASTERY_LAB_TEACHING_PIPELINE_VERSION", "1")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db():
    from app.db import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded(db):
    """最小课程结构：1 课程 / 1 章节 / 1 知识点 / 1 会话。"""
    from app.db.models import Chapter, Course, KnowledgePoint, LearningSession

    course = Course(title=f"测试课程-{os.urandom(4).hex()}", status="active")
    db.add(course)
    db.flush()
    chapter = Chapter(course_id=course.id, title="测试章节")
    db.add(chapter)
    db.flush()
    point = KnowledgePoint(
        chapter_id=chapter.id,
        title="测试知识点",
        description="用于自动化回归",
        content="这是测试知识点正文。",
    )
    db.add(point)
    db.flush()
    session_row = LearningSession(course_id=course.id, knowledge_point_id=point.id)
    db.add(session_row)
    db.commit()
    return {"course": course, "chapter": chapter, "point": point, "session": session_row}
