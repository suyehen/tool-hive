"""架构断言集合（任务 A6）。

设计 §14.1 列出的**全部约束逐条**实现，外加一条由本次实现新增的
「明确不引入的依赖」检查（见 ``test_excluded_dependencies`` 的模块文档）。

:data:`ASSERTIONS` 汇总全部断言，供 ``scripts/verify.py`` 按固定顺序执行。
"""

from __future__ import annotations

from importlib import import_module

from tests.architecture._harness import Assertion, iter_assertion_modules

ASSERTIONS: tuple[Assertion, ...] = tuple(
    assertion
    for module_name in iter_assertion_modules()
    for assertion in import_module(f"tests.architecture.{module_name}").ASSERTIONS
)

__all__ = ["ASSERTIONS"]
