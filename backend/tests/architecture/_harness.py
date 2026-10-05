"""架构断言的共用骨架（任务 A6）。

设计 §14.3 只保留**一条**自动化验证：架构断言。所以它必须足够好用来替代"靠人记住规则"。
两个设计要点：

1. **每条约束一个断言**，便于失败时直接定位是哪条规则被破坏（设计 §14.3 的验收要求）。
2. **每条断言自带设计出处**（``design_ref``），失败信息里直接给出规则原文的位置，
   让人不必回头翻文档猜"为什么不允许这样 import"。

断言函数返回**违规清单**（``list[str]``），空列表表示通过。不抛异常——
这样 :mod:`scripts.verify` 能把所有失败一次性列全，而不是跑一条改一条。
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

#: 后端工程根目录（= 仓库根下的 ``backend/``）。
#: 本文件位于 ``backend/tests/architecture/_harness.py``，故 parents[2] 即 backend/。
BACKEND_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = BACKEND_ROOT / "src" / "toolhive"

#: 本项目的顶层包名。用于识别"指向本项目内部"的 import。
PROJECT_PACKAGE = "toolhive"


@dataclass(frozen=True)
class Assertion:
    """一条架构约束。"""

    name: str
    #: 规则出处，失败信息里会原样打印，避免"知道违规但不知道依据"。
    design_ref: str
    run: Callable[[], list[str]]


def python_files(relative_dir: str) -> list[Path]:
    """列出 ``src/toolhive/<relative_dir>`` 下的全部 ``.py`` 文件（空目录返回空列表）。"""
    base = PACKAGE_ROOT / relative_dir
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py"))


def parse(path: Path) -> ast.Module:
    """解析 Python 源文件为 AST。

    用 AST 而不是正则：正则会被字符串字面量、注释与别名 import 骗过去，
    而"core/ 不得依赖 web 框架"这种约束一旦被绕过就失去意义。
    """
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# ---------------------------------------------------------------------------
# import 分析
# ---------------------------------------------------------------------------


def top_level_import_roots(path: Path) -> set[str]:
    """返回文件 import 的**顶层包名**。

    设计 §14.2 给了这个函数的实现范例；这里保持一致，只额外处理
    ``from . import x`` 这类没有 ``module`` 的相对 import（忽略它们——
    相对 import 不可能是第三方框架）。
    """
    roots: set[str] = set()
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.level == 0  # 只看绝对 import
        ):
            roots.add(node.module.split(".")[0])
    return roots


def project_imports(path: Path) -> set[str]:
    """返回文件对本项目内部模块的 import，统一成 ``toolhive.`` 开头的绝对路径。

    同时处理两种写法，因为两种都真实存在且都能绕过只查绝对 import 的断言：

    * 绝对：``from toolhive.protocols.rest import app``  → ``toolhive.protocols.rest``
    * 相对：``from ..protocols import rest``（在 ``toolhive.adapters.db`` 里）
      → 按文件所在包解析成绝对路径
    """
    package_parts = _package_parts(path)
    found: set[str] = set()

    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == PROJECT_PACKAGE or alias.name.startswith(f"{PROJECT_PACKAGE}."):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                if node.module == PROJECT_PACKAGE or node.module.startswith(f"{PROJECT_PACKAGE}."):
                    found.add(node.module)
            elif node.level > 0 and node.module:
                resolved = _resolve_relative(package_parts, node.level, node.module)
                if resolved:
                    found.add(resolved)
    return found


def _package_parts(path: Path) -> tuple[str, ...]:
    """文件所在包的绝对路径分量，例如 ``src/toolhive/adapters/db/session.py``
    → ``('toolhive', 'adapters', 'db')``。"""
    try:
        relative = path.resolve().relative_to(PACKAGE_ROOT)
    except ValueError:  # pragma: no cover - 断言只扫包内文件
        return ()
    return (PROJECT_PACKAGE, *relative.parent.parts)


def _resolve_relative(
    package_parts: tuple[str, ...], level: int, module: str
) -> str | None:
    """把相对 import 解析为绝对模块路径。

    ``level=1`` 表示当前包，``level=2`` 表示上一级，依此类推——与 Python 的语义一致。
    """
    if not package_parts:
        return None
    # level 个点：1 个点是当前包，所以回退 level-1 层。
    keep = len(package_parts) - (level - 1)
    if keep <= 0:
        return None
    base = package_parts[:keep]
    return ".".join((*base, module)) if module else ".".join(base)


def imported_project_subpackages(path: Path) -> set[tuple[str, ...]]:
    """本项目内部 import 的**子包分量元组**，例如 ``('protocols',)`` / ``('adapters', 'db')``。

    用于层次依赖断言：比对的是包路径分量，而不是字符串前缀——
    否则 ``toolhive.protocolsomething`` 会被 ``toolhive.protocols`` 误判为命中。
    """
    result: set[tuple[str, ...]] = set()
    for dotted in project_imports(path):
        parts = tuple(dotted.split("."))
        if parts and parts[0] == PROJECT_PACKAGE and len(parts) > 1:
            result.add(parts[1:])
    return result


def under(package_parts: tuple[str, ...], prefix: Sequence[str]) -> bool:
    """``package_parts`` 是否位于 ``prefix`` 之下（分量级比较，不是字符串前缀）。"""
    return len(package_parts) >= len(prefix) and package_parts[: len(prefix)] == tuple(prefix)


def format_violations(header: str, violations: Sequence[str]) -> list[str]:
    """把违规项包成带标题的多行消息，便于 verify.py 直接打印。"""
    if not violations:
        return []
    return [header, *(f"    - {v}" for v in violations)]


def relative_display(path: Path) -> str:
    """把绝对路径显示成相对 ``backend/`` 的路径，失败信息更短且可点开。"""
    try:
        return path.resolve().relative_to(BACKEND_ROOT).as_posix()
    except ValueError:  # pragma: no cover
        return str(path)


def _self_check() -> int:
    """``python -m tests.architecture._harness`` 时做一次自检，确认解析器本身没坏。"""
    roots = top_level_import_roots(PACKAGE_ROOT / "config.py")
    ok = "pydantic" in roots and "pydantic_settings" in roots
    print(f"harness 自检：config.py 的顶层 import 根 = {sorted(roots)}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_self_check())


def iter_assertion_modules() -> Iterator[str]:
    """架构断言模块的固定顺序，供 verify.py 与 ``__init__`` 共用。"""
    yield from (
        "test_core_is_framework_free",
        "test_layer_dependencies",
        "test_builtin_tools_are_pure",
        "test_tool_naming",
        "test_excluded_dependencies",
    )


__all__ = [
    "BACKEND_ROOT",
    "PACKAGE_ROOT",
    "PROJECT_PACKAGE",
    "Assertion",
    "format_violations",
    "imported_project_subpackages",
    "iter_assertion_modules",
    "parse",
    "project_imports",
    "python_files",
    "relative_display",
    "top_level_import_roots",
    "under",
]
