"""FastAPI 依赖注入。"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..db import get_session


def db_session() -> Iterator[Session]:
    """路由统一用的数据库会话依赖。"""
    yield from get_session()
