from __future__ import annotations

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

    # ── 运行面（内网） ──
    runtime_host: str = "127.0.0.1"
    runtime_port: int = 8100

    # ── 管理面（公网） ──
    management_host: str = "0.0.0.0"
    management_port: int = 8101


settings = Settings()
