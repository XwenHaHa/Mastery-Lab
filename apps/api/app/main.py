"""FastAPI 应用入口。

启动：python -m app  或  uvicorn app.main:app --reload
文档：http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.v1 import api_router
from .core.config import settings
from .core.response import ApiResponse, AppError, success
from .db import SessionLocal, init_db
from .db.models import AppSetting

SCHEMA_VERSION = "5"

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("mastery_lab")
logging.getLogger("httpx").setLevel(logging.WARNING)


def _record_schema_version() -> None:
    with SessionLocal() as session:
        row = session.get(AppSetting, "schema_version")
        if row is None:
            session.add(AppSetting(key="schema_version", value=SCHEMA_VERSION))
        elif row.value != SCHEMA_VERSION:
            row.value = SCHEMA_VERSION
        session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    init_db()
    from .services.teaching_state import TeachingStateMachine
    with SessionLocal() as session:
        TeachingStateMachine(session).recover()
    _record_schema_version()
    logger.info(
        "Mastery Lab API 已启动 | 数据目录=%s | 数据库=%s | 文档=http://%s:%s/docs",
        settings.data_dir,
        settings.resolved_database_url,
        settings.host,
        settings.port,
    )
    yield
    logger.info("Mastery Lab API 已停止")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Mastery Lab 本地 API：模型配置、教材导入、课程管理和 AI 学习教室（P1.3）。",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        # 只记录方法、路径、状态码和耗时，绝不记录请求体（可能含密钥）
        logger.info("%s %s -> %s (%.1f ms)", request.method, request.url.path, response.status_code, elapsed_ms)
        return response

    # ---- 统一错误响应 ----
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "data": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(part) for part in err.get("loc", [])[1:]), "message": err.get("msg", "")}
            for err in exc.errors()
        ]
        first = fields[0]["message"] if fields else "参数校验失败"
        return JSONResponse(
            status_code=422,
            content={"code": 1003, "message": f"参数校验失败：{first}", "data": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code * 10, "message": str(exc.detail), "data": None},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理的异常: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"code": 1500, "message": "服务内部错误，请查看后端日志", "data": None},
        )

    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", tags=["system"], summary="服务根路径")
    def root() -> dict:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "app": settings.app_name,
                "version": settings.app_version,
                "apiPrefix": settings.api_prefix,
                "docs": "/docs",
                "health": f"{settings.api_prefix}/health",
            },
        }

    return app


app = create_app()
