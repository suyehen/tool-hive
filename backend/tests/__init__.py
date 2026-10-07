"""测试包。

**M0 不建测试套件**（设计 §14.3）——没有 pytest、没有 testcontainers、没有 CI 流水线。
``tests/`` 承载架构断言（``tests/architecture/``）；本地运行时回归位于 scripts/regression.py。

断言不依赖 pytest：每个模块导出 ``ASSERTIONS``，由 ``scripts/verify.py`` 直接执行。
这样"跑一次架构体检"不需要任何测试框架。
"""
