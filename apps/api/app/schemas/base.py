"""统一 schema 基类。

对外 API 一律使用 camelCase 字段（前端友好），Python 内部保留 snake_case 命名。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CamelOutModel(BaseModel):
    """同时支持从 ORM 对象读取的对外模型。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
