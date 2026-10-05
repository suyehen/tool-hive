"""ToolHive 手动验证脚本（任务 A5）。

    F:\\soft\\anaconda\\envs\\toolhive\\python.exe scripts\\verify.py

一条命令跑完四段，逐条输出通过/失败，任一失败以非零码退出：

===========  ==========================================================
1. lint      ``ruff check .``
2. types     ``mypy src tests scripts``
3. arch      架构断言（设计 §14.1 的全部约束，逐条一个断言）
4. config    配置系统冒烟：从 ``.env`` 加载并做启动校验（**只打印脱敏快照**）
===========  ==========================================================

设计依据：§14.3 规定 M0 的自动化验证**只保留架构断言**，
因此本脚本不做 CI、不做测试框架，只把"最该跑的那几项"串成一条命令——
目的是让"改完顺手跑一下"的成本低到不会被跳过。

用法::

    python scripts/verify.py                 # 四段全跑
    python scripts/verify.py --no-config     # 跳过需要 .env 的那段
    python scripts/verify.py --only arch     # 只跑架构断言
"""

from __future__ import annotations

import argparse
import io
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

STAGES = ("lint", "types", "arch", "config")

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


def run_config() -> StageResult:
    env_file = BACKEND_ROOT / ".env"
    if not env_file.is_file():
        return StageResult(
            "config",
            SKIP,
            [f"未找到 {env_file.name}，跳过。部署步骤见 docs/04-部署前置条件 §3"],
        )

    try:
        from toolhive.config import ConfigError, load_settings
    except ImportError as exc:
        return StageResult("config", FAIL, [f"无法 import toolhive.config：{exc}"])

    try:
        settings = load_settings(env_file)
    except ConfigError as exc:
        return StageResult("config", FAIL, str(exc).splitlines())

    import json

    lines = ["配置校验通过。脱敏快照（**不含任何密钥值**）："]
    lines.extend(
        f"  {line}"
        for line in json.dumps(settings.describe(), ensure_ascii=False, indent=2).splitlines()
    )
    return StageResult("config", PASS, lines)


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


RUNNERS = {
    "lint": run_lint,
    "types": run_types,
    "arch": run_arch,
    "config": run_config,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify",
        description="ToolHive 手动验证：lint + 类型 + 架构断言 + 配置冒烟",
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
        help="跳过 config 段（等价于 --only lint --only types --only arch）",
    )
    args = parser.parse_args(argv)

    selected = list(STAGES)
    if args.only:
        selected = [s for s in STAGES if s in set(args.only)]
    if args.no_config:
        selected = [s for s in selected if s != "config"]

    print("ToolHive 手动验证（任务 A5）")
    print("=" * 72)

    results: list[StageResult] = []
    for stage in selected:
        print(f"\n--- {stage} ---")
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
