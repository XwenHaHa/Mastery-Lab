"""健康检查与运行环境信息。"""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone

from fastapi import APIRouter

from ...core.config import settings
from ...core.response import ApiResponse, success
from ...core.security import active_scheme
from ...db import check_database

router = APIRouter(tags=["system"])


@router.get("/health", response_model=ApiResponse, summary="健康检查")
def health() -> ApiResponse:
    db_ok = check_database()
    return success(
        {
            "status": "ok" if db_ok else "degraded",
            "app": settings.app_name,
            "version": settings.app_version,
            "serverTime": datetime.now(timezone.utc).isoformat(),
            "database": {
                "ok": db_ok,
                "engine": "sqlite",
                "path": str(settings.db_path),
            },
            "paths": {
                "dataDir": str(settings.data_dir),
                "uploadsDir": str(settings.uploads_dir),
            },
            "security": {"secretScheme": active_scheme()},
            "runtime": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
            },
        }
    )
