"""教学阶段元数据（P1.6-A）。

阶段只描述「教学流程走到哪一步」，不描述「学生具体做什么」。
- v1 是 P1.4 的六阶段，历史会话继续使用；
- v2 是 P1.6 的八阶段通用流程，由 pipeline_version 特性开关启用。

本模块只包含纯数据与纯函数，不依赖数据库，便于状态机、提示词、档案和 API 共用。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

PIPELINE_V1 = 1
PIPELINE_V2 = 2
SUPPORTED_VERSIONS = (PIPELINE_V1, PIPELINE_V2)

# 活动家族的固定取值。评价、错题、掌握度等旧逻辑按家族兼容新阶段。
FAMILY_LESSON = "lesson"
FAMILY_CHECK = "check"
FAMILY_PRACTICE = "practice"
FAMILY_VERIFY = "verify"
FAMILY_CONSOLIDATE = "consolidate"
FAMILY_NEXT = "next"


@dataclass(frozen=True)
class StageDefinition:
    key: str
    label: str
    goal: str
    order: int
    family: str
    optional: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


STAGES_V1: tuple[StageDefinition, ...] = (
    StageDefinition("TEACH", "讲解", "理解这个知识点是什么、为什么需要它。", 1, FAMILY_LESSON),
    StageDefinition("DEMO", "演示", "看完整的小案例，理解关键语句和预期输出。", 2, FAMILY_LESSON),
    StageDefinition("CHECK", "理解检查", "用一个回答说明你对当前知识点的理解。", 3, FAMILY_CHECK),
    StageDefinition("PAIR", "共同实践", "在老师引导下，逐步完成两个小步骤。", 4, FAMILY_PRACTICE),
    StageDefinition("VERIFY", "独立验证", "独立提交解释或练习结果，验证当前理解。", 5, FAMILY_VERIFY),
    StageDefinition("NEXT", "本节总结", "回顾本节学习结果，自主决定是否学习下一节。", 6, FAMILY_NEXT),
)

STAGES_V2: tuple[StageDefinition, ...] = (
    StageDefinition("UNDERSTAND", "认识问题", "先弄清这个知识点解决什么问题、在什么场景使用。", 1, FAMILY_LESSON),
    StageDefinition("TEACH", "讲解", "理解核心概念、术语和关键原理。", 2, FAMILY_LESSON),
    StageDefinition("DEMONSTRATE", "示范演示", "看一个完整示例，理解每一步的依据和结果。", 3, FAMILY_LESSON),
    StageDefinition("INTERACT", "互动检查", "用一个互动任务确认你是否真正理解。", 4, FAMILY_CHECK),
    StageDefinition("PRACTICE", "引导练习", "在老师引导下分步完成练习。", 5, FAMILY_PRACTICE),
    StageDefinition("VERIFY", "独立验证", "独立完成任务，验证本轮掌握程度。", 6, FAMILY_VERIFY),
    StageDefinition("CONSOLIDATE", "巩固总结", "总结关键点、易错点和后续联系。", 7, FAMILY_CONSOLIDATE, optional=True),
    StageDefinition("NEXT", "本节完成", "本轮教学结束，决定继续下一节或回顾。", 8, FAMILY_NEXT),
)

PIPELINES: dict[int, tuple[StageDefinition, ...]] = {
    PIPELINE_V1: STAGES_V1,
    PIPELINE_V2: STAGES_V2,
}

_BY_VERSION: dict[int, dict[str, StageDefinition]] = {
    version: {stage.key: stage for stage in stages} for version, stages in PIPELINES.items()
}

# 旧阶段值到活动家族的映射；v2 阶段直接使用自身 family。
_LEGACY_FAMILY: dict[str, str] = {stage.key: stage.family for stage in STAGES_V1}
_V2_FAMILY: dict[str, str] = {stage.key: stage.family for stage in STAGES_V2}


def normalize_version(value: int | None) -> int:
    """未知或空版本一律按 v1 处理，保证旧数据不会被误升级。"""
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return PIPELINE_V1
    return number if number in SUPPORTED_VERSIONS else PIPELINE_V1


def stages_for(version: int | None) -> tuple[StageDefinition, ...]:
    return PIPELINES[normalize_version(version)]


def stage_definitions(version: int | None) -> list[dict]:
    return [stage.as_dict() for stage in stages_for(version)]


def stage_keys(version: int | None) -> tuple[str, ...]:
    return tuple(stage.key for stage in stages_for(version))


def stage_map(version: int | None) -> dict[str, StageDefinition]:
    return _BY_VERSION[normalize_version(version)]


def is_known(stage: str | None, version: int | None) -> bool:
    return bool(stage) and stage in stage_map(version)


def stage_definition(stage: str, version: int | None) -> StageDefinition | None:
    return stage_map(version).get(stage)


def goal_for(stage: str, version: int | None) -> str:
    definition = stage_definition(stage, version)
    if definition is not None:
        return definition.goal
    # 阶段值来自旧数据或未来版本时，不抛异常，返回可展示的兜底文案。
    return "按当前教学步骤继续学习。"


def index_of(stage: str, version: int | None) -> int:
    keys = stage_keys(version)
    return keys.index(stage) if stage in keys else -1


def family_of(stage: str | None) -> str:
    if not stage:
        return FAMILY_LESSON
    return _V2_FAMILY.get(stage) or _LEGACY_FAMILY.get(stage) or FAMILY_LESSON


def is_lesson(stage: str | None) -> bool:
    return family_of(stage) in (FAMILY_LESSON, FAMILY_CONSOLIDATE)


def is_task(stage: str | None) -> bool:
    return family_of(stage) in (FAMILY_CHECK, FAMILY_PRACTICE, FAMILY_VERIFY)


def is_verify(stage: str | None) -> bool:
    return family_of(stage) == FAMILY_VERIFY


def is_next(stage: str | None) -> bool:
    return family_of(stage) == FAMILY_NEXT


def evaluation_stage_key(stage: str | None) -> str:
    """把任意版本的阶段映射到旧评价语义（CHECK / PAIR / VERIFY）。

    错题分类、掌握度推导继续复用 P1.5 的规则，避免为 v2 再复制一套判断。
    """
    family = family_of(stage)
    if family == FAMILY_CHECK:
        return "CHECK"
    if family == FAMILY_PRACTICE:
        return "PAIR"
    if family == FAMILY_VERIFY:
        return "VERIFY"
    if family == FAMILY_NEXT:
        return "NEXT"
    return "TEACH"


def state_stage_key(stage: str | None) -> str:
    """掌握度推导使用的阶段语义；巩固阶段按已进入结束段处理。"""
    if family_of(stage) in (FAMILY_CONSOLIDATE, FAMILY_NEXT):
        return "NEXT"
    return evaluation_stage_key(stage)


def first_lesson_stage(version: int | None) -> str:
    for stage in stages_for(version):
        if stage.family in (FAMILY_LESSON, FAMILY_CONSOLIDATE):
            return stage.key
    return stages_for(version)[0].key


def reteach_stage(version: int | None) -> str:
    """需要重新讲解时回到的阶段；v2 回到 TEACH，v1 同样回到 TEACH。"""
    definitions = stage_map(version)
    if "TEACH" in definitions:
        return "TEACH"
    return first_lesson_stage(version)


def pipeline_payload(default_version: int | None = None) -> dict:
    return {
        "defaultPipelineVersion": normalize_version(default_version),
        "pipelines": {
            str(version): [stage.as_dict() for stage in stages]
            for version, stages in PIPELINES.items()
        },
    }
