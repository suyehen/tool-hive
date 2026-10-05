"""ToolHive 配置系统（任务 A2）。

设计目标
--------
1. **分区**：配置按功能分区，每个分区一个类，便于按模块查阅与扩展。
2. **环境变量是唯一来源**（M0）：所有项都可由环境变量覆盖，代码里的默认值只用于开发。
3. **启动校验**：按设计 §10.1 与 §6.5 的要求，任一校验不通过即**拒绝启动**，
   而不是等到某次请求才发现配置不对。

环境变量命名
------------
环境变量名是**对外契约**——`.env`、`docs/04-部署前置条件` 与运维脚本都按它书写。
因此本模块**不做任何命名推断**，每个字段用显式的 ``validation_alias`` 固定变量名。

其中这几个名字由设计文档**冻结**，不得改动（改动即破坏已写好的部署文档）：

``TOOLHIVE_KEKS`` / ``TOOLHIVE_ACTIVE_KEK_ID``                        —— 设计 §10.1
``TOOLHIVE_SNOWFLAKE_DATACENTER_ID`` / ``TOOLHIVE_SNOWFLAKE_WORKER_ID`` —— §4.1
``TOOLHIVE_EMBEDDING_BASE_URL`` / ``TOOLHIVE_EMBEDDING_API_KEY``        —— §6.5

校验分级
--------
* **拒绝启动**（``ConfigError``）：配置本身错了，继续跑一定会出问题。
* **仅告警**（``ConfigWarning``）：能力降级但平台仍可运行，按设计 §6.6 处理。

分级的依据写在各校验项旁边，便于复核。
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "ConfigError",
    "ConfigProblem",
    "Settings",
    "load_settings",
]

# 检索返回条数上限。设计 §6.1 规定 k 上限为 50，属于对外契约，不做成配置项。
MAX_SEARCH_K: Final = 50

# 环境变量名前缀。仅用于文档与报错信息，不参与解析。
ENV_PREFIX: Final = "TOOLHIVE_"


class ConfigError(RuntimeError):
    """配置校验不通过。**抛出即代表拒绝启动**（设计 §14.3 的启动校验要求）。"""

    def __init__(self, problems: list[ConfigProblem]) -> None:
        self.problems = problems
        lines = [f"配置校验未通过，拒绝启动（共 {len(problems)} 项）："]
        lines += [f"  [{p.section}] {p.message}" for p in problems]
        super().__init__("\n".join(lines))


@dataclass(frozen=True)
class ConfigProblem:
    """一条配置问题。``severity`` 为 ``error`` 时拒绝启动，``warning`` 时仅告警。"""

    section: str
    field: str
    message: str
    severity: str = "error"


@dataclass
class ConfigReport:
    """校验结果汇总。``load_settings`` 用它决定是否放行。"""

    problems: list[ConfigProblem] = field(default_factory=list)

    @property
    def errors(self) -> list[ConfigProblem]:
        return [p for p in self.problems if p.severity == "error"]

    @property
    def warnings(self) -> list[ConfigProblem]:
        return [p for p in self.problems if p.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


class _Section(BaseSettings):
    """所有配置分区的基类。

    ``extra="ignore"`` 让无关的环境变量（同一台机器上还有别的应用）不至于让解析失败。
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
        validate_default=True,
        frozen=True,
    )


# ---------------------------------------------------------------------------
# 分区定义
# ---------------------------------------------------------------------------


class RuntimeSettings(_Section):
    """运行参数。设计 §12。"""

    env: str = Field("dev", validation_alias="TOOLHIVE_ENV")
    log_level: str = Field("INFO", validation_alias="TOOLHIVE_LOG_LEVEL")
    bind_host: str = Field("127.0.0.1", validation_alias="TOOLHIVE_BIND_HOST")
    bind_port: int = Field(8080, validation_alias="TOOLHIVE_BIND_PORT")


class DatabaseSettings(_Section):
    """PostgreSQL。设计 §12；经 SSH 隧道访问的部署形态见 docs/04 §1.2。"""

    # 无默认值：缺失即拒绝启动。连不上数据库的平台没有任何可用能力。
    url: str = Field(..., validation_alias="TOOLHIVE_DATABASE_URL")
    pool_min: int = Field(2, validation_alias="TOOLHIVE_DB_POOL_MIN")
    pool_max: int = Field(20, validation_alias="TOOLHIVE_DB_POOL_MAX")
    command_timeout: float = Field(5.0, validation_alias="TOOLHIVE_DB_COMMAND_TIMEOUT")


class RedisSettings(_Section):
    """Redis。设计 §12。

    ⚠️ 注意 ``db`` 编号：服务器上的 ``db0`` 被另一个应用占用，ToolHive 用 ``db1``
    （见 docs/04 §1.3）。编号写在 URL 末尾，这里不单独配置。
    """

    url: str = Field(..., validation_alias="TOOLHIVE_REDIS_URL")


class SnowflakeSettings(_Section):
    """雪花 ID。设计 §4.1 的全局约定① + **§4.4 的位分配与发号规则**。

    位分配是 ``1 符号 + 41 时间戳 + 5 数据中心 + 5 机器 + 12 序列``，
    所以两个值各自 5 位、取值 ``0..31``。

    ⚠️ **多实例部署时 (datacenter_id, worker_id) 组合不得重复**——
    重复会让两个实例发出完全相同的 ID。任务 B6 会用 Redis 租约在启动时把它拦住。
    """

    datacenter_id: int = Field(1, validation_alias="TOOLHIVE_SNOWFLAKE_DATACENTER_ID")
    worker_id: int = Field(1, validation_alias="TOOLHIVE_SNOWFLAKE_WORKER_ID")


class SecretSettings(_Section):
    """凭据加密的 KEK。设计 §10.1。

    ``keks`` 是 **JSON 对象**（多把并存，为轮换留位），不是单值：
    ``{"k1": "<32 字节 base64>", "k2": "..."}``
    """

    keks: str = Field(..., validation_alias="TOOLHIVE_KEKS")
    active_kek_id: str = Field(..., validation_alias="TOOLHIVE_ACTIVE_KEK_ID")

    def kek_ids(self) -> set[str]:
        return set(self._parsed().keys())

    def kek_bytes(self, kek_id: str) -> bytes:
        """按 ``kek_id`` 取 KEK 原始字节。

        解密时必须用**密文上记录的** ``kek_id``，而不是 ``active_kek_id``——
        否则 KEK 轮换期间存量凭据会全部解不开（设计 §10.1）。
        """
        parsed = self._parsed()
        if kek_id not in parsed:
            raise KeyError(kek_id)
        return base64.b64decode(parsed[kek_id])

    def active_kek(self) -> tuple[str, bytes]:
        """新写入凭据使用的那把 KEK：``(kek_id, 原始字节)``。"""
        return self.active_kek_id, self.kek_bytes(self.active_kek_id)

    def _parsed(self) -> dict[str, str]:
        try:
            data = json.loads(self.keks)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}


class EmbeddingSettings(_Section):
    """embedding 服务。设计 §6.4 / §6.5。

    ``dim`` 必须与 ``tool_embedding.embedding`` 的 ``halfvec(2560)`` 一致——
    索引版本化（§6.5）靠 ``index_meta`` 里记录的模型与维度做启动校验。
    """

    base_url: str = Field(..., validation_alias="TOOLHIVE_EMBEDDING_BASE_URL")
    api_key: str = Field("", validation_alias="TOOLHIVE_EMBEDDING_API_KEY")
    model: str = Field(..., validation_alias="TOOLHIVE_EMBEDDING_MODEL")
    dim: int = Field(2560, validation_alias="TOOLHIVE_EMBEDDING_DIM")
    timeout_seconds: float = Field(5.0, validation_alias="TOOLHIVE_EMBEDDING_TIMEOUT_SECONDS")

    @property
    def embeddings_path(self) -> str:
        """OpenAI 兼容的接口路径（设计 §6.4）。"""
        return f"{self.base_url.rstrip('/')}/v1/embeddings"


class RetrievalSettings(_Section):
    """检索。设计 §6.1 / §6.5。"""

    # 检索用哪个索引版本由它**唯一决定**，不是"自动选最新"——显式配置才能让切换可回滚。
    active_index_version: str = Field(
        "v1", validation_alias="TOOLHIVE_RETRIEVAL_ACTIVE_INDEX_VERSION"
    )
    default_k: int = Field(10, validation_alias="TOOLHIVE_RETRIEVAL_DEFAULT_K")
    max_k: int = Field(MAX_SEARCH_K, validation_alias="TOOLHIVE_RETRIEVAL_MAX_K")
    description_snippet_chars: int = Field(
        80, validation_alias="TOOLHIVE_RETRIEVAL_DESCRIPTION_SNIPPET_CHARS"
    )


class RerankSettings(_Section):
    """精排。设计 §6.2 / §16.2 —— **M0 默认关闭**，只交付接口 + no-op。

    配置项名对应任务 H5 的
    ``retrieval.rerank.{enabled,endpoint,model,api_key,timeout_ms,max_candidates}``。
    """

    enabled: bool = Field(False, validation_alias="TOOLHIVE_RERANK_ENABLED")
    provider: str = Field("dashscope", validation_alias="TOOLHIVE_RERANK_PROVIDER")
    endpoint: str = Field("", validation_alias="TOOLHIVE_RERANK_ENDPOINT")
    model: str = Field("", validation_alias="TOOLHIVE_RERANK_MODEL")
    api_key: str = Field("", validation_alias="TOOLHIVE_RERANK_API_KEY")
    timeout_ms: int = Field(1000, validation_alias="TOOLHIVE_RERANK_TIMEOUT_MS")
    max_candidates: int = Field(50, validation_alias="TOOLHIVE_RERANK_MAX_CANDIDATES")


class IdempotencySettings(_Section):
    """幂等结果缓存。设计 §7.2 的缓存规则表。"""

    ttl_seconds: int = Field(86400, validation_alias="TOOLHIVE_IDEMPOTENCY_TTL_SECONDS")
    max_result_bytes: int = Field(262144, validation_alias="TOOLHIVE_IDEMPOTENCY_MAX_RESULT_BYTES")


class LoggingSettings(_Section):
    """结构化日志与延迟直方图。设计 §11。

    延迟分位不接 Prometheus，改为**在日志里写预聚合的直方图桶**（固定边界），
    日志解析即可算分位——成本几乎为零（设计 §11 的「延迟分位」一行）。
    """

    service_name: str = Field("toolhive", validation_alias="TOOLHIVE_SERVICE_NAME")
    # 逗号分隔的毫秒边界，例如 "10,25,50,100,200,500,1000,2000"。
    # 用字符串而非列表：环境变量里写 JSON 数组对运维不友好。
    latency_buckets_ms: str = Field(
        "10,25,50,100,200,500,1000,2000",
        validation_alias="TOOLHIVE_LOG_LATENCY_BUCKETS_MS",
    )

    @property
    def latency_buckets(self) -> tuple[int, ...]:
        """解析后的桶边界，升序。格式非法时返回 ``()``（由 ``validate`` 负责报错）。"""
        try:
            parsed = {int(x) for x in self.latency_buckets_ms.split(",") if x.strip()}
            bounds = tuple(sorted(parsed))
        except ValueError:
            return ()
        return bounds


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------


class Settings:
    """全量配置。由 ``load_settings()`` 构造，不直接实例化。"""

    def __init__(
        self,
        *,
        runtime: RuntimeSettings,
        database: DatabaseSettings,
        redis: RedisSettings,
        snowflake: SnowflakeSettings,
        secret: SecretSettings,
        embedding: EmbeddingSettings,
        retrieval: RetrievalSettings,
        rerank: RerankSettings,
        idempotency: IdempotencySettings,
        logging: LoggingSettings,
    ) -> None:
        self.runtime = runtime
        self.database = database
        self.redis = redis
        self.snowflake = snowflake
        self.secret = secret
        self.embedding = embedding
        self.retrieval = retrieval
        self.rerank = rerank
        self.idempotency = idempotency
        self.logging = logging

    # -- 便于调试与日志：只输出非敏感项 ------------------------------------

    def describe(self) -> dict[str, Any]:
        """返回可安全写入日志的配置快照。

        **绝不包含任何密钥值**（设计 §10.1 部署约束第 2 条：KEK 不进日志、
        不进配置查询接口，配置查询只返回 ``kek_id``）。
        """
        return {
            "runtime": {
                "env": self.runtime.env,
                "bind": f"{self.runtime.bind_host}:{self.runtime.bind_port}",
            },
            "database": {
                "host": _redact_url(self.database.url),
                "pool": f"{self.database.pool_min}-{self.database.pool_max}",
            },
            "redis": {"host": _redact_url(self.redis.url)},
            "snowflake": {
                "datacenter_id": self.snowflake.datacenter_id,
                "worker_id": self.snowflake.worker_id,
            },
            "secret": {
                # 只报 kek_id 清单，永不返回值本身。
                "kek_ids": sorted(self.secret.kek_ids()),
                "active_kek_id": self.secret.active_kek_id,
            },
            "embedding": {
                "base_url": self.embedding.base_url,
                "model": self.embedding.model,
                "dim": self.embedding.dim,
                "api_key_set": bool(self.embedding.api_key),
            },
            "retrieval": {
                "active_index_version": self.retrieval.active_index_version,
                "default_k": self.retrieval.default_k,
                "max_k": self.retrieval.max_k,
            },
            "rerank": {"enabled": self.rerank.enabled, "provider": self.rerank.provider},
            "idempotency": {"ttl_seconds": self.idempotency.ttl_seconds},
            "logging": {"latency_buckets": list(self.logging.latency_buckets)},
        }


def _redact_url(url: str) -> str:
    """把连接串里的密码换成 ``***``，用于日志。"""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    credentials, _, host = rest.rpartition("@")
    user, _, _password = credentials.partition(":")
    return f"{scheme}://{user}:***@{host}"


# ---------------------------------------------------------------------------
# 加载与校验
# ---------------------------------------------------------------------------


def load_settings(
    env_file: str | Path | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> Settings:
    """加载配置并校验。**校验不通过即抛 ``ConfigError``**——调用方不得吞掉它。

    参数
    ----
    env_file:
        ``.env`` 文件路径。为 ``None`` 时，若当前目录存在 ``.env`` 则自动加载。
        真实环境变量**优先于** ``.env``（pydantic-settings 的既定行为）。
    environ:
        仅测试用：显式传入环境变量字典，避免污染进程环境。
    """
    if env_file is None:
        candidate = Path(".env")
        env_file = candidate if candidate.is_file() else None

    section_kwargs: dict[str, Any] = {"_env_file": env_file}
    if environ is not None:
        section_kwargs["_environ"] = environ

    sections: dict[str, Any] = {}
    missing: list[ConfigProblem] = []
    for name, section_type in (
        ("runtime", RuntimeSettings),
        ("database", DatabaseSettings),
        ("redis", RedisSettings),
        ("snowflake", SnowflakeSettings),
        ("secret", SecretSettings),
        ("embedding", EmbeddingSettings),
        ("retrieval", RetrievalSettings),
        ("rerank", RerankSettings),
        ("idempotency", IdempotencySettings),
        ("logging", LoggingSettings),
    ):
        try:
            sections[name] = section_type(**section_kwargs)
        except ValidationError as exc:
            for err in exc.errors():
                missing.append(
                    ConfigProblem(
                        section=name,
                        field=".".join(str(p) for p in err["loc"]) or name,
                        message=_format_validation_error(name, err),
                    )
                )

    if missing:
        raise ConfigError(missing)

    settings = Settings(**sections)
    report = validate(settings)
    for problem in report.warnings:
        # 警告走标准库 logging：此时结构化日志可能尚未初始化，不能依赖它。
        import logging as _logging

        _logging.getLogger(__name__).warning("[%s] %s", problem.section, problem.message)
    if not report.ok:
        raise ConfigError(report.errors)
    return settings


def _format_validation_error(section: str, err: Mapping[str, object]) -> str:
    raw_loc = err.get("loc")
    location = ".".join(str(p) for p in raw_loc) if isinstance(raw_loc, (list, tuple)) else ""
    loc = location or section
    message = err.get("msg", "")
    return f"字段 {loc} 非法或缺失（{message}）。请检查环境变量 {ENV_PREFIX}{section.upper()}_*"


def validate(settings: Settings) -> ConfigReport:
    """纯配置校验——**不连数据库**。

    依赖数据库的两项启动校验（设计 §10.1 的 KEK 覆盖度、§6.5 的索引模型一致性）
    需要读取 ``credential`` 与 ``index_meta`` 表，放在 :mod:`toolhive.startup`，
    由 B1 提供连接池后调用。
    """
    report = ConfigReport()

    # ---- database -------------------------------------------------------
    if not settings.database.url.startswith(("postgresql://", "postgres://")):
        report.problems.append(
            ConfigProblem("database", "url", "连接串必须以 postgresql:// 或 postgres:// 开头")
        )
    if settings.database.pool_min < 1:
        report.problems.append(ConfigProblem("database", "pool_min", "必须 >= 1"))
    if settings.database.pool_max < settings.database.pool_min:
        report.problems.append(
            ConfigProblem(
                "database", "pool_max", f"必须 >= pool_min（{settings.database.pool_min}）"
            )
        )
    if settings.database.command_timeout <= 0:
        report.problems.append(ConfigProblem("database", "command_timeout", "必须 > 0"))

    # ---- redis ----------------------------------------------------------
    if not settings.redis.url.startswith(("redis://", "rediss://", "unix://")):
        report.problems.append(
            ConfigProblem("redis", "url", "连接串必须以 redis:// 或 rediss:// 开头")
        )

    # ---- snowflake（设计 §4.4）------------------------------------------
    # 位分配 1 符号 + 41 时间戳 + 5 数据中心 + 5 机器 + 12 序列，
    # 因此数据中心与机器各占 5 位，取值 0..31。上限来自设计 §4.4，不要在这里放宽或收紧。
    if not 0 <= settings.snowflake.datacenter_id <= 31:
        report.problems.append(
            ConfigProblem("snowflake", "datacenter_id", "必须在 0..31（5 位，设计 §4.4）")
        )
    if not 0 <= settings.snowflake.worker_id <= 31:
        report.problems.append(
            ConfigProblem("snowflake", "worker_id", "必须在 0..31（5 位，设计 §4.4）")
        )

    # ---- secret（§10.1）-------------------------------------------------
    parsed_keks = settings.secret._parsed()
    if not parsed_keks:
        report.problems.append(
            ConfigProblem("secret", "keks", "必须是 JSON 对象，形如 {\"k1\": \"<32 字节 base64>\"}")
        )
    else:
        for kek_id, value in parsed_keks.items():
            try:
                raw = base64.b64decode(value, validate=True)
            except (binascii.Error, ValueError):
                report.problems.append(
                    ConfigProblem("secret", "keks", f"KEK {kek_id!r} 不是合法的 base64")
                )
                continue
            if len(raw) != 32:
                report.problems.append(
                    ConfigProblem(
                        "secret", "keks", f"KEK {kek_id!r} 解码后 {len(raw)} 字节，AES-256 要求 32"
                    )
                )
        if settings.secret.active_kek_id not in parsed_keks:
            report.problems.append(
                ConfigProblem(
                    "secret",
                    "active_kek_id",
                    f"{settings.secret.active_kek_id!r} 不在 KEKS 中"
                    f"（现有：{sorted(parsed_keks)}）",
                )
            )

    # ---- embedding（§6.4 / §6.5）----------------------------------------
    if not settings.embedding.base_url.startswith(("http://", "https://")):
        report.problems.append(
            ConfigProblem("embedding", "base_url", "必须以 http:// 或 https:// 开头")
        )
    if not settings.embedding.model:
        report.problems.append(ConfigProblem("embedding", "model", "不得为空"))
    if settings.embedding.dim <= 0:
        report.problems.append(ConfigProblem("embedding", "dim", "必须 > 0"))
    if settings.embedding.timeout_seconds <= 0:
        report.problems.append(ConfigProblem("embedding", "timeout_seconds", "必须 > 0"))
    if not settings.embedding.api_key:
        # 不拒绝启动：设计 §6.6 规定向量服务不可用时**降级为纯关键词检索**（degraded=true）。
        # 但缺 Key 是明确的部署失误，必须显式告警。
        report.problems.append(
            ConfigProblem(
                "embedding",
                "api_key",
                "未配置：检索将退化为纯关键词（设计 §6.6），请确认这是有意为之",
                severity="warning",
            )
        )

    # ---- retrieval（§6.1）-----------------------------------------------
    if not settings.retrieval.active_index_version:
        report.problems.append(
            ConfigProblem("retrieval", "active_index_version", "不得为空（设计 §6.5 要求显式指定）")
        )
    if settings.retrieval.default_k < 1:
        report.problems.append(ConfigProblem("retrieval", "default_k", "必须 >= 1"))
    if not 1 <= settings.retrieval.max_k <= MAX_SEARCH_K:
        report.problems.append(
            ConfigProblem(
                "retrieval",
                "max_k",
                f"必须在 1..{MAX_SEARCH_K}（设计 §6.1 规定上限 {MAX_SEARCH_K}）",
            )
        )
    if settings.retrieval.default_k > settings.retrieval.max_k:
        report.problems.append(
            ConfigProblem(
                "retrieval",
                "default_k",
                f"不得大于 max_k（{settings.retrieval.default_k} > {settings.retrieval.max_k}）",
            )
        )
    if settings.retrieval.description_snippet_chars < 1:
        report.problems.append(
            ConfigProblem("retrieval", "description_snippet_chars", "必须 >= 1")
        )

    # ---- rerank（§6.2）：关闭时允许留空；开启时必须齐全 ------------------
    if settings.rerank.enabled:
        for name, value in (
            ("endpoint", settings.rerank.endpoint),
            ("model", settings.rerank.model),
            ("api_key", settings.rerank.api_key),
        ):
            if not value:
                report.problems.append(
                    ConfigProblem("rerank", name, f"精排已启用（enabled=true）时 {name} 不得为空")
                )
        if settings.rerank.endpoint and not settings.rerank.endpoint.startswith(("http://", "https://")):
            report.problems.append(
                ConfigProblem("rerank", "endpoint", "必须以 http:// 或 https:// 开头")
            )
        if settings.rerank.timeout_ms <= 0:
            report.problems.append(ConfigProblem("rerank", "timeout_ms", "必须 > 0"))
        if settings.rerank.max_candidates < 1:
            report.problems.append(ConfigProblem("rerank", "max_candidates", "必须 >= 1"))

    # ---- idempotency（§7.2）---------------------------------------------
    if settings.idempotency.ttl_seconds <= 0:
        report.problems.append(ConfigProblem("idempotency", "ttl_seconds", "必须 > 0"))
    if settings.idempotency.max_result_bytes < 1:
        report.problems.append(ConfigProblem("idempotency", "max_result_bytes", "必须 >= 1"))

    # ---- logging（§11）：桶边界必须递增且非空 ----------------------------
    buckets = settings.logging.latency_buckets
    if not buckets:
        report.problems.append(
            ConfigProblem(
                "logging",
                "latency_buckets_ms",
                "解析失败或为空，应为逗号分隔的毫秒整数，如 10,25,50,100,200,500,1000,2000",
            )
        )
    elif any(b <= 0 for b in buckets):
        report.problems.append(ConfigProblem("logging", "latency_buckets_ms", "桶边界必须 > 0"))

    return report


def load_settings_or_exit(env_file: str | Path | None = None) -> Settings:
    """加载配置；失败则打印所有问题并**以非零码结束进程**。

    这是应用入口（REST 前端、CLI）应当调用的函数——保证"拒绝启动"是真的启动不了，
    而不是打条日志继续跑。
    """
    try:
        return load_settings(env_file)
    except ConfigError as exc:
        import sys

        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


def env_file_exists(path: str | Path = ".env") -> bool:
    """``.env`` 是否存在——供启动日志说明配置来源。"""
    return Path(path).is_file() or os.environ.get(f"{ENV_PREFIX}ENV_FILE") is not None
