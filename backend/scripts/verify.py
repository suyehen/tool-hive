"""ToolHive 手动验证脚本（任务 A5）。

    F:\\soft\\anaconda\\envs\\toolhive\\python.exe scripts\\verify.py

逐条输出通过/失败/跳过，任一失败以非零码退出：

===========  ==========================================================
1. lint      ``ruff check .``
2. types     ``mypy src tests scripts``
3. arch      架构断言（设计 §14.1 的全部约束，逐条一个断言）
4. runtime   本地异常路径回归（无外部服务）
5. integration 显式指定配置后运行严格 selfcheck 与隔离 schema 的领域验证；未指定时 SKIP
6. config    配置系统冒烟：从 ``.env`` 加载并做启动校验（**只打印脱敏快照**）
===========  ==========================================================

设计依据：§14.3 保留架构断言与高影响异常路径的本地回归，
本脚本不做 CI、不做测试框架，只把验证串成一条命令——
目的是让"改完顺手跑一下"的成本低到不会被跳过。

用法::

    python scripts/verify.py                 # 本地验证及配置；真实集成默认 SKIP
    python scripts/verify.py --no-config     # 跳过需要 .env 的那段
    python scripts/verify.py --only arch     # 只跑架构断言
    python scripts/verify.py --no-config --integration-env .env.test  # 严格集成
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: 后端工程根目录（= 仓库根下的 backend/）。ruff / mypy / .env 都相对于它。
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Windows 控制台默认编码可能是 cp950 / cp936，本脚本输出全为中文，
# 不重设编码会直接抛 UnicodeEncodeError 而掩盖真正的检查结果。
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

STAGES = ("lint", "types", "arch", "runtime", "integration", "config")

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass
class StageResult:
    """一段的结果。``lines`` 是要原样打印的细节。"""

    name: str
    status: str
    lines: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == FAIL


# ---------------------------------------------------------------------------
# 1. lint
# ---------------------------------------------------------------------------


def run_lint() -> StageResult:
    result = _run_tool([sys.executable, "-m", "ruff", "check", "."])
    if result.returncode == 0:
        return StageResult("lint", PASS, ["ruff check . 零问题"])
    return StageResult("lint", FAIL, _tail(result.stdout + result.stderr))


# ---------------------------------------------------------------------------
# 2. types
# ---------------------------------------------------------------------------


def run_types() -> StageResult:
    result = _run_tool(
        [sys.executable, "-m", "mypy", "src", "tests", "scripts"],
    )
    if result.returncode == 0:
        return StageResult("types", PASS, ["mypy src tests scripts 零错误"])
    return StageResult("types", FAIL, _tail(result.stdout + result.stderr))


# ---------------------------------------------------------------------------
# 3. 架构断言
# ---------------------------------------------------------------------------


def run_arch() -> StageResult:
    from tests.architecture import ASSERTIONS

    lines: list[str] = []
    failed = 0

    for assertion in ASSERTIONS:
        try:
            violations = assertion.run()
        except Exception as exc:
            violations = [f"断言执行异常：{type(exc).__name__}: {exc}"]

        if violations:
            failed += 1
            lines.append(f"{FAIL}  {assertion.name}")
            lines.append(f"      依据：{assertion.design_ref}")
            lines.extend(f"  {line}" for line in violations)
        else:
            lines.append(f"{PASS}  {assertion.name}")

    header = f"架构断言 {len(ASSERTIONS) - failed}/{len(ASSERTIONS)} 通过"
    return StageResult("arch", FAIL if failed else PASS, [header, *lines])


# ---------------------------------------------------------------------------
# 4. 配置冒烟
# ---------------------------------------------------------------------------


def _config_guard() -> list[str]:
    """配置系统自检——**不读 ``.env``，也不依赖机器上的环境变量**。

    存在的理由：``load_settings(environ=...)`` 曾经是**写了但完全没生效**的死参数——
    实现把 ``_environ`` 传给了 pydantic-settings，而它不认这个参数，
    又因为各分区设了 ``extra="ignore"``，于是被**静默丢弃**。
    当时 config 段只走真实 ``.env`` 这条路径，所以这个 bug 一直测不出来。

    下面四项专门覆盖"显式传入一份配置字典"这条路径：
    值要真的生效、未给的项要回落默认值、非法配置仍要被拒、退出后环境要还原。
    """
    from toolhive.config import ConfigError, load_settings

    # 32 个零字节的 base64 —— 明显是占位值，不是真密钥。
    dummy_kek = base64.b64encode(b"\x00" * 32).decode()
    base = {
        "TOOLHIVE_DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/toolhive",
        "TOOLHIVE_REDIS_URL": "redis://:p@127.0.0.1:6379/1",
        "TOOLHIVE_KEKS": json.dumps({"k1": dummy_kek}),
        "TOOLHIVE_ACTIVE_KEK_ID": "k1",
        "TOOLHIVE_EMBEDDING_BASE_URL": "https://example.invalid",
        "TOOLHIVE_EMBEDDING_MODEL": "m",
        # 给个占位 key：否则每次调用都会触发「api_key 未配置」告警，
        # 而那条告警不是本守护要覆盖的路径，只会把输出刷满。
        "TOOLHIVE_EMBEDDING_API_KEY": "dummy-not-a-real-key",
    }
    problems: list[str] = []

    # ① environ= 必须生效，且值要真的反映到结果里
    try:
        probe = load_settings(
            environ={
                **base,
                "TOOLHIVE_DB_POOL_MAX": "7",
                "TOOLHIVE_SNOWFLAKE_WORKER_ID": "9",
            }
        )
    except ConfigError as exc:
        problems.append(
            f"environ= 未生效（{len(exc.problems)} 条问题，首条：{exc.problems[0].message[:60]}）"
        )
    else:
        if probe.database.pool_max != 7 or probe.snowflake.worker_id != 9:
            problems.append(
                "environ= 被接受但值没生效："
                f"pool_max={probe.database.pool_max}（期望 7）、"
                f"worker_id={probe.snowflake.worker_id}（期望 9）"
            )

    # ② 未提供的项必须回落默认值 —— 证明它是「完整替代」，没有偷偷去读进程环境
    try:
        fallback = load_settings(environ=base)
        if fallback.database.pool_max != 20:
            problems.append(
                f"未提供的项没有回落默认值：pool_max={fallback.database.pool_max}（期望 20）"
            )
    except ConfigError as exc:
        problems.append(f"最小可用配置被判非法（{len(exc.problems)} 条）")

    # ③ 非法配置仍必须被拒 —— 否则无法区分「校验通过」与「校验根本没跑」
    invalid_cases = (
        (
            "KEK 不足 32 字节",
            {**base, "TOOLHIVE_KEKS": json.dumps({"k1": base64.b64encode(b"x" * 16).decode()})},
        ),
        ("ACTIVE_KEK_ID 不存在", {**base, "TOOLHIVE_ACTIVE_KEK_ID": "k9"}),
        ("worker_id 超范围", {**base, "TOOLHIVE_SNOWFLAKE_WORKER_ID": "99"}),
    )
    for label, cfg in invalid_cases:
        try:
            load_settings(environ=cfg)
        except ConfigError:
            continue
        problems.append(f"非法配置未被拒绝：{label}")

    # ④ 退出后进程环境必须原样还原，不能把测试值泄漏到进程里
    before = dict(os.environ)
    load_settings(environ={**base, "TOOLHIVE_VERIFY_SENTINEL": "1"})
    if dict(os.environ) != before:
        problems.append("environ= 退出后未还原进程环境（有泄漏）")

    return problems


def run_config() -> StageResult:
    lines: list[str] = []

    guard_problems = _config_guard()
    if guard_problems:
        lines.append(f"{FAIL}  配置系统自检（environ= 路径）")
        lines.extend(f"      - {p}" for p in guard_problems)
    else:
        lines.append(
            f"{PASS}  配置系统自检（environ= 路径）：值生效、默认值回落、非法被拒、环境还原"
        )

    env_file = BACKEND_ROOT / ".env"
    if not env_file.is_file():
        lines.append(f"{SKIP}  未找到 {env_file.name}，未做真实配置校验")
        lines.append("      部署步骤见 docs/04-部署前置条件 §3")
        return StageResult("config", FAIL if guard_problems else SKIP, lines)

    from toolhive.config import ConfigError, load_settings

    try:
        settings = load_settings(env_file)
    except ConfigError as exc:
        lines.append(f"{FAIL}  真实 {env_file.name} 未通过校验")
        lines.extend(f"      {line}" for line in str(exc).splitlines())
        return StageResult("config", FAIL, lines)

    lines.append(f"{PASS}  真实 {env_file.name} 校验通过。脱敏快照（**不含任何密钥值**）：")
    lines.extend(
        f"  {line}"
        for line in json.dumps(settings.describe(), ensure_ascii=False, indent=2).splitlines()
    )
    return StageResult("config", FAIL if guard_problems else PASS, lines)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _run_tool(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _tail(text: str, limit: int = 40) -> list[str]:
    """截取工具输出的尾部——错误通常在最下面，全量打印会淹没结论。"""
    stripped = [line for line in text.splitlines() if line.strip()]
    if len(stripped) <= limit:
        return stripped
    return [f"（前 {len(stripped) - limit} 行省略）", *stripped[-limit:]]


def run_runtime() -> StageResult:
    lines: list[str] = []
    for script in ("regression.py", "domain_regression.py", "policy_regression.py"):
        result = _run_tool([sys.executable, str(BACKEND_ROOT / "scripts" / script)])
        lines.extend(_tail(result.stdout + result.stderr))
        if result.returncode != 0:
            return StageResult("runtime", FAIL, lines)
    return StageResult("runtime", PASS, lines)


def run_integration(env_file: Path | None, *, required: bool = False) -> StageResult:
    """显式选择配置才写基础设施；未选择时清楚报告 SKIP。"""
    if env_file is None:
        return StageResult(
            "integration",
            FAIL if required else SKIP,
            [
                "未执行真实 PostgreSQL/Redis 验证；使用 --integration-env <隔离环境配置>",
                "该阶段会创建临时表、缓存键及随机 schema；严格模式不允许依赖不可达时跳过。",
            ],
        )
    if not env_file.is_file():
        return StageResult("integration", FAIL, ["指定的集成验证配置文件不存在"])
    lines: list[str] = []
    for script, flags in (
        ("selfcheck.py", ["--strict"]),
        ("domain_selfcheck.py", []),
        ("policy_selfcheck.py", []),
    ):
        result = _run_tool(
            [
                sys.executable,
                str(BACKEND_ROOT / "scripts" / script),
                *flags,
                "--env-file",
                str(env_file.resolve()),
            ]
        )
        lines.extend(_tail(result.stdout + result.stderr, limit=100))
        if result.returncode != 0:
            return StageResult("integration", FAIL, lines)
    return StageResult("integration", PASS, lines)


RUNNERS = {
    "lint": run_lint,
    "types": run_types,
    "arch": run_arch,
    "runtime": run_runtime,
    "config": run_config,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify",
        description="ToolHive 验证：静态、本地回归、可选严格集成及配置冒烟",
    )
    parser.add_argument(
        "--integration-env",
        type=Path,
        help="执行会写入临时表/缓存键的严格集成验证；指定隔离环境配置文件",
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=STAGES,
        help="只跑指定段（可重复）。不指定则全部跑。",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="跳过读取 .env 的 config 段，仍执行本地运行时回归",
    )
    args = parser.parse_args(argv)

    selected = list(STAGES)
    if args.only:
        selected = [s for s in STAGES if s in set(args.only)]
    if args.no_config:
        selected = [s for s in selected if s != "config"]
    if args.integration_env and "integration" not in selected:
        selected.append("integration")

    print("ToolHive 手动验证（任务 A5）")
    print("=" * 72)

    results: list[StageResult] = []
    for stage in selected:
        print(f"\n--- {stage} ---")
        if stage == "integration":
            result = run_integration(
                args.integration_env,
                required=bool(args.only and "integration" in args.only),
            )
        else:
            result = RUNNERS[stage]()
        for line in result.lines:
            print(line)
        print(f"[{result.status}] {stage}")
        results.append(result)

    print("\n" + "=" * 72)
    failed = [r for r in results if r.failed]
    skipped = [r for r in results if r.status == SKIP]

    summary = "  ".join(f"{r.name}={r.status}" for r in results)
    print(summary)

    if failed:
        print(f"\n❌ {len(failed)} 段未通过：" + ", ".join(r.name for r in failed))
        return 1
    if skipped:
        print(f"\n✅ 已跑完（跳过 {len(skipped)} 段：" + ", ".join(r.name for r in skipped) + "）")
        return 0
    print("\n✅ 全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
