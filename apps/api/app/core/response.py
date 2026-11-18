"""统一响应结构与业务异常定义。

所有 /api 接口（含错误）都返回同一外壳：

    {"code": 0, "message": "ok", "data": {...}}

code == 0 表示成功；非 0 时 message 可直接展示给用户，detail 里带可选的字段级信息。
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None


def success(data: Any = None, message: str = "ok") -> ApiResponse[Any]:
    return ApiResponse[Any](code=0, message=message, data=data)


class AppError(Exception):
    """可预期的业务异常。"""

    def __init__(
        self,
        message: str,
        *,
        code: int = 1000,
        status_code: int = 400,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.detail = detail


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(message, code=1001, status_code=404)


class ConflictError(AppError):
    def __init__(self, message: str = "资源冲突") -> None:
        super().__init__(message, code=1002, status_code=409)


class ValidationError(AppError):
    def __init__(self, message: str = "参数校验失败", detail: Any = None) -> None:
        super().__init__(message, code=1003, status_code=422, detail=detail)


class UpstreamError(AppError):
    """调用外部模型服务失败。"""

    def __init__(self, message: str = "模型服务调用失败", detail: Any = None) -> None:
        super().__init__(message, code=1004, status_code=502, detail=detail)
