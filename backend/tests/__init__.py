"""测试包。

**M0 不建测试套件**（设计 §14.3）——没有 pytest、没有 testcontainers、没有 CI 流水线。
``tests/`` 只承载**唯一保留的自动化验证：架构断言**（``tests/architecture/``）。

断言不依赖 pytest：每个模块导出 ``ASSERTIONS``，由 ``scripts/verify.py`` 直接执行。
这样"跑一次架构体检"不需要任何测试框架。
"""
