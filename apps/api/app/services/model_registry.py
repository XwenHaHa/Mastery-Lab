"""模型配置的业务逻辑。

职责边界：
- 这里负责密钥的加密/解密与“默认配置唯一”等业务规则；
- 路由层只做参数校验和响应包装；
- 密钥明文只在这一层与 llm_client 之间短暂存在，绝不进日志、绝不出现在响应里。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.response import ConflictError, NotFoundError, ValidationError
from ..core.security import SecretError, active_scheme, decrypt_secret, encrypt_secret, mask_secret
from ..db.models import ModelConfig
from ..schemas.model_config import (
    ModelConfigCreate,
    ModelConfigOut,
    ModelConfigUpdate,
    ModelTestRequest,
    ModelTestResult,
)
from .llm_client import probe_chat

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_out(config: ModelConfig) -> ModelConfigOut:
    return ModelConfigOut.model_validate(config).model_copy(update={"api_key_hint": "****"})


def _check_key_destination(saved: ModelConfig, base_url: str | None, key: str | None) -> None:
    if base_url is not None and base_url != saved.base_url and not key:
        raise ValidationError("修改 Base URL 后，请重新填写用于新地址的 API Key")


def list_configs(session: Session) -> list[ModelConfigOut]:
    rows = session.scalars(select(ModelConfig).order_by(ModelConfig.id)).all()
    return [to_out(row) for row in rows]


def get_config(session: Session, config_id: int) -> ModelConfig:
    config = session.get(ModelConfig, config_id)
    if config is None:
        raise NotFoundError(f"模型配置 {config_id} 不存在")
    return config


def _ensure_name_available(session: Session, name: str, *, exclude_id: int | None = None) -> None:
    stmt = select(ModelConfig).where(ModelConfig.name == name)
    if exclude_id is not None:
        stmt = stmt.where(ModelConfig.id != exclude_id)
    if session.scalars(stmt).first() is not None:
        raise ConflictError(f"已存在同名配置「{name}」")


def _clear_other_defaults(session: Session, keep_id: int | None) -> None:
    rows = session.scalars(select(ModelConfig)).all()
    for row in rows:
        if row.id != keep_id and row.is_default:
            row.is_default = False


def create_config(session: Session, payload: ModelConfigCreate) -> ModelConfigOut:
    _ensure_name_available(session, payload.name)

    try:
        cipher = encrypt_secret(payload.api_key)
    except SecretError as exc:
        raise ValidationError(f"密钥加密失败：{exc}") from exc

    is_first = session.scalars(select(ModelConfig)).first() is None
    config = ModelConfig(
        name=payload.name,
        base_url=payload.base_url,
        model_name=payload.model_name,
        api_key_cipher=cipher,
        api_key_hint=mask_secret(payload.api_key),
        api_key_scheme=active_scheme(),
        is_default=payload.is_default or is_first,
    )
    session.add(config)
    session.flush()
    if config.is_default:
        _clear_other_defaults(session, config.id)
    session.commit()
    session.refresh(config)
    logger.info("已保存模型配置 id=%s name=%s model=%s", config.id, config.name, config.model_name)
    return to_out(config)


def update_config(session: Session, config_id: int, payload: ModelConfigUpdate) -> ModelConfigOut:
    config = get_config(session, config_id)
    _check_key_destination(config, payload.base_url, payload.api_key)
    changed = bool(payload.api_key) or (
        payload.base_url is not None and payload.base_url != config.base_url
    ) or (payload.model_name is not None and payload.model_name != config.model_name)

    if payload.name is not None and payload.name != config.name:
        _ensure_name_available(session, payload.name, exclude_id=config.id)
        config.name = payload.name
    if payload.base_url is not None:
        config.base_url = payload.base_url
    if payload.model_name is not None:
        config.model_name = payload.model_name

    if payload.api_key:
        try:
            config.api_key_cipher = encrypt_secret(payload.api_key)
        except SecretError as exc:
            raise ValidationError(f"密钥加密失败：{exc}") from exc
        config.api_key_hint = mask_secret(payload.api_key)
        config.api_key_scheme = active_scheme()
    if changed:
        config.last_test_at = None
        config.last_test_ok = None
        config.last_test_message = ""

    if payload.is_default is not None:
        config.is_default = payload.is_default

    session.commit()
    session.refresh(config)
    if config.is_default:
        _clear_other_defaults(session, config.id)
        session.commit()
        session.refresh(config)
    logger.info("已更新模型配置 id=%s name=%s", config.id, config.name)
    return to_out(config)


def delete_config(session: Session, config_id: int) -> None:
    config = get_config(session, config_id)
    was_default = config.is_default
    session.delete(config)
    session.commit()
    if was_default:
        remaining = session.scalars(select(ModelConfig).order_by(ModelConfig.id)).all()
        if remaining:
            remaining[0].is_default = True
            session.commit()
    logger.info("已删除模型配置 id=%s", config_id)


async def test_config(session: Session, payload: ModelTestRequest) -> ModelTestResult:
    """连接测试。既支持表单里的临时值，也支持库里已保存的配置。"""
    base_url = payload.base_url
    model_name = payload.model_name
    api_key = payload.api_key
    saved: ModelConfig | None = None

    if payload.id is not None:
        saved = get_config(session, payload.id)
        _check_key_destination(saved, base_url, api_key)
        base_url = base_url or saved.base_url
        model_name = model_name or saved.model_name
        if not api_key:
            try:
                api_key = decrypt_secret(saved.api_key_cipher)
            except SecretError as exc:
                raise ValidationError(str(exc)) from exc

    if not base_url or not model_name or not api_key:
        raise ValidationError("缺少测试参数：需要 base_url、model_name 和 api_key（或已保存的 id）")

    result = await probe_chat(
        base_url=base_url,
        model_name=model_name,
        api_key=api_key,
        prompt=payload.prompt,
    )

    if saved is not None and not payload.api_key and base_url == saved.base_url and model_name == saved.model_name:
        saved.last_test_at = _utcnow()
        saved.last_test_ok = result.ok
        saved.last_test_message = result.message[:300]
        session.commit()

    logger.info(
        "模型连接测试 id=%s model=%s ok=%s status=%s latency=%sms",
        payload.id,
        model_name,
        result.ok,
        result.http_status,
        result.latency_ms,
    )

    return ModelTestResult(
        ok=result.ok,
        message=result.message,
        latency_ms=result.latency_ms,
        model=result.model,
        reply=result.reply,
        http_status=result.http_status,
    )
