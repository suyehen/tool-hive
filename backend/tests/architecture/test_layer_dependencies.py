"""架构断言 2、3：层次依赖方向。

* **设计 §14.1 第 2 条**：``adapters/`` 不得反向依赖 ``protocols/``。
* **设计 §14.1 第 3 条**：``protocols/`` 之间不得互相 import。

为什么这两条重要：它们保证"新增一种协议"不会牵动基础设施层，
也不会让两个协议适配器通过共享代码偷偷长出耦合——那正是 C1（两套并行编排）的起点。

> **命名说明**：``protocols/`` 就是设计里说的「协议前端」（§3.3 / §8），
> 即 REST / MCP / 管理 API 这些**后端适配器**，不是浏览器界面。
> 该目录原本叫 ``frontends/``，与仓库根目录的 ``frontend/``（管理台界面，TypeScript）
> 一字之差而含义完全不同，故改名为 ``protocols/``。
"""

from __future__ import annotations

from pathlib import Path

from tests.architecture._harness import (
    PACKAGE_ROOT,
    Assertion,
    format_violations,
    imported_project_subpackages,
    python_files,
    relative_display,
    under,
)

ADAPTERS = ("adapters",)
PROTOCOLS = ("protocols",)


def check_adapters_do_not_depend_on_protocols() -> list[str]:
    """``adapters/`` 里出现 ``toolhive.protocols.*`` 即为违规。"""
    offenders: list[str] = []
    for path in python_files("adapters"):
        hits = sorted(
            parts for parts in imported_project_subpackages(path) if under(parts, PROTOCOLS)
        )
        if hits:
            offenders.append(f"{relative_display(path)} → {['.'.join(h) for h in hits]}")

    return format_violations(
        "adapters/ 不得反向依赖 protocols/（设计 §14.1 第 2 条）："
        "基础设施层不应知道协议适配器的存在",
        offenders,
    )


def check_protocols_are_independent() -> list[str]:
    """``protocols/X`` 里出现 ``toolhive.protocols.Y``（Y != X）即为违规。"""
    offenders: list[str] = []
    for path in python_files("protocols"):
        own = _own_protocol(path)
        if own is None:
            # protocols/__init__.py 自身不归属任何具体协议，跳过。
            continue
        for parts in imported_project_subpackages(path):
            if not under(parts, PROTOCOLS) or len(parts) < 2:
                continue
            other = parts[1]
            if other != own:
                offenders.append(
                    f"{relative_display(path)} → toolhive.protocols.{other}（本文件属 {own}）"
                )

    return format_violations(
        "protocols/ 之间不得互相 import（设计 §14.1 第 3 条）："
        "共享逻辑必须下沉到 core/，否则会演变成第二份编排",
        offenders,
    )


def _own_protocol(path: Path) -> str | None:
    """判定文件属于哪一个协议适配器（``rest`` / ``mcp`` / ``admin``）。"""
    try:
        relative = path.resolve().relative_to(PACKAGE_ROOT / "protocols")
    except ValueError:  # pragma: no cover
        return None
    return relative.parts[0] if len(relative.parts) > 1 else None


ASSERTIONS: tuple[Assertion, ...] = (
    Assertion(
        name="adapters_do_not_depend_on_protocols",
        design_ref="设计 §14.1 第 2 条",
        run=check_adapters_do_not_depend_on_protocols,
    ),
    Assertion(
        name="protocols_are_independent",
        design_ref="设计 §14.1 第 3 条",
        run=check_protocols_are_independent,
    ),
)
