"""允许 `python -m app` 直接启动（脚本里用 uvicorn 亦可）。"""

from __future__ import annotations

import uvicorn

from .core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level,
    )
