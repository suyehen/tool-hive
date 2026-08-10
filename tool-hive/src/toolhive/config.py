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

    # ── 数据库 ──
    database_url: str = "postgresql+asyncpg://toolhive:changeme@localhost:5432/toolhive"

    # ── Redis / 共享缓存 ──
    redis_url: str = "redis://localhost:6379/0"

    # ── Chroma ──
    chroma_persist_dir: str = "./chroma_data"

    # ── 模型服务 ──
    model_api_key: str = ""
    embedding_model: str = ""

    # ── 安全：登录与账号 ──
    login_max_failures: int = 5
    login_lock_minutes: int = 30
    captcha_trigger_failures: int = 3
    captcha_trigger_window_minutes: int = 10
    temp_password_expire_hours: int = 24
    password_min_length: int = 12
    password_max_length: int = 128
    password_history_count: int = 5

    # ── 安全：会话 ──
    session_idle_timeout_minutes: int = 30
    session_absolute_timeout_hours: int = 8

    # ── 安全：运行侧签名 ──
    signature_time_window_seconds: int = 300
    nonce_retention_minutes: int = 10
    signing_key_min_bits: int = 2048
    signing_algorithm: str = "RSA-PSS-SHA256"
    signature_version: str = "TOOLHIVE-SIGN-V1"

    # ── 密钥（生产环境务必通过环境变量覆盖） ──
    totp_encryption_key: str = ""
    csrf_secret: str = ""


settings = Settings()
