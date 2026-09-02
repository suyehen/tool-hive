"""ToolHive 全局配置。

配置来源与优先级：环境变量具体值 > 外挂 YAML > ``.env`` 文件 > 代码默认值。
外挂 YAML 通过 ``--config`` 或 ``TOOLHIVE_CONFIG_FILE`` 指定，
``.env`` 文件在启动阶段统一解析（``load_settings``）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, get_args, get_origin

import yaml
from pydantic import BaseModel, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseModel):
    """应用级配置。"""

    app_name: str = "ToolHive"
    app_version: str = "0.1.0"
    debug: bool = False
    bind_host: str = "127.0.0.1"
    bind_port: int = 8100


class AdminSecuritySettings(BaseModel):
    """管理侧安全配置：登录、密码、会话与 CSRF。"""

    csrf_secret: str = ""
    login_max_failures: int = 5
    login_lock_minutes: int = 30
    login_failure_window_minutes: int = 10
    captcha_ttl_seconds: int = 300
    captcha_code_length: int = 4
    captcha_challenge_max_per_minute: int = 10
    temp_password_expire_hours: int = 24
    password_min_length: int = 12
    password_max_length: int = 128
    password_history_count: int = 5
    session_idle_timeout_minutes: int = 30
    session_absolute_timeout_hours: int = 8


class RuntimeSecuritySettings(BaseModel):
    """运行侧安全配置：请求签名、时间窗口与 Nonce（一期下半使用）。"""

    signature_time_window_seconds: int = 300
    nonce_retention_minutes: int = 10
    signing_key_min_bits: int = 2048
    signing_algorithm: str = "RSA-PSS-SHA256"
    signature_version: str = "TOOLHIVE-SIGN-V1"
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_window_seconds: int = 60
    circuit_breaker_open_seconds: int = 30
    provider_max_request_bytes: int = 1048576
    provider_max_request_header_count: int = 50
    provider_max_response_bytes: int = 1048576
    provider_max_header_count: int = 50
    provider_connect_timeout_seconds: int = 5
    provider_read_timeout_seconds: int = 10


class RetrievalSettings(BaseModel):
    """检索配置：Embedding 模型与模型 Key（一期下半使用）。"""

    model_api_key: str = ""
    embedding_model: str = ""
    timeout_seconds: int = 10


class OutboxRetrySettings(BaseModel):
    """Outbox 重试参数。"""

    initial_delay_seconds: int = Field(
        default=5,
        ge=1,
        description="第一次投递失败后的等待时间，单位秒",
    )
    max_delay_seconds: int = Field(
        default=1800,
        ge=1,
        description="重试等待时间的最大值，单位秒",
    )
    multiplier: float = Field(
        default=2.0,
        ge=1.0,
        description="每次重试等待时间的增长倍数",
    )
    jitter_ratio: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="避免多个任务同时重试的随机抖动比例",
    )


class OutboxSettings(BaseModel):
    """Outbox 后台投递任务配置。"""

    enabled: bool = Field(default=True, description="是否启用 Outbox 后台投递任务")
    poll_interval_ms: int = Field(
        default=1000,
        ge=100,
        description="查询 PostgreSQL 待处理任务的间隔，单位毫秒",
    )
    batch_size: int = Field(default=50, ge=1, description="单次领取的最大任务数量")
    max_concurrency: int = Field(
        default=5,
        ge=1,
        description="Redis 等普通投递目标的最大并发处理数量",
    )
    lock_timeout_seconds: int = Field(
        default=60,
        ge=1,
        description="PROCESSING 任务的占用超时时间，单位秒",
    )
    max_attempts: int = Field(
        default=10,
        ge=1,
        description="单条投递的最大尝试次数，超过后进入 DEAD",
    )
    retry: OutboxRetrySettings = Field(default_factory=OutboxRetrySettings)


class ChromaSettings(BaseModel):
    """Chroma 检索索引配置。"""

    mode: str = Field(
        default="embedded",
        pattern="^(embedded|service)$",
        description="一期固定使用 embedded；二期可以扩展为 service",
    )
    persist_directory: str = Field(
        default="/vdb/tool-hive/chroma",
        description="嵌入式 Chroma 的生产持久化目录",
    )
    write_concurrency: int = Field(
        default=1,
        ge=1,
        description="嵌入式模式的写入并发数，一期只能为 1",
    )


class InfrastructureSettings(BaseModel):
    """基础设施连接配置。"""

    database_url: str = "postgresql+asyncpg://toolhive:changeme@localhost:5432/toolhive"
    redis_url: str = "redis://localhost:6379/0"
    chroma: ChromaSettings = Field(default_factory=ChromaSettings)


class NetworkSettings(BaseModel):
    """网络入口配置：可信代理与开发直连。"""

    trusted_proxies: list[str] = Field(
        default_factory=lambda: ["127.0.0.1/32", "::1/128"],
        description="可信代理 CIDR 列表；只有这些来源的内部 Header 才被读取",
    )
    allow_loopback_direct: bool = Field(
        default=False,
        description="开发环境是否允许仅回环地址直连（生产必须为 false）",
    )


class SnowflakeSettings(BaseModel):
    """雪花算法 ID 配置。"""

    epoch_ms: int = Field(
        default=1767225600000,
        description="雪花算法使用的固定起始时间戳，投产后不得随意修改",
    )
    datacenter_id: int = Field(
        default=1,
        ge=0,
        le=31,
        description="数据中心编号，取值范围为 0～31",
    )
    worker_id: int = Field(
        default=0,
        ge=0,
        le=31,
        description="当前运行节点编号，取值范围为 0～31；多实例不得重复",
    )
    clock_rollback_tolerance_ms: int = Field(
        default=5,
        ge=0,
        description="允许等待恢复的系统时钟回退时间，单位毫秒",
    )


class Settings(BaseSettings):
    """ToolHive 全局配置。"""

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

    # ── 监听（A01：单一应用、单一端口，仅绑定回环地址） ──
    bind_host: str = "127.0.0.1"
    bind_port: int = 8100

    # ── 数据库 ──
    database_url: str = "postgresql+asyncpg://toolhive:changeme@localhost:5432/toolhive"

    # ── Redis / 共享缓存 ──
    redis_url: str = "redis://localhost:6379/0"

    # ── 模型服务 ──
    model_api_key: str = ""
    embedding_model: str = ""
    retrieval_timeout_seconds: int = 10

    # ── 安全：登录与账号 ──
    login_max_failures: int = 5
    login_lock_minutes: int = 30
    login_failure_window_minutes: int = 10
    captcha_ttl_seconds: int = 300
    captcha_code_length: int = 4
    captcha_challenge_max_per_minute: int = 10
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
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_window_seconds: int = 60
    circuit_breaker_open_seconds: int = 30
    provider_max_request_bytes: int = 1048576
    provider_max_request_header_count: int = 50
    provider_max_response_bytes: int = 1048576
    provider_max_header_count: int = 50
    provider_connect_timeout_seconds: int = 5
    provider_read_timeout_seconds: int = 10

    # ── 密钥（生产环境务必通过环境变量覆盖） ──
    csrf_secret: str = ""

    # ── Outbox 后台投递 ──
    outbox: OutboxSettings = Field(default_factory=OutboxSettings)

    # ── Chroma 检索索引 ──
    chroma: ChromaSettings = Field(default_factory=ChromaSettings)

    # ── 网络入口 ──
    network: NetworkSettings = Field(default_factory=NetworkSettings)

    # ── 雪花 ID ──
    snowflake: SnowflakeSettings = Field(default_factory=SnowflakeSettings)

    # ── 配置分区视图（业务模块只注入所需分区，不依赖完整 Settings） ──

    @computed_field
    @property
    def app(self) -> AppSettings:
        return AppSettings(
            app_name=self.app_name,
            app_version=self.app_version,
            debug=self.debug,
            bind_host=self.bind_host,
            bind_port=self.bind_port,
        )

    @computed_field
    @property
    def admin_security(self) -> AdminSecuritySettings:
        return AdminSecuritySettings(
            csrf_secret=self.csrf_secret,
            login_max_failures=self.login_max_failures,
            login_lock_minutes=self.login_lock_minutes,
            login_failure_window_minutes=self.login_failure_window_minutes,
            captcha_ttl_seconds=self.captcha_ttl_seconds,
            captcha_code_length=self.captcha_code_length,
            captcha_challenge_max_per_minute=self.captcha_challenge_max_per_minute,
            temp_password_expire_hours=self.temp_password_expire_hours,
            password_min_length=self.password_min_length,
            password_max_length=self.password_max_length,
            password_history_count=self.password_history_count,
            session_idle_timeout_minutes=self.session_idle_timeout_minutes,
            session_absolute_timeout_hours=self.session_absolute_timeout_hours,
        )

    @computed_field
    @property
    def runtime_security(self) -> RuntimeSecuritySettings:
        return RuntimeSecuritySettings(
            signature_time_window_seconds=self.signature_time_window_seconds,
            nonce_retention_minutes=self.nonce_retention_minutes,
            signing_key_min_bits=self.signing_key_min_bits,
            signing_algorithm=self.signing_algorithm,
            signature_version=self.signature_version,
            circuit_breaker_failure_threshold=self.circuit_breaker_failure_threshold,
            circuit_breaker_window_seconds=self.circuit_breaker_window_seconds,
            circuit_breaker_open_seconds=self.circuit_breaker_open_seconds,
            provider_max_request_bytes=self.provider_max_request_bytes,
            provider_max_request_header_count=(
                self.provider_max_request_header_count
            ),
            provider_max_response_bytes=self.provider_max_response_bytes,
            provider_max_header_count=self.provider_max_header_count,
            provider_connect_timeout_seconds=self.provider_connect_timeout_seconds,
            provider_read_timeout_seconds=self.provider_read_timeout_seconds,
        )

    @computed_field
    @property
    def retrieval(self) -> RetrievalSettings:
        return RetrievalSettings(
            model_api_key=self.model_api_key,
            embedding_model=self.embedding_model,
            timeout_seconds=self.retrieval_timeout_seconds,
        )

    @computed_field
    @property
    def infrastructure(self) -> InfrastructureSettings:
        return InfrastructureSettings(
            database_url=self.database_url,
            redis_url=self.redis_url,
            chroma=self.chroma,
        )


def _is_model(annotation: Any) -> bool:
    """判断注解是否为（或包含）pydantic BaseModel。"""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return True
    origin = get_origin(annotation)
    if origin is not None:
        return any(_is_model(arg) for arg in get_args(annotation))
    return False


def _iter_env_names(
    model_cls: type[BaseModel], prefix: str = "",
) -> list[tuple[str, str, Any]]:
    """遍历模型字段，返回 (字段路径, 环境变量名, 字段注解) 列表。"""
    result: list[tuple[str, str, Any]] = []
    for name, field in model_cls.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        env_name = "TOOLHIVE_" + path.upper().replace(".", "_")
        if _is_model(field.annotation):
            result.extend(_iter_env_names(field.annotation, path))
        else:
            result.append((path, env_name, field.annotation))
    return result


def _is_complex_annotation(annotation: Any) -> bool:
    """判断注解是否为需要 JSON 解析的复杂类型（列表/字典/集合/元组）。"""
    if annotation in (list, dict, set, tuple):
        return True
    origin = get_origin(annotation)
    if origin is None:
        return False
    if origin in (list, dict, set, tuple):
        return True
    # Union / Optional 等组合类型：递归检查成员
    return any(_is_complex_annotation(arg) for arg in get_args(annotation))


def _parse_env_value(value: str, annotation: Any) -> Any:
    """解析单个配置值：复杂类型按 JSON 解析，其余保留字符串由 pydantic 强转。"""
    if not _is_complex_annotation(annotation):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"配置项需要 JSON 格式（如 [\"a\",\"b\"]），当前值无法解析: {value[:80]}"
        ) from exc


def _build_nested(values: Any) -> dict[str, Any]:
    """把 TOOLHIVE_* 配置（真实环境变量或 .env 文件）映射为嵌套 dict。"""
    data: dict[str, Any] = {}
    for path, env_name, annotation in _iter_env_names(Settings):
        value = values.get(env_name)
        if value is None or value == "":
            continue
        node = data
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = _parse_env_value(value, annotation)
    return data


def _collect_env_values() -> dict[str, Any]:
    """收集真实环境变量中的 TOOLHIVE_* 配置并映射为嵌套 dict。"""
    return _build_nested(os.environ)


def _load_dotenv_data() -> dict[str, Any]:
    """读取 ``.env`` 文件中的 TOOLHIVE_* 配置并映射为嵌套 dict。"""
    env_file = Path(".env")
    if not env_file.is_file():
        return {}
    from dotenv import dotenv_values
    return _build_nested(dotenv_values(env_file))


def _load_yaml_data(config_file: str | Path | None) -> dict[str, Any]:
    if config_file is None:
        return {}
    path = Path(config_file)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"配置文件不存在或不可读: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"配置文件内容非法: {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件必须是 YAML 映射: {path}")
    return data


def _deep_merge(
    base: dict[str, Any], override: dict[str, Any],
) -> dict[str, Any]:
    """override 递归覆盖 base。"""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(config_file: str | Path | None = None) -> Settings:
    """加载应用配置。

    优先级：环境变量具体值 > 外挂 YAML > ``.env`` 文件 > 代码默认值。
    外挂配置文件通过 ``--config`` 或 ``TOOLHIVE_CONFIG_FILE`` 指定；
    明确指定的文件不存在、不可读或内容非法时抛出异常，服务启动失败。
    """
    global settings
    resolved = config_file or os.environ.get("TOOLHIVE_CONFIG_FILE")
    yaml_data = _load_yaml_data(resolved)
    dotenv_data = _load_dotenv_data()
    env_data = _collect_env_values()
    merged = _deep_merge(dotenv_data, yaml_data)
    merged = _deep_merge(merged, env_data)
    settings = Settings(**merged)
    return settings


def validate_production_settings(settings: Settings) -> None:
    """生产模式（debug=false）配置校验。

    不满足时抛出 ValueError，应用启动失败并输出明确原因；
    开发模式（debug=true）跳过校验，允许宽松配置。
    """
    if settings.debug:
        return
    errors: list[str] = []
    if not settings.csrf_secret:
        errors.append("csrf_secret 不能为空，必须通过环境变量或配置文件设置")
    if "changeme" in settings.database_url:
        errors.append("database_url 不能使用默认占位密码 changeme")
    if "changeme" in settings.redis_url:
        errors.append("redis_url 不能使用默认占位密码 changeme")
    if settings.network.allow_loopback_direct:
        errors.append("network.allow_loopback_direct 在生产环境必须为 false")
    if settings.bind_host not in ("127.0.0.1", "::1"):
        errors.append("bind_host 在生产环境必须绑定回环地址（127.0.0.1 或 ::1）")
    if not settings.network.trusted_proxies:
        errors.append("network.trusted_proxies 不能为空，必须包含部署的 Nginx 地址")
    # ── 运行侧签名 ──
    if settings.signature_time_window_seconds <= 0:
        errors.append("signature_time_window_seconds 必须大于 0")
    if settings.nonce_retention_minutes <= 0:
        errors.append("nonce_retention_minutes 必须大于 0")
    if settings.signing_key_min_bits < 2048:
        errors.append("signing_key_min_bits 不能小于 2048")
    if settings.signing_algorithm not in ("RSA-PSS-SHA256", "Ed25519"):
        errors.append("signing_algorithm 必须是 RSA-PSS-SHA256 或 Ed25519")
    if settings.signature_version != "TOOLHIVE-SIGN-V1":
        errors.append("signature_version 必须为 TOOLHIVE-SIGN-V1")
    # ── Embedding 与 Chroma ──
    if bool(settings.embedding_model) != bool(settings.model_api_key):
        errors.append("embedding_model 与 model_api_key 必须同时配置或同时为空")
    if not settings.chroma.persist_directory:
        errors.append("chroma.persist_directory 不能为空")
    if settings.chroma.mode != "embedded":
        errors.append("一期 chroma.mode 必须为 embedded")
    # ── Provider 出站限制 ──
    if (
        settings.provider_max_request_bytes <= 0
        or settings.provider_max_request_header_count <= 0
        or settings.provider_max_response_bytes <= 0
        or settings.provider_max_header_count <= 0
        or settings.provider_connect_timeout_seconds <= 0
        or settings.provider_read_timeout_seconds <= 0
    ):
        errors.append(
            "provider_max_request_bytes / provider_max_request_header_count / "
            "provider_max_response_bytes / provider_max_header_count / "
            "provider_connect_timeout_seconds / "
            "provider_read_timeout_seconds 必须大于 0"
        )
    if errors:
        raise ValueError(
            "生产配置校验失败，拒绝启动：\n- " + "\n- ".join(errors),
        )


settings = Settings()
