"""P1.6-D：提示词统一组装、学科识别与活动推荐。"""

from __future__ import annotations

from uuid import uuid4

from app.db.models import Chapter, Course, KnowledgePoint, LearningSession
from app.schemas.teaching import TeachingAction, TeachingTask
from app.services import prompt_assembler, teaching_protocol
from app.services.teaching_state import TeachingStateMachine


def _entity(title: str, description: str, content: str):
    class Entity:
        pass

    entity = Entity()
    entity.title = title
    entity.description = description
    entity.content = content
    return entity


def test_subject_detection_by_keywords():
    math = prompt_assembler.detect_subject_profile(
        _entity("高等数学", "导数与积分", ""),
        _entity("导数定义", "用极限定义导数", "函数 极限 证明"),
    )
    language = prompt_assembler.detect_subject_profile(
        _entity("商务英语", "口语与听力", ""),
        _entity("问候语", "日常对话", "单词 语法 句型 发音"),
    )
    theory = prompt_assembler.detect_subject_profile(
        _entity("中国历史", "近代史", ""),
        _entity("辛亥革命", "历史事件", "人物 社会 政治"),
    )
    assert math.key == "math"
    assert language.key == "language"
    assert theory.key == "theory"


def test_activity_recommendation_matches_subject_and_stage():
    assert prompt_assembler.recommend_activity_type("programming", "DEMONSTRATE") == "CODE_DEMO"
    assert prompt_assembler.recommend_activity_type("math", "DEMONSTRATE") == "FORMULA_DERIVATION"
    assert prompt_assembler.recommend_activity_type("theory", "DEMONSTRATE") == "DIAGRAM_WALKTHROUGH"
    assert prompt_assembler.recommend_activity_type("language", "INTERACT") == "FILL_IN_BLANK"
    assert prompt_assembler.recommend_activity_type("practice", "VERIFY") == "PRACTICAL_TASK"


def test_teaching_messages_follow_required_order(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    view = machine.view(machine.ensure(session_id))
    operation = machine.begin(
        session_id,
        TeachingAction(
            request_id=uuid4(),
            expected_revision=view["revision"],
            action="START",
        ),
        "test-model",
    )
    machine.finish(operation.id, "讲解内容")

    view = machine.view(machine.ensure(session_id))
    operation = machine.begin(
        session_id,
        TeachingAction(
            request_id=uuid4(),
            expected_revision=view["revision"],
            action="CONTINUE",
        ),
        "test-model",
    )
    machine.finish(operation.id, "示例内容")

    view = machine.view(machine.ensure(session_id))
    operation = machine.begin(
        session_id,
        TeachingAction(
            request_id=uuid4(),
            expected_revision=view["revision"],
            action="CONTINUE",
        ),
        "test-model",
    )
    task = TeachingTask(
        instruction="读题后回答。",
        question="这个循环执行几次？",
        rubric="能说出循环次数",
        hint="看 range 的终点",
        summary="",
    )
    machine.finish(operation.id, f"{task.instruction}\n\n{task.question}", task)
    operation = db.get(type(operation), operation.id)

    row = db.get(type(seeded["session"]), session_id)
    progress = machine.ensure(session_id)
    messages = teaching_protocol.build_messages(db, row, progress, operation, "")

    contents = [item["content"] for item in messages if item["role"] == "system"]
    assert "Mastery Lab 的耐心老师" in contents[0]
    assert "[学科策略]" in contents[1]
    assert "[阶段契约]" in contents[2]
    assert "[当前活动]" in contents[3]
    assert "教材上下文" in contents[4] or "当前知识点" in contents[4]
    assert "SHORT_ANSWER" in contents[3]


def test_math_and_language_demo_prompts_recommend_matching_activity(db):
    cases = [
        ("高等数学", "导数", "函数 极限 求导 证明", "FORMULA_DERIVATION"),
        ("商务英语", "问候", "单词 语法 听力 口语", "AUDIO_EXERCISE"),
        ("Python 入门", "循环", "代码 变量 循环", "CODE_DEMO"),
    ]
    for course_title, point_title, content, expected in cases:
        course = Course(title=course_title, description=course_title, status="active")
        db.add(course)
        db.flush()
        chapter = Chapter(course_id=course.id, title="示例章节")
        db.add(chapter)
        db.flush()
        point = KnowledgePoint(chapter_id=chapter.id, title=point_title, content=content)
        db.add(point)
        db.flush()
        session_row = LearningSession(course_id=course.id, knowledge_point_id=point.id)
        db.add(session_row)
        db.commit()

        machine = TeachingStateMachine(db)
        progress = machine.ensure(session_row.id)
        progress.pipeline_version = 2
        progress.current_stage = "DEMONSTRATE"
        progress.stage_status = "PENDING"
        db.commit()

        view = machine.view(machine.ensure(session_row.id))
        operation = machine.begin(
            session_row.id,
            TeachingAction(
                request_id=uuid4(),
                expected_revision=view["revision"],
                action="START",
            ),
            "test-model",
        )
        row = db.get(LearningSession, session_row.id)
        messages = teaching_protocol.build_messages(db, row, progress, operation, "")
        assert expected in messages[3]["content"]


def test_free_chat_messages_use_same_role_and_subject_strategy(db):
    course = Course(title="Python 入门", description="编程基础", status="active")
    db.add(course)
    db.flush()
    chapter = Chapter(course_id=course.id, title="循环")
    db.add(chapter)
    db.flush()
    point = KnowledgePoint(chapter_id=chapter.id, title="for 循环", content="for i in range(3): print(i)")
    db.add(point)
    db.commit()

    messages = prompt_assembler.free_chat_messages(course, chapter, point, [])
    assert "Mastery Lab 的耐心老师" in messages[0]["content"]
    assert "[学科策略]" in messages[1]["content"]
    assert messages[-1]["role"] == "user"
    assert "开始讲解" in messages[-1]["content"]
