"""学科教学策略预设（P1.6-A，只读）。

策略只影响「怎么讲、举什么例子、用什么活动、如何判断掌握」，
不直接控制阶段迁移。P1.6-D 才会把它接入提示词组装。
"""

from __future__ import annotations

from dataclasses import dataclass

SUBJECT_PROGRAMMING = "programming"
SUBJECT_MATH = "math"
SUBJECT_LANGUAGE = "language"
SUBJECT_THEORY = "theory"
SUBJECT_PRACTICE = "practice"


@dataclass(frozen=True)
class SubjectProfile:
    key: str
    label: str
    description: str
    explanation_style: str
    example_strategy: str
    preferred_activities: tuple[str, ...]
    practice_design: str
    mastery_evidence: str

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "explanationStyle": self.explanation_style,
            "exampleStrategy": self.example_strategy,
            "preferredActivities": list(self.preferred_activities),
            "practiceDesign": self.practice_design,
            "masteryEvidence": self.mastery_evidence,
        }


PROFILES: dict[str, SubjectProfile] = {
    SUBJECT_PROGRAMMING: SubjectProfile(
        key=SUBJECT_PROGRAMMING,
        label="编程",
        description="以可读代码、输入输出和调试过程为主要证据。",
        explanation_style="先讲问题与目标，再讲关键概念，最后落到可读的最小代码。",
        example_strategy="使用完整、可运行、与知识点直接相关的小案例，并标注预期输出。",
        preferred_activities=("CODE_DEMO", "SHORT_ANSWER", "PRACTICAL_TASK", "FILL_IN_BLANK"),
        practice_design="从读代码、补全一小步到独立写一个小函数，逐步减少提示。",
        mastery_evidence="能解释关键语句，并在无提示情况下独立完成一个小任务。",
    ),
    SUBJECT_MATH: SubjectProfile(
        key=SUBJECT_MATH,
        label="数学",
        description="以公式、推导步骤和计算结果为主要证据。",
        explanation_style="先说明结论的用途，再从定义出发推导，明确每一步的依据。",
        example_strategy="使用一个完整例题，展示条件、推导、计算和验证四个环节。",
        preferred_activities=("FORMULA_DERIVATION", "CALCULATION", "STEP_ORDERING", "SHORT_ANSWER"),
        practice_design="先补全推导步骤，再做同类计算，最后独立解一道变式题。",
        mastery_evidence="能写出关键推导步骤，并在容差范围内得到正确结果。",
    ),
    SUBJECT_LANGUAGE: SubjectProfile(
        key=SUBJECT_LANGUAGE,
        label="语言",
        description="以听、说、读、写任务和语境理解为主要证据。",
        explanation_style="先给出真实语境，再讲表达结构、词汇和常见错误。",
        example_strategy="使用一段对话或短文，标出目标表达并解释使用场景。",
        preferred_activities=("TEXT_EXPLANATION", "AUDIO_EXERCISE", "FILL_IN_BLANK", "CONVERSATION"),
        practice_design="从跟读、替换练习到情景对话，逐级减少提示。",
        mastery_evidence="能在新语境中正确使用目标表达，并说明使用理由。",
    ),
    SUBJECT_THEORY: SubjectProfile(
        key=SUBJECT_THEORY,
        label="理论知识",
        description="以概念关系、因果解释和结构化复述为主要证据。",
        explanation_style="先建立时间线或概念图，再讲关键人物、事件和因果关系。",
        example_strategy="使用一个典型案例或史料片段，示范如何提取论点和证据。",
        preferred_activities=("TEXT_EXPLANATION", "DIAGRAM_WALKTHROUGH", "MULTIPLE_CHOICE", "SHORT_ANSWER"),
        practice_design="先做概念辨析，再用自己的话复述因果链，最后分析新材料。",
        mastery_evidence="能准确复述核心概念，并用证据解释一个新问题。",
    ),
    SUBJECT_PRACTICE: SubjectProfile(
        key=SUBJECT_PRACTICE,
        label="实践操作",
        description="以操作步骤、交付物和检查清单为主要证据。",
        explanation_style="先说明操作目标与安全边界，再按步骤演示关键动作。",
        example_strategy="完整演示一次标准操作，标出检查点和常见失误。",
        preferred_activities=("DIAGRAM_WALKTHROUGH", "STEP_ORDERING", "PRACTICAL_TASK", "VIDEO_ANALYSIS"),
        practice_design="先排序操作步骤，再在清单辅助下完成，最后独立交付。",
        mastery_evidence="能按正确顺序独立完成操作，交付物通过检查清单。",
    ),
}

DEFAULT_PROFILE_KEY = SUBJECT_PROGRAMMING


def get_profile(key: str | None) -> SubjectProfile:
    return PROFILES.get(key or "", PROFILES[DEFAULT_PROFILE_KEY])


def payload() -> list[dict]:
    return [profile.as_dict() for profile in PROFILES.values()]
