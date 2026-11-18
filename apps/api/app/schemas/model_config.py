"""模型配置相关的请求/响应模型。

对外字段为 camelCase：baseUrl / modelName / apiKey / apiKeyHint ...
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from .base import CamelModel, CamelOutModel


def _normalize_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("Base URL 不能为空")
    if not normalized.lower().startswith(("http://", "https://")):
        raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
    return normalized


class ModelConfigCreate(CamelModel):
    name: str = Field(min_length=1, max_length=80, description="配置名称，用于界面识别")
    base_url: str = Field(max_length=500, description="OpenAI 兼容 API 地址，如 https://api.deepseek.com/v1")
    model_name: str = Field(min_length=1, max_length=160, description="模型名称，如 deepseek-chat")
    api_key: str = Field(min_length=1, max_length=400, description="仅写入，不会回显")
    is_default: bool = False

    @field_validator("name", "model_name", "api_key")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        return _normalize_base_url(value)


class ModelConfigUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, min_length=1, max_length=160)
    api_key: str | None = Field(default=None, max_length=400, description="留空表示不修改密钥")
    is_default: bool | None = None

    @field_validator("name", "model_name")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("api_key")
    @classmethod
    def _blank_means_keep(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_base_url(value)


class ModelConfigOut(CamelOutModel):
    """对外视图：不含明文密钥，只带掩码提示。"""

    id: int
    name: str
    base_url: str
    model_name: str
    api_key_hint: str
    api_key_scheme: str
    is_default: bool
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str
    created_at: datetime
    updated_at: datetime


class ModelTestRequest(CamelModel):
    """连接测试：可以直接测试尚未保存的表单（必须带 apiKey），
    也可以只给 id 测试已保存的配置（apiKey 可省略，用库里的密钥）。"""

    id: int | None = None
    base_url: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=160)
    api_key: str | None = Field(default=None, max_length=400)
    prompt: str = Field(default="请只回复两个字：可用", max_length=200)

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_base_url(value)


class ModelTestResult(CamelModel):
    ok: bool
    message: str
    latency_ms: int = 0
    model: str = ""
    reply: str = ""
    http_status: int | None = None
