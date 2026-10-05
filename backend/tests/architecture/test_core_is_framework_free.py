"""架构断言 1：``core/`` 不得依赖 Web 框架或协议库。

**设计 §14.1 第 1 条**，也是设计 §3.3 说的"一条硬规则"：

    core/ 不允许 import fastapi、starlette、mcp、uvicorn。

理由是 C1 教训——上一版执行编排写了两份（REST 一份、MCP 一份），
MCP 通道因此没有配额与幂等。**执行逻辑一旦长在 Web 框架里，加一种协议就要复制一遍。**
"""

from __future__ import annotations

from tests.architecture._harness import (
    Assertion,
    format_violations,
    python_files,
    relative_display,
    top_level_import_roots,
)

#: 设计 §14.1 第 1 条明确列出的四个包，不多不少。
FORBIDDEN_FRAMEWORKS = frozenset({"fastapi", "starlette", "mcp", "uvicorn"})


def check_core_is_framework_free() -> list[str]:
    offenders: list[str] = []
    for path in python_files("core"):
        bad = top_level_import_roots(path) & FORBIDDEN_FRAMEWORKS
        if bad:
            offenders.append(f"{relative_display(path)} → {sorted(bad)}")

    return format_violations(
        f"core/ 不得 import {sorted(FORBIDDEN_FRAMEWORKS)}"
        "（设计 §14.1 第 1 条）：执行逻辑必须与协议无关",
        offenders,
    )


ASSERTIONS: tuple[Assertion, ...] = (
    Assertion(
        name="core_is_framework_free",
        design_ref="设计 §14.1 第 1 条 / §3.3",
        run=check_core_is_framework_free,
    ),
)
