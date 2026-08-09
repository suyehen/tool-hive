from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ToolHive 全局配置，从环境变量或 .env 文件加载。"""

    model_config = SettingsConfigDict(
        env_prefix="TOOLHIVE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 应用 ──
    app_name: str = "ToolHive"
    app_version: str = "0.1.0"
    debug: bool = False

    # ── 数据库 ──
    database_url: str = "postgresql+asyncpg://toolhive:toolhive@localhost:5432/toolhive"

    # ── 运行面（内网） ──
    runtime_host: str = "127.0.0.1"
    runtime_port: int = 8100

    # ── 管理面（公网） ──
    management_host: str = "0.0.0.0"
    management_port: int = 8101

    # ── 认证 ──
    secret_key: str = "change-me-in-production"
    session_ttl_minutes: int = 480  # 8 小时
    bcrypt_rounds: int = 12

    # ── Chroma ──
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_collection: str = "toolhive_tools"

    # ── Redis（会话 & 限流）──
    redis_url: str = "redis://localhost:6379/0"

    # ── 执行 ──
    default_execute_timeout_ms: int = 30_000
    max_response_size_bytes: int = 1_048_576  # 1 MiB

    # ── 服务间认证 ──
    runtime_api_key: str = "change-me-runtime-key"


settings = Settings()
