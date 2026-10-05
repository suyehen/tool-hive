"""架构断言 5：``builtin_tools/`` 必须是纯函数。

**设计 §14.1 第 5 条**：``builtin_tools/`` 不得 import ``httpx`` / ``sqlalchemy``。
配合设计 §16.6 的准入规则：只能是元能力（时间、UUID、哈希、编码转换）、
不得有业务语义、数量上限 10 个。

一处**有意扩展**（已在 :data:`FORBIDDEN_TOP_LEVEL` 中标注）：除设计明列的
``httpx`` / ``sqlalchemy`` 之外，还禁止 ``builtin_tools/`` import 本项目的
``toolhive.adapters``。理由是那条规则的**意图**是"保证纯函数"——
而 ``adapters`` 正是通往网络与数据库的门（``adapters.upstream`` 是 HTTP 客户端、
``adapters.db`` 是数据库）。允许这条路径等于让规则形同虚设。
若认为此项过严，删掉 :data:`FORBIDDEN_PROJECT_PREFIXES` 即可，不影响其它断言。
"""

from __future__ import annotations

from tests.architecture._harness import (
    Assertion,
    format_violations,
    imported_project_subpackages,
    python_files,
    relative_display,
    top_level_import_roots,
    under,
)

#: 设计 §14.1 第 5 条明列的两个第三方包。
FORBIDDEN_TOP_LEVEL = frozenset({"httpx", "sqlalchemy"})

#: 见模块文档说明的扩展项：禁止触达基础设施层。
FORBIDDEN_PROJECT_PREFIXES: tuple[tuple[str, ...], ...] = (("adapters",),)


def check_builtin_tools_are_pure() -> list[str]:
    offenders: list[str] = []

    for path in python_files("builtin_tools"):
        reasons: list[str] = []

        third_party = top_level_import_roots(path) & FORBIDDEN_TOP_LEVEL
        if third_party:
            reasons.append(f"第三方包 {sorted(third_party)}")

        project_hits = sorted(
            ".".join(parts)
            for parts in imported_project_subpackages(path)
            if any(under(parts, prefix) for prefix in FORBIDDEN_PROJECT_PREFIXES)
        )
        if project_hits:
            reasons.append(f"基础设施层 {['toolhive.' + h for h in project_hits]}")

        if reasons:
            offenders.append(f"{relative_display(path)} → {'；'.join(reasons)}")

    return format_violations(
        "builtin_tools/ 必须是纯函数：不得访问网络或数据库（设计 §14.1 第 5 条 / §16.6）",
        offenders,
    )


ASSERTIONS: tuple[Assertion, ...] = (
    Assertion(
        name="builtin_tools_are_pure",
        design_ref="设计 §14.1 第 5 条 / §16.6",
        run=check_builtin_tools_are_pure,
    ),
)
