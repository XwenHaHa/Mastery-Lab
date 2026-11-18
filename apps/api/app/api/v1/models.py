"""模型配置接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ...core.response import ApiResponse, success
from ...schemas.model_config import (
    ModelConfigCreate,
    ModelConfigOut,
    ModelConfigUpdate,
    ModelTestRequest,
    ModelTestResult,
)
from ...services import model_registry
from ..deps import db_session

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ApiResponse[list[ModelConfigOut]], summary="列出所有模型配置")
def list_models(session: Session = Depends(db_session)) -> ApiResponse:
    return success(model_registry.list_configs(session))


@router.get("/{config_id}", response_model=ApiResponse[ModelConfigOut], summary="获取单个模型配置")
def get_model(config_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    return success(model_registry.to_out(model_registry.get_config(session, config_id)))


@router.post(
    "",
    response_model=ApiResponse[ModelConfigOut],
    status_code=status.HTTP_201_CREATED,
    summary="新建模型配置",
)
def create_model(payload: ModelConfigCreate, session: Session = Depends(db_session)) -> ApiResponse:
    return success(model_registry.create_config(session, payload), message="配置已保存")


@router.put("/{config_id}", response_model=ApiResponse[ModelConfigOut], summary="修改模型配置")
def update_model(
    config_id: int,
    payload: ModelConfigUpdate,
    session: Session = Depends(db_session),
) -> ApiResponse:
    return success(model_registry.update_config(session, config_id, payload), message="配置已更新")


@router.delete("/{config_id}", response_model=ApiResponse[None], summary="删除模型配置")
def delete_model(config_id: int, session: Session = Depends(db_session)) -> ApiResponse:
    model_registry.delete_config(session, config_id)
    return success(message="配置已删除")


@router.post("/test", response_model=ApiResponse[ModelTestResult], summary="测试模型连接（支持未保存的表单）")
async def test_model(payload: ModelTestRequest, session: Session = Depends(db_session)) -> ApiResponse:
    return success(await model_registry.test_config(session, payload))
