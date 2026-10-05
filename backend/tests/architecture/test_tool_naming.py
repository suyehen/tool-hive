"""架构断言 4：工具命名必须符合 ``<domain>.<system>.<entity>.<action>``。

**设计 §14.1 第 4 条**，规则的完整说明在设计 §5.3：

    例：crm.customer.query / aftersale.ticket.create / erp.inventory.adjust

本断言做两件事：

1. **钉住契约**：用 §5.3 的例子验证模式本身——合法样例必须通过、畸形样例必须被拒。
   这防止后来者（任务 G3 的命名规范化）另起一套模式。
2. **检查实际声明的工具编码**：扫描平台自己声明的工具编码，逐条比对。

关于第 2 点的现状：**M0 的平台自建工具只有 ``builtin_tools/``**（设计 §16.6），
而模块 A 阶段它还是空的，因此这一半断言当前是空过。
任务 G3 引入导入器后，被导入工具的 ``code`` 由 ``ingestion/normalizer.py`` 生成，
届时应把该模块的产物也纳入扫描范围——见 :data:`SCAN_DIRS`。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.architecture._harness import (
    BACKEND_ROOT,
    Assertion,
    format_violations,
    parse,
    relative_display,
)

#: 单段的形态：snake_case —— 小写字母开头，不能以下划线开头或结尾，
#: 也不能出现连续下划线。比 ``[a-z0-9_]*`` 更严，挡掉 ``query_`` / ``__x`` 这类写法。
_SEGMENT = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"

#: 设计 §5.3 的命名模式。
#:
#: ⚠️ **段数存在设计矛盾，此处暂按"3 或 4 段"放行**（发现问题时的实测记录）：
#:
#: * §5.3 写出的格式是 ``<domain>.<system>.<entity>.<action>``，即 **4 段**；
#: * 但同一节给出的三个样例 ``crm.customer.query`` / ``aftersale.ticket.create`` /
#:   ``erp.inventory.adjust`` **全部是 3 段**。
#:
#: 两者不可能同时成立。断言**不能替设计做决定**，因此这里暂时两者都接受。
#: 一旦设计澄清（见任务 G3 的命名规范化），必须把此处收窄到唯一段数。
TOOL_CODE_PATTERN = re.compile(rf"^{_SEGMENT}(?:\.{_SEGMENT}){{2,3}}$")

#: 设计 §5.3 给出的合法样例（实测均为 3 段）。
VALID_EXAMPLES = ("crm.customer.query", "aftersale.ticket.create", "erp.inventory.adjust")

#: 另一类合法形态：按 §5.3 的格式字面（4 段）构造。
VALID_EXAMPLES_FOUR_SEGMENT = ("crm.customer.profile.query",)

#: 畸形样例：每一类都对应一种真实会犯的错。
INVALID_EXAMPLES = (
    "crm.customer",  # 段数不足
    "crm",  # 只有一段
    "Crm.customer.query",  # 段首大写
    "crm..query",  # 空段
    "crm.customer.query_",  # 段尾下划线
    "crm-customer-query-id",  # 用连字符而非点
    "2crm.customer.query",  # 段首数字
    "",  # 空串
)

#: 需要扫描"已声明工具编码"的目录。G3 落地后应把 ``ingestion`` 也加进来。
SCAN_DIRS = ("builtin_tools",)


def _dotted_string_literals(path: Path) -> list[str]:
    """取出文件里形如点分标识符的字符串字面量（3 或 4 段，与暂定模式一致）。"""
    found: list[str] = []
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if 2 <= value.count(".") <= 3 and value.replace(".", "").isalnum():
                found.append(value)
    return found


def check_tool_naming_contract() -> list[str]:
    """第 1 部分：模式本身是否正确（合法样例通过、畸形样例被拒）。"""
    offenders: list[str] = []

    for example in (*VALID_EXAMPLES, *VALID_EXAMPLES_FOUR_SEGMENT):
        if not TOOL_CODE_PATTERN.match(example):
            offenders.append(f"合法样例被误判为非法：{example!r}")

    for example in INVALID_EXAMPLES:
        if TOOL_CODE_PATTERN.match(example):
            offenders.append(f"畸形样例被误判为合法：{example!r}")

    return format_violations(
        "工具命名模式与设计 §5.3 不一致（模式被改动过？）：",
        offenders,
    )


def check_declared_tool_codes() -> list[str]:
    """第 2 部分：实际声明的工具编码是否合规。"""
    offenders: list[str] = []
    scanned = 0

    for dirname in SCAN_DIRS:
        base = BACKEND_ROOT / "src" / "toolhive" / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            scanned += 1
            for code in _dotted_string_literals(path):
                if not TOOL_CODE_PATTERN.match(code):
                    offenders.append(f"{relative_display(path)} → {code!r}")

    return format_violations(
        f"工具编码不符合 <domain>.<system>.<entity>.<action>（已扫描 {scanned} 个文件，"
        f"设计 §5.3 / §14.1 第 4 条）：",
        offenders,
    )


ASSERTIONS: tuple[Assertion, ...] = (
    Assertion(
        name="tool_naming_contract",
        design_ref="设计 §5.3 / §14.1 第 4 条",
        run=check_tool_naming_contract,
    ),
    Assertion(
        name="declared_tool_codes_conform",
        design_ref="设计 §5.3 / §14.1 第 4 条",
        run=check_declared_tool_codes,
    ),
)
