"""应用配置：环境变量 > .env > 代码默认值。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/app/core/config.py -> apps/api
API_ROOT = Path(__file__).resolve().parents[2]
# apps/api -> 仓库根目录
REPO_ROOT = API_ROOT.parents[1]


class Settings(BaseSettings):
    """全局配置。所有变量使用 MASTERY_LAB_ 前缀。"""

    model_config = SettingsConfigDict(
        env_prefix="MASTERY_LAB_",
        env_file=str(API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Mastery Lab API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "info"

    data_dir: Path = Field(default=REPO_ROOT / "data")
    database_url: str | None = None

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    llm_timeout_seconds: float = 20.0
    # 教学对话是长回答，读超时单独放宽；连接超时仍由 httpx 的 connect 控制。
    llm_stream_timeout_seconds: float = Field(default=180.0, gt=0)
    llm_stream_total_timeout_seconds: float = Field(default=240.0, gt=0)
    llm_reply_max_tokens: int = Field(default=4096, gt=0)
    # 教学上下文预算：知识点正文与历史消息都会按字数裁剪，避免把整本教材发给模型。
    classroom_context_chars: int = Field(default=6000, ge=500)
    classroom_history_messages: int = Field(default=20, ge=2)
    classroom_history_chars: int = Field(default=14000, ge=1000)
    # 单份教材文件上限（字节），超出直接拒绝，不把超大文件读进内存
    max_material_bytes: int = 20 * 1024 * 1024

    # ---- 派生路径 ----
    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def courses_dir(self) -> Path:
        """教材原文目录（P1.1）：data/courses/<uuid>/<原文件名>。"""
        return self.data_dir / "courses"

    @property
    def run_dir(self) -> Path:
        return self.data_dir / "run"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mastery_lab.db"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.db_path.as_posix()}"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.secrets_dir, self.uploads_dir, self.courses_dir, self.run_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
