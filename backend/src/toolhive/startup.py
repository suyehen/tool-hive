"""启动校验中**需要读数据库**的两项（任务 A2 的后半部分）。设计 §10.1 与 §6.5。

为什么单独一个模块
------------------
:mod:`toolhive.config` 的校验只读环境变量，**不连数据库**；
而这两项必须读库，且它们的失败同样是"拒绝启动"。把两者分开，
配置校验才能在没有任何基础设施时也跑得起来（例如 CI 里的架构断言）。

两项校验
--------
1. **KEK 覆盖度**（设计 §10.1）：若库里存在引用了 ``TOOLHIVE_KEKS`` 里没有的
   ``kek_id`` 的凭据，**拒绝启动**。原文的理由是"而不是等到某次调用才发现凭证解不开"。
2. **索引模型一致性**（设计 §6.5）：``retrieval.active_index_version`` 指向的
   ``index_meta`` 记录，其 ``model`` / ``dimension`` 必须与在线 ``embedding.model`` /
   ``dim`` 相同，否则**拒绝启动**。

   §6.5 特别强调校验方式不能是"两个配置项必须相等"——那会卡死重建流程：
   重建新索引本来就需要新模型，而 ``active_index_version`` 仍指向旧模型，两者必然不等。
   所以这里比对的是 **``index_meta`` 元数据**，不是配置。

为什么用 ``Protocol`` 而不是直接 import asyncpg
----------------------------------------------
数据库连接由 ``adapters/db``（任务 B1）负责创建，本模块**只消费**一个能 ``fetch`` 的对象。
好处有两点：不引入对驱动类型的耦合；以及**可以用假连接验证分支逻辑**，
不必等数据库就绪。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from toolhive.config import ConfigError, ConfigProblem, ConfigReport, Settings

__all__ = [
    "STARTUP_CHECKS",
    "StartupCheck",
    "check_index_model_consistency",
    "check_kek_coverage",
    "run_startup_checks",
]


@runtime_checkable
class DbConnection(Protocol):
    """启动校验需要的最小数据库能力。

    ``asyncpg.Connection`` 与 ``asyncpg.Pool`` 都结构化满足它——
    无需继承、无需适配器。
    """

    async def fetch(self, query: str, *args: object) -> Sequence[Mapping[str, Any]]:
        """执行查询并返回全部行。"""
        ...

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, Any] | None:
        """执行查询并返回首行，无结果时返回 ``None``。"""
        ...


@dataclass(frozen=True)
class StartupCheck:
    """一项启动校验。"""

    name: str
    #: 设计依据，便于失败时直接定位规则原文。
    design_ref: str
    run: Callable[[DbConnection, Settings], Awaitable[list[ConfigProblem]]]


# ---------------------------------------------------------------------------
# 校验 1：KEK 覆盖度（设计 §10.1）
# ---------------------------------------------------------------------------


async def check_kek_coverage(conn: DbConnection, settings: Settings) -> list[ConfigProblem]:
    """库里是否有凭据引用了不存在的 KEK。

    这通常发生在两种运维事故之后：
    * 轮换第 4 步（从 ``TOOLHIVE_KEKS`` 移除旧 KEK）执行得太早，存量凭据还没重包装完；
    * 换环境时把 ``.env`` 里的 KEK 换成了新生成的，却没有迁移密文。

    两种情况都**必须拒绝启动**——否则要等到某个真实调用去解密时才炸，
    而且那时看到的是"上游报错"，极易误判成上游抖动（设计 §10.1 部署约束第 3 条）。
    """
    rows = await conn.fetch(
        "SELECT DISTINCT kek_id FROM credential WHERE kek_id IS NOT NULL",
    )
    referenced = {str(row["kek_id"]) for row in rows}
    known = settings.secret.kek_ids()

    unknown = sorted(referenced - known)
    if not unknown:
        return []

    return [
        ConfigProblem(
            section="startup",
            field="TOOLHIVE_KEKS",
            message=(
                f"凭据表引用了 {len(unknown)} 个不存在的 KEK：{unknown}；"
                f"当前 KEKS 提供 {sorted(known)}。"
                "拒绝启动——按设计 §10.1，KEK 轮换的第 4 步必须在全部凭据重包装完成后执行"
            ),
        )
    ]


# ---------------------------------------------------------------------------
# 校验 2：索引模型一致性（设计 §6.5）
# ---------------------------------------------------------------------------


async def check_index_model_consistency(
    conn: DbConnection, settings: Settings
) -> list[ConfigProblem]:
    """``active_index_version`` 元数据的模型与维度是否与在线 embedding 配置一致。"""
    version = settings.retrieval.active_index_version
    row = await conn.fetchrow(
        "SELECT model, dimension, status FROM index_meta WHERE index_version = $1",
        version,
    )

    if row is None:
        return [
            ConfigProblem(
                section="startup",
                field="TOOLHIVE_RETRIEVAL_ACTIVE_INDEX_VERSION",
                message=(
                    f"index_meta 中不存在 index_version={version!r} 的记录。"
                    "检索没有可用索引——先执行 `toolhive rebuild-index` 建立索引版本"
                ),
            )
        ]

    problems: list[ConfigProblem] = []
    meta_model = str(row["model"])
    meta_dim = int(row["dimension"])

    if meta_model != settings.embedding.model:
        problems.append(
            ConfigProblem(
                section="startup",
                field="TOOLHIVE_EMBEDDING_MODEL",
                message=(
                    f"在线 embedding.model={settings.embedding.model!r} 与索引版本 "
                    f"{version!r} 的 model={meta_model!r} 不一致。"
                    "向量空间不同，检索结果将无意义——按设计 §6.5 拒绝启动"
                ),
            )
        )
    if meta_dim != settings.embedding.dim:
        problems.append(
            ConfigProblem(
                section="startup",
                field="TOOLHIVE_EMBEDDING_DIM",
                message=(
                    f"在线 embedding.dim={settings.embedding.dim} 与索引版本 "
                    f"{version!r} 的 dimension={meta_dim} 不一致（设计 §6.5）"
                ),
            )
        )

    # 一致性通过、但 index_meta 里"活跃"的是另一个版本 —— 说明配置与状态机已经漂移。
    # 这属于可疑状态而非硬错误，因此只告警：切换过程中配置先行是允许的。
    if not problems and str(row["status"]) != "active":
        problems.append(
            ConfigProblem(
                section="startup",
                field="TOOLHIVE_RETRIEVAL_ACTIVE_INDEX_VERSION",
                message=(
                    f"index_version={version!r} 的 status={row['status']!r} 而不是 'active'，"
                    "说明配置指向的版本与 index_meta 的单活版本不一致，请确认这是切换过程中的中间态"
                ),
                severity="warning",
            )
        )

    return problems


#: 全部需要数据库的启动校验。B1 提供连接池后，在应用启动路径上调用
#: :func:`run_startup_checks` 即可；将来新增校验只需在此登记。
STARTUP_CHECKS: tuple[StartupCheck, ...] = (
    StartupCheck(
        name="kek_coverage",
        design_ref="设计 §10.1（启动自检：密文引用的 kek_id 必须都在 TOOLHIVE_KEKS 里）",
        run=check_kek_coverage,
    ),
    StartupCheck(
        name="index_model_consistency",
        design_ref=(
            "设计 §6.5（启动校验：active_index_version 元数据里的模型 == 在线 embedding.model）"
        ),
        run=check_index_model_consistency,
    ),
)


async def run_startup_checks(conn: DbConnection, settings: Settings) -> ConfigReport:
    """依次执行全部启动校验，汇总问题。**不抛异常**，由调用方决定是否放行。"""
    report = ConfigReport()
    for check in STARTUP_CHECKS:
        report.problems.extend(await check.run(conn, settings))
    return report


async def require_startup_checks(conn: DbConnection, settings: Settings) -> None:
    """执行启动校验，**任一 error 即抛 :class:`ConfigError`**（拒绝启动）。"""
    report = await run_startup_checks(conn, settings)
    if not report.ok:
        raise ConfigError(report.errors)
