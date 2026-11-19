"""数据表定义。

P0：model_configs / app_settings。
P1.1：courses / chapters / knowledge_points。
P1.2：课程与知识点补 icon、last_studied_at 等字段（见 db/__init__._ensure_columns 的增量迁移）。
P1.3：learning_sessions / chat_messages（AI 学习教室的会话与消息）。
P1.4：teaching_progress / teaching_operations / teaching_events / teaching_evaluations。
P1.5：learning_activities / mastery_history / mistake_records / mistake_occurrences /
      learning_breakpoints / learning_events，知识点补 mastery_state（增量加列）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ModelConfig(Base):
    """一条 OpenAI 兼容 API 的模型接入配置。

    api_key_cipher 只存密文；新写入的 api_key_hint 为固定掩码，不含密钥字符。
    """

    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)

    api_key_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_hint: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    api_key_scheme: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_message: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ModelConfig id={self.id} name={self.name!r} model={self.model_name!r}>"


class AppSetting(Base):
    """轻量键值表，P0 只用于记录 schema 版本等运行时元信息。"""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class Course(Base):
    """一门课程（P1.1 教材导入产物，P1.2 增加学习统计字段）。

    status='draft'  ：解析得到的建议结构，只出现在导入流程里，不进课程中心；
    status='active' ：用户确认后的正式课程。
    source_file 存相对 data 目录的路径，绝不存绝对路径，避免换机器后失效。
    icon 是单字符图标（用户可从预设里换），空串表示用来源类型（MD/PDF）做徽标。
    last_studied_at 由知识点状态变更时刷新，用于课程列表的「最近学习」排序。
    """

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="markdown")
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_file: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    icon: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    # JSON 文本：解析统计与警告（例如扫描版 PDF 提示）
    parse_meta: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    last_studied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="Chapter.sort_order",
        lazy="selectin",
    )


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    code_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    course: Mapped[Course] = relationship(back_populates="chapters")
    knowledge_points: Mapped[list["KnowledgePoint"]] = relationship(
        back_populates="chapter",
        cascade="all, delete-orphan",
        order_by="KnowledgePoint.sort_order",
        lazy="selectin",
    )


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    code_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # P1.2 学习状态：not_started / in_progress / completed / review（见 services/learning.py）
    mastery_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    learning_status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_started")
    completion_source: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_studied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # P1.5 掌握状态：NOT_STARTED / INTRODUCED / UNDERSTANDING / GUIDED_PRACTICE /
    # INDEPENDENT / NEEDS_REVIEW（见 services/mastery.py），只由教学证据更新。
    mastery_state: Mapped[str] = mapped_column(String(24), nullable=False, default="NOT_STARTED")
    mastery_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    chapter: Mapped[Chapter] = relationship(back_populates="knowledge_points")


class LearningSession(Base):
    """某个知识点上的一次学习会话（P1.3）。

    一个知识点对应一条会话，重新进入教室时复用它，因此历史对话不会丢。
    model_config_id 只是「上次用的模型配置」，为空时按当前默认模型解析；
    模型配置被删除时置空，不影响已经产生的对话。
    """

    __tablename__ = "learning_sessions"
    __table_args__ = (
        UniqueConstraint("course_id", "knowledge_point_id", name="uq_learning_sessions_course_point"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_config_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True
    )

    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
        lazy="selectin",
    )


class ChatMessage(Base):
    """会话里的一条消息。

    role 只存 user / assistant；system 提示词每次请求时重新组装，不落库。
    status 用于表达「这条回答是否完整」：
    - streaming：正在生成（进程异常退出时会残留，读取时按 interrupted 展示）；
    - completed：正常结束；
    - interrupted：用户点了停止或断开连接，content 是已经生成的部分；
    - failed：上游模型报错，content 可能为空或只有部分内容。
    """

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    model_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    session: Mapped[LearningSession] = relationship(back_populates="messages")


class TeachingProgress(Base):
    __tablename__ = "teaching_progress"

    session_id: Mapped[int] = mapped_column(ForeignKey("learning_sessions.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_stage: Mapped[str] = mapped_column(String(16), nullable=False, default="TEACH")
    stage_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_stages: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    current_question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    question_message_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    rubric: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pair_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    check_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pair_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verify_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verify_hint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    backtrack_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mastery_state: Mapped[str] = mapped_column(String(24), nullable=False, default="INTRODUCED")
    verification_result: Mapped[str | None] = mapped_column(String(24), nullable=True)
    legacy_completion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    stage_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TeachingOperation(Base):
    __tablename__ = "teaching_operations"
    __table_args__ = (UniqueConstraint("session_id", "request_id", name="uq_teaching_request"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    user_message_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    assistant_message_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    question_message_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    previous_status: Mapped[str] = mapped_column(String(24), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TeachingEvent(Base):
    __tablename__ = "teaching_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_operations.id", ondelete="CASCADE"), nullable=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_stage: Mapped[str] = mapped_column(String(16), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class TeachingEvaluation(Base):
    __tablename__ = "teaching_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[int] = mapped_column(ForeignKey("teaching_operations.id", ondelete="CASCADE"), nullable=False, unique=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    hint_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class LearningActivity(Base):
    """一次可统计的学习活动（P1.5）。

    有效时长只来自客户端心跳累计的 active_seconds，而不是「页面打开到关闭」的墙钟时间。
    每个会话同时只允许一条 active 记录（SQLite 部分唯一索引兜底），
    空闲超时后由服务层关闭为 interrupted，下一次进入重新开始。
    """

    __tablename__ = "learning_activities"
    __table_args__ = (
        Index(
            "uq_learning_activities_active_session",
            "session_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    result: Mapped[str] = mapped_column(String(24), nullable=False, default="in_progress")
    end_reason: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    active_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heartbeat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    final_stage: Mapped[str] = mapped_column(String(16), nullable=False, default="TEACH")
    completed_stages: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    check_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pair_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verify_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verify_hint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class MasteryHistory(Base):
    """知识点掌握状态的变化历史（P1.5），只由教学证据写入。"""

    __tablename__ = "mastery_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="SET NULL"), nullable=True
    )
    activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_activities.id", ondelete="SET NULL"), nullable=True
    )
    from_state: Mapped[str] = mapped_column(String(24), nullable=False)
    to_state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)


class MistakeRecord(Base):
    """错题 / 薄弱点（P1.5）。同一知识点重复出现的相同错误归并到一条记录。"""

    __tablename__ = "mistake_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_activities.id", ondelete="SET NULL"), nullable=True
    )

    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    error_type: Mapped[str] = mapped_column(String(24), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    user_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    correction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    misconceptions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class MistakeOccurrence(Base):
    """错题每次发生的历史明细，归并后仍可逐次追溯。"""

    __tablename__ = "mistake_occurrences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mistake_id: Mapped[int] = mapped_column(
        ForeignKey("mistake_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_activities.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    user_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class LearningBreakpoint(Base):
    """断点续学快照（P1.5）。每个学习会话一条，与 teaching_progress 互为补充。"""

    __tablename__ = "learning_breakpoints"

    session_id: Mapped[int] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_activities.id", ondelete="SET NULL"), nullable=True
    )

    current_stage: Mapped[str] = mapped_column(String(16), nullable=False, default="TEACH")
    stage_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    input_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="ASK")
    draft_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    completed_stages: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    pair_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    check_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pair_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verify_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verify_hint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    last_assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    last_assistant_excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")

    client_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class LearningEvent(Base):
    """学习活动层面的关键事件；阶段迁移与评价仍以 teaching_events / teaching_evaluations 为准。"""

    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_activities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
