"""通用教学编排器（P1.6-C）。

阶段契约负责回答：
- 这个阶段的下一个阶段是谁；失败时回到哪里；
- 允许哪些评价结果；通过/部分/失败分别怎么处理；
- 一个阶段需要几次活动、是否允许提示、是否可选。

旧 v1 契约严格复刻 P1.4 行为；v2 使用八阶段通用流程。
本模块不写数据库、不调用模型，只返回「计划」，由状态机执行。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import teaching_stages as stages

VERDICT_PASS = "PASSED"
VERDICT_NEEDS_REVIEW = "NEEDS_REVIEW"
VERDICT_FAILED = "FAILED"
VERDICT_CORRECT = "CORRECT"
VERDICT_PARTIAL = "PARTIAL"
VERDICT_INCORRECT = "INCORRECT"
VERDICT_UNCLEAR = "UNCLEAR"


@dataclass(frozen=True)
class StageContract:
    key: str
    family: str
    goal: str
    next_stage: str | None
    backstage: str | None = None
    min_activities: int = 1
    required_activity_types: tuple[str, ...] = ()
    allow_hints: bool = True
    optional: bool = False
    pair_steps: int = 1
    pass_verdicts: tuple[str, ...] = ()
    partial_verdicts: tuple[str, ...] = ()
    fail_verdicts: tuple[str, ...] = ()

    @property
    def is_lesson(self) -> bool:
        return self.family in (stages.FAMILY_LESSON, stages.FAMILY_CONSOLIDATE)

    @property
    def is_task(self) -> bool:
        return self.family in (stages.FAMILY_CHECK, stages.FAMILY_PRACTICE, stages.FAMILY_VERIFY)


@dataclass
class Transition:
    """一次评价后的执行计划。"""

    complete_stage: bool = False
    move_to: str | None = None
    retry: bool = False
    advance_activity: bool = False
    mastery_state: str | None = None
    finished: bool = False
    summary_from_result: bool = False


def _contracts(version: int) -> dict[str, StageContract]:
    if version == stages.PIPELINE_V1:
        return {
            "TEACH": StageContract(
                key="TEACH", family=stages.FAMILY_LESSON,
                goal=stages.goal_for("TEACH", version), next_stage="DEMO",
            ),
            "DEMO": StageContract(
                key="DEMO", family=stages.FAMILY_LESSON,
                goal=stages.goal_for("DEMO", version), next_stage="CHECK",
            ),
            "CHECK": StageContract(
                key="CHECK", family=stages.FAMILY_CHECK,
                goal=stages.goal_for("CHECK", version), next_stage="PAIR", backstage="TEACH",
                pass_verdicts=(VERDICT_CORRECT,), partial_verdicts=(VERDICT_PARTIAL,),
                fail_verdicts=(VERDICT_INCORRECT,),
            ),
            "PAIR": StageContract(
                key="PAIR", family=stages.FAMILY_PRACTICE,
                goal=stages.goal_for("PAIR", version), next_stage="VERIFY", backstage="DEMO",
                pair_steps=2, pass_verdicts=(VERDICT_CORRECT,),
                partial_verdicts=(VERDICT_PARTIAL,), fail_verdicts=(VERDICT_INCORRECT,),
            ),
            "VERIFY": StageContract(
                key="VERIFY", family=stages.FAMILY_VERIFY,
                goal=stages.goal_for("VERIFY", version), next_stage="NEXT", backstage="PAIR",
                pass_verdicts=(VERDICT_PASS,), partial_verdicts=(),
                fail_verdicts=(VERDICT_FAILED, VERDICT_NEEDS_REVIEW),
            ),
            "NEXT": StageContract(
                key="NEXT", family=stages.FAMILY_NEXT,
                goal=stages.goal_for("NEXT", version), next_stage=None,
            ),
        }
    return {
        "UNDERSTAND": StageContract(
            key="UNDERSTAND", family=stages.FAMILY_LESSON,
            goal=stages.goal_for("UNDERSTAND", version), next_stage="TEACH",
        ),
        "TEACH": StageContract(
            key="TEACH", family=stages.FAMILY_LESSON,
            goal=stages.goal_for("TEACH", version), next_stage="DEMONSTRATE",
        ),
        "DEMONSTRATE": StageContract(
            key="DEMONSTRATE", family=stages.FAMILY_LESSON,
            goal=stages.goal_for("DEMONSTRATE", version), next_stage="INTERACT",
        ),
        "INTERACT": StageContract(
            key="INTERACT", family=stages.FAMILY_CHECK,
            goal=stages.goal_for("INTERACT", version), next_stage="PRACTICE", backstage="TEACH",
            pass_verdicts=(VERDICT_CORRECT,), partial_verdicts=(VERDICT_PARTIAL,),
            fail_verdicts=(VERDICT_INCORRECT,),
        ),
        "PRACTICE": StageContract(
            key="PRACTICE", family=stages.FAMILY_PRACTICE,
            goal=stages.goal_for("PRACTICE", version), next_stage="VERIFY", backstage="DEMONSTRATE",
            pair_steps=2, pass_verdicts=(VERDICT_CORRECT,),
            partial_verdicts=(VERDICT_PARTIAL,), fail_verdicts=(VERDICT_INCORRECT,),
        ),
        "VERIFY": StageContract(
            key="VERIFY", family=stages.FAMILY_VERIFY,
            goal=stages.goal_for("VERIFY", version), next_stage="CONSOLIDATE", backstage="PRACTICE",
            pass_verdicts=(VERDICT_PASS,), partial_verdicts=(),
            fail_verdicts=(VERDICT_FAILED, VERDICT_NEEDS_REVIEW),
        ),
        "CONSOLIDATE": StageContract(
            key="CONSOLIDATE", family=stages.FAMILY_CONSOLIDATE,
            goal=stages.goal_for("CONSOLIDATE", version), next_stage="NEXT", optional=True,
        ),
        "NEXT": StageContract(
            key="NEXT", family=stages.FAMILY_NEXT,
            goal=stages.goal_for("NEXT", version), next_stage=None,
        ),
    }


class TeachingPipeline:
    def __init__(self, version: int | None = 1):
        self.version = stages.normalize_version(version)
        self.stage_keys = stages.stage_keys(self.version)
        self.contracts = _contracts(self.version)

    # ---- 只读查询 ----
    def contract(self, stage: str | None) -> StageContract:
        key = stage if stage in self.contracts else self.stage_keys[0]
        return self.contracts[key]

    def next_of(self, stage: str | None) -> str | None:
        return self.contract(stage).next_stage

    def backstage_of(self, stage: str | None) -> str | None:
        return self.contract(stage).backstage

    def index(self, stage: str | None) -> int:
        return self.stage_keys.index(stage) if stage in self.stage_keys else -1

    def is_lesson(self, stage: str | None) -> bool:
        return self.contract(stage).is_lesson

    def is_task(self, stage: str | None) -> bool:
        return self.contract(stage).is_task

    def is_verify(self, stage: str | None) -> bool:
        return self.contract(stage).family == stages.FAMILY_VERIFY

    def pair_steps(self, stage: str | None) -> int:
        return self.contract(stage).pair_steps

    def task_role(self, stage: str | None) -> str:
        return stages.evaluation_stage_key(stage)

    def reteach_stage(self) -> str:
        return "TEACH" if "TEACH" in self.stage_keys else self.stage_keys[0]

    def first_stage(self) -> str:
        return self.stage_keys[0]

    def allowed_verdicts(self, stage: str | None) -> set[str]:
        contract = self.contract(stage)
        if contract.family == stages.FAMILY_VERIFY:
            return {"PASSED", "NEEDS_REVIEW", "FAILED", "UNCLEAR"}
        if contract.family in (stages.FAMILY_CHECK, stages.FAMILY_PRACTICE):
            return {"CORRECT", "PARTIAL", "INCORRECT", "UNCLEAR"}
        return set()

    # ---- 动作与迁移计划 ----
    def allowed_actions(self, progress) -> list[str]:
        if progress.paused:
            return ["RESUME"]
        if progress.stage_status == "ACTIVE":
            return ["PAUSE"]
        stage = progress.current_stage
        contract = self.contract(stage)
        actions = ["ASK", "PAUSE"]
        if contract.family == stages.FAMILY_NEXT:
            return actions + ["NEXT", "RESTART"]
        actions += ["EXPLAIN_AGAIN", "CHANGE_EXAMPLE", "DONT_UNDERSTAND", "GIVE_HINT"]
        if progress.stage_status in ("PENDING", "BLOCKED"):
            actions += ["START", "REGENERATE"]
        elif contract.is_lesson and progress.stage_status == "COMPLETED":
            actions += ["CONTINUE", "REGENERATE"]
            if stage in ("DEMO", "DEMONSTRATE"):
                actions += ["TRY_MYSELF"]
        elif progress.current_question:
            actions += ["ANSWER", "REGENERATE", "TRY_MYSELF"]
        return actions

    def transition(self, progress, stage: str, verdict: str) -> Transition:
        contract = self.contract(stage)
        if verdict == VERDICT_UNCLEAR:
            return Transition(retry=True)
        if verdict in contract.pass_verdicts:
            if contract.pair_steps > 1 and progress.pair_step < contract.pair_steps:
                return Transition(
                    advance_activity=True,
                    mastery_state="GUIDED_PRACTICE",
                )
            return Transition(
                complete_stage=True,
                move_to=contract.next_stage,
                mastery_state="GUIDED_PRACTICE" if progress.verify_hint_count else "INDEPENDENT",
                finished=contract.family == stages.FAMILY_VERIFY,
                summary_from_result=contract.family == stages.FAMILY_VERIFY,
            )
        if verdict in contract.partial_verdicts:
            return Transition(retry=True, mastery_state="UNDERSTANDING")
        if verdict in contract.fail_verdicts:
            return Transition(
                move_to=contract.backstage,
                mastery_state="NEEDS_REVIEW",
            )
        return Transition(retry=True)
