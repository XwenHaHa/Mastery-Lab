"""P1.7-A/B：结构化活动生成、确定性评价、素材归属与四学科闭环。"""

from __future__ import annotations

import base64
import json
from uuid import uuid4

from sqlalchemy import select

from app.db.models import (
    Chapter,
    Course,
    KnowledgePoint,
    LearningSession,
    Material,
    TeachingActivityInstance,
)
from app.schemas.teaching import TeachingAction, TeachingTask
from app.services import activities, activity_protocol
from app.services.teaching_state import TeachingStateMachine

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lK3Q6wAAAABJRU5ErkJggg=="
)


def _begin(machine, session_id, action, content=""):
    view = machine.view(machine.ensure(session_id))
    return machine.begin(
        session_id,
        TeachingAction(
            request_id=uuid4(),
            expected_revision=view["revision"],
            action=action,
            content=content,
        ),
        "test-model",
    )


def _lesson(machine, session_id, action="START"):
    operation = _begin(machine, session_id, action)
    return machine.finish(operation.id, "老师的讲解内容。")


def _task(machine, session_id, task: TeachingTask, action="CONTINUE"):
    operation = _begin(machine, session_id, action)
    return machine.finish(operation.id, f"{task.instruction}\n\n{task.question}", task)


def _make_session(db, title: str, content: str):
    course = Course(title=title, description=title, status="active")
    db.add(course)
    db.flush()
    chapter = Chapter(course_id=course.id, title="示例章节")
    db.add(chapter)
    db.flush()
    point = KnowledgePoint(chapter_id=chapter.id, title=title, description=title, content=content)
    db.add(point)
    db.flush()
    session_row = LearningSession(course_id=course.id, knowledge_point_id=point.id)
    db.add(session_row)
    db.commit()
    return course, chapter, point, session_row


def _walk_to_check(db, machine, session_id):
    _lesson(machine, session_id)
    _lesson(machine, session_id, "CONTINUE")
    return machine


def _task_with_activity(question: str, activity: dict) -> TeachingTask:
    return TeachingTask(
        instruction="先阅读题目，再作答。",
        question=question,
        rubric="按标准答案判断",
        hint="回忆刚才的示例",
        summary="",
        activity=activity,
    )


def test_multiple_choice_is_persisted_and_scored_by_server(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    _walk_to_check(db, machine, session_id)
    task = _task_with_activity(
        "range(3) 的输出是什么？",
        {
            "type": "MULTIPLE_CHOICE",
            "title": "判断循环输出",
            "objective": "能预测循环次数",
            "content": [{"kind": "markdown", "text": "for i in range(3): print(i)"}],
            "interaction": {
                "inputKind": "CHOICE",
                "prompt": "选出正确输出",
                "payload": {
                    "options": [
                        {"id": "A", "label": "0 1 2"},
                        {"id": "B", "label": "1 2 3"},
                    ],
                    "correctOptionIds": ["A"],
                },
            },
            "evaluation": {"mode": "EXACT", "criteria": [{"id": "c1", "description": "选对", "weight": 1}]},
        },
    )
    view = _task(machine, session_id, task)
    assert view["currentActivity"]["activityType"] == "MULTIPLE_CHOICE"
    assert view["currentActivity"]["definition"]["interaction"]["payload"]["correctOptionIds"] == ["A"]

    db.expire_all()
    instance = db.scalars(
        select(TeachingActivityInstance).where(TeachingActivityInstance.session_id == session_id)
    ).one()
    assert instance.activity_type == "MULTIPLE_CHOICE"

    definition = activities.definition_for_question(db, session_id, instance.prompt_message_id)
    result = activity_protocol.evaluate_deterministic(definition, "[A]")
    assert result is not None and result.verdict == "CORRECT"
    judgment = activity_protocol.to_judgment(result, is_verify=False, student_input="[A]")

    operation = _begin(machine, session_id, "ANSWER", "[A]")
    view = machine.finish(operation.id, judgment.feedback, judgment)
    assert view["currentStage"] == "PAIR"


def test_invalid_structured_activity_degrades_with_reason(db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    _walk_to_check(db, machine, session_id)
    task = _task_with_activity(
        "选择正确答案。",
        {
            "type": "MULTIPLE_CHOICE",
            "title": "缺少选项",
            "interaction": {"inputKind": "CHOICE", "prompt": "选一个"},
            "evaluation": {"mode": "EXACT"},
        },
    )
    view = _task(machine, session_id, task)
    activity = view["currentActivity"]
    assert activity["activityType"] == "SHORT_ANSWER"
    assert activity["definition"]["meta"]["degraded"] is True
    assert "结构化活动" in activity["definition"]["meta"]["fallbackReason"]


def test_cross_course_material_reference_is_removed(db, seeded):
    other = Course(title="另一门课程", status="active")
    db.add(other)
    db.flush()
    foreign = Material(
        course_id=other.id,
        file_name="gear.png",
        relative_path="materials/foreign/gear.png",
        mime_type="image/png",
        kind="image",
        size_bytes=10,
        sha256="x",
    )
    db.add(foreign)
    db.commit()

    task = _task_with_activity(
        "观察齿轮图片并说明传动关系。",
        {
            "type": "IMAGE_ANALYSIS",
            "title": "齿轮结构识别",
            "content": [
                {"kind": "image", "materialId": foreign.id, "alt": "齿轮结构"},
                {"kind": "markdown", "text": "请描述主动轮与从动轮的关系。"},
            ],
            "materials": [{"materialId": foreign.id, "role": "primary"}],
            "interaction": {"inputKind": "SHORT_TEXT", "prompt": "你看到了什么？", "payload": {}},
            "evaluation": {"mode": "RUBRIC_AI", "criteria": [{"id": "c1", "description": "描述关系"}]},
        },
    )
    definition, warnings = activity_protocol.build_definition_from_task(
        task=task,
        stage="CHECK",
        knowledge_point_id=seeded["point"].id,
        point_title=seeded["point"].title,
        allowed_material_ids=set(),
    )
    assert warnings
    assert definition.materials == []
    assert all(block.kind != "image" for block in definition.content)
    assert definition.meta["materialWarnings"]


def test_deterministic_modes_cover_fill_order_and_numeric():
    fill = activity_protocol.TeachingActivityDefinition.model_validate(
        {
            "type": "FILL_IN_BLANK",
            "stage": "CHECK",
            "knowledgePointId": 1,
            "title": "过去式填空",
            "objective": "掌握一般过去时",
            "content": [{"kind": "markdown", "text": "Yesterday I ___ to school."}],
            "interaction": {
                "inputKind": "BLANKS",
                "prompt": "填写动词过去式",
                "payload": {
                    "blanks": [{"id": "b1", "label": "第 1 空", "acceptedAnswers": ["went", "walked"]}]
                },
            },
            "evaluation": {"mode": "NORMALIZED"},
        }
    )
    assert activity_protocol.evaluate_deterministic(fill, "第 1 空：Went").verdict == "CORRECT"
    assert activity_protocol.evaluate_deterministic(fill, "第 1 空：go").verdict == "INCORRECT"

    order = activity_protocol.TeachingActivityDefinition.model_validate(
        {
            "type": "STEP_ORDERING",
            "stage": "CHECK",
            "knowledgePointId": 1,
            "title": "齿轮装配顺序",
            "objective": "掌握装配步骤",
            "content": [],
            "interaction": {
                "inputKind": "ORDER",
                "prompt": "按正确顺序排列",
                "payload": {
                    "items": [
                        {"id": "1", "label": "清洁轴颈"},
                        {"id": "2", "label": "安装轴承"},
                        {"id": "3", "label": "压装齿轮"},
                    ],
                    "correctOrder": ["1", "2", "3"],
                },
            },
            "evaluation": {"mode": "EXACT"},
        }
    )
    assert activity_protocol.evaluate_deterministic(order, "[1]、[2]、[3]").verdict == "CORRECT"
    assert activity_protocol.evaluate_deterministic(order, "[2]、[1]、[3]").verdict == "PARTIAL"

    calc = activity_protocol.TeachingActivityDefinition.model_validate(
        {
            "type": "CALCULATION",
            "stage": "CHECK",
            "knowledgePointId": 1,
            "title": "解一元一次方程",
            "objective": "会解方程",
            "content": [{"kind": "latex", "expression": "2x+3=7"}],
            "interaction": {
                "inputKind": "CALCULATION",
                "prompt": "求 x",
                "payload": {"answer": "2", "tolerance": 0.001},
            },
            "evaluation": {"mode": "NUMERIC"},
        }
    )
    assert activity_protocol.evaluate_deterministic(calc, "x=2").verdict == "CORRECT"
    assert activity_protocol.evaluate_deterministic(calc, "x=3").verdict == "INCORRECT"


def test_four_subjects_share_one_teaching_flow(db):
    cases = [
        (
            "Python 编程：变量与赋值",
            "变量 赋值 代码 print",
            {
                "type": "MULTIPLE_CHOICE",
                "title": "变量赋值结果",
                "content": [{"kind": "code", "language": "python", "code": "x = 1\nx = x + 1\nprint(x)"}],
                "interaction": {
                    "inputKind": "CHOICE",
                    "prompt": "输出是什么？",
                    "payload": {
                        "options": [{"id": "A", "label": "1"}, {"id": "B", "label": "2"}],
                        "correctOptionIds": ["B"],
                    },
                },
                "evaluation": {"mode": "EXACT"},
            },
            "[B]",
        ),
        (
            "数学：一元一次方程",
            "方程 函数 求导 数学",
            {
                "type": "CALCULATION",
                "title": "解方程",
                "content": [{"kind": "latex", "expression": "2x+3=7"}],
                "interaction": {
                    "inputKind": "CALCULATION",
                    "prompt": "求 x",
                    "payload": {"answer": "2"},
                },
                "evaluation": {"mode": "NUMERIC"},
            },
            "2",
        ),
        (
            "英语：一般过去时",
            "英语 语法 单词 句型",
            {
                "type": "FILL_IN_BLANK",
                "title": "过去式填空",
                "content": [{"kind": "markdown", "text": "Yesterday I ___ to school."}],
                "interaction": {
                    "inputKind": "BLANKS",
                    "prompt": "填写 go 的过去式",
                    "payload": {
                        "blanks": [{"id": "b1", "label": "第 1 空", "acceptedAnswers": ["went"]}]
                    },
                },
                "evaluation": {"mode": "NORMALIZED"},
            },
            "第 1 空：went",
        ),
        (
            "机械设计：齿轮传动基础",
            "机械 装配 齿轮 传动 操作",
            {
                "type": "STEP_ORDERING",
                "title": "齿轮装配顺序",
                "content": [{"kind": "markdown", "text": "请按标准流程排列。"}],
                "interaction": {
                    "inputKind": "ORDER",
                    "prompt": "排序",
                    "payload": {
                        "items": [
                            {"id": "1", "label": "清洁轴颈"},
                            {"id": "2", "label": "安装轴承"},
                            {"id": "3", "label": "压装齿轮"},
                        ],
                        "correctOrder": ["1", "2", "3"],
                    },
                },
                "evaluation": {"mode": "EXACT"},
            },
            "[1]、[2]、[3]",
        ),
    ]

    for title, content, activity, answer in cases:
        _course, _chapter, _point, session_row = _make_session(db, title, content)
        machine = TeachingStateMachine(db)
        _walk_to_check(db, machine, session_row.id)
        task = _task_with_activity(f"{title} 的课堂任务", activity)
        view = _task(machine, session_row.id, task)
        assert view["currentStage"] == "CHECK"
        assert view["currentActivity"]["activityType"] == activity["type"]

        definition = activities.current_definition(db, machine.ensure(session_row.id))
        result = activity_protocol.evaluate_deterministic(definition, answer)
        assert result is not None and result.verdict == "CORRECT", title
        judgment = activity_protocol.to_judgment(result, is_verify=False, student_input=answer)
        operation = _begin(machine, session_row.id, "ANSWER", answer)
        view = machine.finish(operation.id, judgment.feedback, judgment)
        assert view["currentStage"] == "PAIR", title


def test_all_fourteen_activity_types_validate_and_keep_type(db, seeded):
    base = {
        "stage": "CHECK",
        "knowledgePointId": seeded["point"].id,
        "title": "活动",
        "objective": "完成活动",
        "content": [{"kind": "markdown", "text": "任务说明"}],
    }
    samples = {
        "TEXT_EXPLANATION": {
            "interaction": {"inputKind": "REFLECTION", "prompt": "说说你的理解", "payload": {}},
            "evaluation": {"mode": "NONE"},
        },
        "IMAGE_ANALYSIS": {
            "interaction": {"inputKind": "SHORT_TEXT", "prompt": "描述图片", "payload": {}},
            "evaluation": {"mode": "RUBRIC_AI"},
        },
        "FORMULA_DERIVATION": {
            "interaction": {"inputKind": "STEPS", "prompt": "写出推导", "payload": {}},
            "evaluation": {"mode": "RUBRIC_AI"},
        },
        "DIAGRAM_WALKTHROUGH": {
            "interaction": {"inputKind": "NONE", "prompt": "阅读图表", "payload": {}},
            "evaluation": {"mode": "NONE"},
        },
        "CODE_DEMO": {
            "interaction": {
                "inputKind": "PREDICT_OUTPUT",
                "prompt": "预测输出",
                "payload": {"expectedOutput": "2"},
            },
            "evaluation": {"mode": "EXACT"},
        },
        "MULTIPLE_CHOICE": {
            "interaction": {
                "inputKind": "CHOICE",
                "prompt": "选出答案",
                "payload": {
                    "options": [{"id": "A", "label": "甲"}, {"id": "B", "label": "乙"}],
                    "correctOptionIds": ["A"],
                },
            },
            "evaluation": {"mode": "EXACT"},
        },
        "FILL_IN_BLANK": {
            "interaction": {
                "inputKind": "BLANKS",
                "prompt": "填空",
                "payload": {"blanks": [{"id": "b1", "label": "第 1 空", "acceptedAnswers": ["x"]}]},
            },
            "evaluation": {"mode": "NORMALIZED"},
        },
        "SHORT_ANSWER": {
            "interaction": {"inputKind": "SHORT_TEXT", "prompt": "回答", "payload": {}},
            "evaluation": {"mode": "RUBRIC_AI"},
        },
        "STEP_ORDERING": {
            "interaction": {
                "inputKind": "ORDER",
                "prompt": "排序",
                "payload": {
                    "items": [{"id": "1", "label": "甲"}, {"id": "2", "label": "乙"}],
                    "correctOrder": ["1", "2"],
                },
            },
            "evaluation": {"mode": "EXACT"},
        },
        "CALCULATION": {
            "interaction": {"inputKind": "CALCULATION", "prompt": "计算", "payload": {"answer": "2"}},
            "evaluation": {"mode": "NUMERIC"},
        },
        "CONVERSATION": {
            "interaction": {"inputKind": "DIALOGUE", "prompt": "对话", "payload": {}},
            "evaluation": {"mode": "RUBRIC_AI"},
        },
        "PRACTICAL_TASK": {
            "interaction": {"inputKind": "DELIVERABLE", "prompt": "交付", "payload": {}},
            "evaluation": {"mode": "RUBRIC_AI"},
        },
        "AUDIO_EXERCISE": {
            "interaction": {
                "inputKind": "CHOICE",
                "prompt": "听并选择",
                "payload": {
                    "options": [{"id": "A", "label": "甲"}, {"id": "B", "label": "乙"}],
                    "correctOptionIds": ["B"],
                },
            },
            "evaluation": {"mode": "EXACT"},
        },
        "VIDEO_ANALYSIS": {
            "interaction": {"inputKind": "TIMESTAMP_ANSWER", "prompt": "指出时间点", "payload": {}},
            "evaluation": {"mode": "RUBRIC_AI"},
        },
    }

    for activity_type, part in samples.items():
        task = TeachingTask(
            instruction="先看材料。",
            question=f"{activity_type} 任务",
            rubric="按标准评价",
            hint="回忆示例",
            summary="",
            activity={"type": activity_type, **base, **part},
        )
        definition, warnings = activity_protocol.build_definition_from_task(
            task=task,
            stage="CHECK",
            knowledge_point_id=seeded["point"].id,
            point_title=seeded["point"].title,
            allowed_material_ids=set(),
        )
        assert definition.type == activity_type, (activity_type, warnings)
        assert definition.meta.get("degraded") is not True, (activity_type, warnings)


def test_deleted_material_keeps_activity_but_marks_missing(client, db, seeded):
    machine = TeachingStateMachine(db)
    session_id = seeded["session"].id
    _walk_to_check(db, machine, session_id)

    response = client.post(
        f"/api/v1/courses/{seeded['course'].id}/materials",
        files={"file": ("gear.png", PNG_1PX, "image/png")},
        data={"caption": "齿轮结构"},
    )
    assert response.status_code == 201
    material_id = response.json()["data"]["id"]

    task = _task_with_activity(
        "观察齿轮图片并说明传动关系。",
        {
            "type": "IMAGE_ANALYSIS",
            "title": "齿轮结构识别",
            "content": [
                {"kind": "image", "materialId": material_id, "alt": "齿轮结构"},
                {"kind": "markdown", "text": "请描述主动轮与从动轮的关系。"},
            ],
            "interaction": {"inputKind": "SHORT_TEXT", "prompt": "你看到了什么？", "payload": {}},
            "evaluation": {"mode": "RUBRIC_AI", "criteria": [{"id": "c1", "description": "描述关系"}]},
        },
    )
    _task(machine, session_id, task)

    current = client.get(f"/api/v1/classroom/sessions/{session_id}/teaching").json()["data"]["currentActivity"]
    assert current["materials"][0]["exists"] is True
    assert current["materials"][0]["url"].endswith(f"/materials/{material_id}/content")

    assert client.delete(f"/api/v1/materials/{material_id}").status_code == 200
    current = client.get(f"/api/v1/classroom/sessions/{session_id}/teaching").json()["data"]["currentActivity"]
    assert current["materials"][0]["exists"] is False
    # 历史活动定义不被删除。
    assert current["definition"]["content"][0]["materialId"] == material_id

    db.expire_all()
    instance = db.scalars(
        select(TeachingActivityInstance).where(TeachingActivityInstance.session_id == session_id)
    ).one()
    assert json.loads(instance.definition_json)["content"][0]["materialId"] == material_id
