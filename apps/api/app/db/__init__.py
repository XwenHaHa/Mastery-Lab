"""数据库连接、会话管理与轻量增量迁移（P0 使用 SQLite）。"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


settings.ensure_dirs()

engine = create_engine(
    settings.resolved_database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _connection_record):  # pragma: no cover - 驱动层回调
    if not settings.resolved_database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def _column_names(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {str(row[1]) for row in rows}


# P1.2 增量迁移：只做「加列」，不改名、不删列，因此不会丢用户数据。
# 键是表名，值是 {列名: ALTER 语句}。create_all() 不会给已存在的表补列，
# 所以老库启动时必须靠这里补齐（新库由 create_all 直接建成完整结构）。
_COLUMN_MIGRATIONS: dict[str, dict[str, str]] = {
    "courses": {
        "icon": "ALTER TABLE courses ADD COLUMN icon VARCHAR(16) NOT NULL DEFAULT ''",
        "last_studied_at": "ALTER TABLE courses ADD COLUMN last_studied_at DATETIME",
    },
    "knowledge_points": {
        "last_studied_at": "ALTER TABLE knowledge_points ADD COLUMN last_studied_at DATETIME",
        "completion_source": "ALTER TABLE knowledge_points ADD COLUMN completion_source VARCHAR(24)",
    },
}

# P1.2 把旧的两种状态并入四态模型（learning → in_progress，mastered → completed）。
_STATUS_ALIASES = {"learning": "in_progress", "mastered": "completed"}


def _ensure_columns() -> None:
    """给已存在的表补上 P1.2 新增的列（幂等）。"""
    with engine.begin() as conn:
        for table, columns in _COLUMN_MIGRATIONS.items():
            existing = _column_names(conn, table)
            if not existing:
                continue  # 表还不存在，交给 create_all
            for column, ddl in columns.items():
                if column in existing:
                    continue
                conn.execute(text(ddl))
                logger.info("增量迁移：%s 表新增列 %s", table, column)


def _migrate_learning_status() -> None:
    """把历史状态值归一到 P1.2 的四态命名（幂等）。"""
    with engine.begin() as conn:
        if not _column_names(conn, "knowledge_points"):
            return
        for old, new in _STATUS_ALIASES.items():
            result = conn.execute(
                text("UPDATE knowledge_points SET learning_status = :new WHERE learning_status = :old"),
                {"new": new, "old": old},
            )
            if result.rowcount:
                logger.info("增量迁移：learning_status %s → %s（%s 行）", old, new, result.rowcount)


def init_db() -> None:
    """建库建表 + 增量迁移（幂等）。仍不引入迁移框架，见 docs/DATABASE.md 第 5 节。"""
    settings.ensure_dirs()
    from . import models  # noqa: F401  - 导入以注册表结构

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _migrate_learning_status()
    with engine.begin() as conn:
        conn.execute(text("UPDATE knowledge_points SET completion_source='legacy_manual' WHERE learning_status='completed' AND completion_source IS NULL"))
    logger.info("数据库就绪: %s", settings.resolved_database_url)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个 Session，结束后自动关闭。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_database() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - 健康检查只关心可用性
        logger.exception("数据库健康检查失败")
        return False
