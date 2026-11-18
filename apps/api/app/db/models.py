"""数据表定义。

P0：model_configs / app_settings。
P1.1：courses / chapters / knowledge_points。
P1.2：课程与知识点补 icon、last_studied_at 等字段（见 db/__init__._ensure_columns 的增量迁移）。
P1.3：learning_sessions / chat_messages（AI 学习教室的会话与消息）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
