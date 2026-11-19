"""P1.6-A：阶段元数据、学科策略、活动协议与元数据 API。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services import activity_protocol, subject_profiles, teaching_stages


def test_pipeline_versions_are_stable():
    v1 = teaching_stages.stage_keys(1)
    v2 = teaching_stages.stage_keys(2)
    assert v1 == ("TEACH", "DEMO", "CHECK", "PAIR", "VERIFY", "NEXT")
    assert v2 == (
        "UNDERSTAND",
        "TEACH",
        "DEMONSTRATE",
        "INTERACT",
        "PRACTICE",
        "VERIFY",
        "CONSOLIDATE",
        "NEXT",
    )
    assert teaching_stages.normalize_version(None) == 1
    assert teaching_stages.normalize_version(99) == 1


def test_stage_metadata_has_labels_and_goals():
    for version in (1, 2):
        for stage in teaching_stages.stages_for(version):
            assert stage.label and stage.goal
            assert stage.order >= 1
    assert teaching_stages.goal_for("UNKNOWN", 2)
    assert teaching_stages.is_known("UNKNOWN", 2) is False


def test_stage_families_map_to_legacy_evaluation_semantics():
    assert teaching_stages.evaluation_stage_key("INTERACT") == "CHECK"
    assert teaching_stages.evaluation_stage_key("PRACTICE") == "PAIR"
    assert teaching_stages.evaluation_stage_key("VERIFY") == "VERIFY"
    assert teaching_stages.state_stage_key("CONSOLIDATE") == "NEXT"
    assert teaching_stages.state_stage_key("PAIR") == "PAIR"


def test_subject_profiles_cover_five_domains():
    keys = {profile.key for profile in subject_profiles.PROFILES.values()}
    assert keys == {"programming", "math", "language", "theory", "practice"}
    for profile in subject_profiles.PROFILES.values():
        assert profile.preferred_activities
        assert profile.mastery_evidence


def test_activity_protocol_accepts_multiple_choice():
    definition = activity_protocol.TeachingActivityDefinition.model_validate(
        {
            "schemaVersion": 1,
            "type": "MULTIPLE_CHOICE",
            "stage": "INTERACT",
            "knowledgePointId": 1,
            "title": "选择正确说法",
            "objective": "确认概念边界",
            "content": [{"kind": "markdown", "text": "阅读后选择一个答案。"}],
            "interaction": {
                "inputKind": "CHOICE",
                "prompt": "下面哪个说法正确？",
                "payload": {
                    "options": [
                        {"id": "a", "label": "选项 A"},
                        {"id": "b", "label": "选项 B"},
                    ],
                    "correctOptionIds": ["b"],
                    "multiple": False,
                },
            },
            "evaluation": {
                "mode": "EXACT",
                "passThreshold": 1,
                "criteria": [
                    {"id": "c1", "description": "选中 B", "weight": 1, "required": True}
                ],
                "evidenceRule": "SELECTION",
                "allowHints": True,
                "maxHints": 2,
                "hintPenalty": "NONE",
                "feedbackPolicy": "IMMEDIATE",
            },
            "applicable": True,
            "difficulty": 2,
        }
    )
    assert definition.interaction.input_kind == "CHOICE"
    assert definition.evaluation.mode == "EXACT"


def test_activity_protocol_rejects_invalid_contracts():
    base = {
        "type": "MULTIPLE_CHOICE",
        "stage": "INTERACT",
        "knowledgePointId": 1,
        "title": "题目",
        "objective": "目标",
        "interaction": {
            "inputKind": "CHOICE",
            "prompt": "请选择",
            "payload": {"options": [{"id": "a"}], "correctOptionIds": ["a"]},
        },
        "evaluation": {"mode": "EXACT"},
    }
    with pytest.raises(ValidationError):
        activity_protocol.TeachingActivityDefinition.model_validate(base)

    mismatched = {
        **base,
        "interaction": {
            "inputKind": "SHORT_TEXT",
            "prompt": "请选择",
            "payload": {},
        },
    }
    with pytest.raises(ValidationError):
        activity_protocol.TeachingActivityDefinition.model_validate(mismatched)

    extra = {
        **base,
        "interaction": {
            "inputKind": "CHOICE",
            "prompt": "请选择",
            "payload": {
                "options": [{"id": "a"}, {"id": "b"}],
                "correctOptionIds": ["a"],
            },
        },
        "evaluation": {"mode": "EXACT"},
        "unknownField": True,
    }
    with pytest.raises(ValidationError):
        activity_protocol.TeachingActivityDefinition.model_validate(extra)


def test_activity_definition_from_legacy_task():
    definition = activity_protocol.definition_from_task(
        instruction="先说明你的理解。",
        question="这个变量为什么从 0 开始？",
        rubric="能说明累加器初始化",
        hint="想想累加前的结果",
        summary="",
        stage="CHECK",
        knowledge_point_id=7,
    )
    assert definition.type == "SHORT_ANSWER"
    assert definition.interaction.input_kind == "SHORT_TEXT"
    assert definition.evaluation.evidence_rule == "QUOTE"
    assert definition.knowledge_point_id == 7


def test_meta_api_exposes_metadata(client):
    response = client.get("/api/v1/meta/teaching")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["defaultPipelineVersion"] == 1
    assert set(payload["pipelines"]) == {"1", "2"}
    assert len(payload["pipelines"]["2"]) == 8
    assert len(payload["activityTypes"]) == 14
    assert len(payload["subjectProfiles"]) == 5
