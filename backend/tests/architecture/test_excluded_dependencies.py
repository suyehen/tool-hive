"""架构断言 6：明确不引入的外部依赖不得出现。

**这条不在设计 §14.1 的五条之内，是本次实现新增的**——但依据充分：
设计 §12「明确不引入的外部依赖」原文是

    以下组件已决定不接入，实现时不得引入；若将来确需，必须先走设计变更。

"必须先走设计变更"这句话如果没有机器检查，就只是一句愿望。所以这里把它做成断言。

检查两处，因为两处都可能漏：

* **源码 import** —— 已经用了。
* **``pyproject.toml`` 的 dependencies** —— 装了但还没用，同样属于"引入"。
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.architecture._harness import (
    BACKEND_ROOT,
    PACKAGE_ROOT,
    Assertion,
    format_violations,
    relative_display,
    top_level_import_roots,
)

#: 顶层包名 → 它代表什么、为什么被排除。键是 import 根名。
#: 依据：设计 §12 的「明确不引入的外部依赖」表 + §2 的 C5 教训 + §16.2。
EXCLUDED: dict[str, str] = {
    "opentelemetry": "设计 §12：不接 OpenTelemetry，用 trace_id + 结构化日志",
    "prometheus_client": "设计 §12：不接 Prometheus，关键计数写日志",
    "prometheus": "设计 §12：不接 Prometheus",
    "hvac": "设计 §12：不接 Vault，external_ref 仅作字段预留",
    "boto3": "设计 §12：KEK 由环境变量注入，不接 KMS",
    "botocore": "设计 §12：KEK 由环境变量注入，不接 KMS",
    "chromadb": "设计 §2 的 C5 教训：嵌入式向量库是上一版的硬伤，改用 pgvector",
}


def _iter_source_files() -> list[Path]:
    """``src/toolhive`` 下的全部 ``.py``（不限于某个子包）。"""
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def check_no_excluded_imports() -> list[str]:
    offenders: list[str] = []
    for path in _iter_source_files():
        hits = top_level_import_roots(path) & set(EXCLUDED)
        if hits:
            detail = "；".join(f"{name}（{EXCLUDED[name]}）" for name in sorted(hits))
            offenders.append(f"{relative_display(path)} → {detail}")

    return format_violations(
        "引用了设计明确排除的外部依赖（设计 §12）：",
        offenders,
    )


_DEP_LINE = re.compile(r'^\s*"([A-Za-z0-9_.\-]+)\s*(?:[<>=!~\[].*)?",\s*$', re.MULTILINE)


def check_no_excluded_dependencies() -> list[str]:
    """``pyproject.toml`` 的依赖列表里不得出现被排除的包。"""
    pyproject = BACKEND_ROOT / "pyproject.toml"
    if not pyproject.is_file():
        return []

    text = pyproject.read_text(encoding="utf-8")
    # 只取 [project] 段里的依赖字符串，避免误伤 [tool.*] 配置。
    project_section = text.split("[project]", 1)[-1].split("\n[", 1)[0]

    offenders: list[str] = []
    for match in _DEP_LINE.finditer(project_section):
        name = match.group(1).split("[")[0].strip()
        root = name.lower().replace("-", "_").split(".")[0]
        for excluded, reason in EXCLUDED.items():
            if root == excluded or root.startswith(f"{excluded}_"):
                offenders.append(f'pyproject.toml 依赖 "{name}" → {reason}')

    return format_violations(
        "pyproject.toml 声明了设计明确排除的依赖（设计 §12）：",
        offenders,
    )


ASSERTIONS: tuple[Assertion, ...] = (
    Assertion(
        name="no_excluded_imports",
        design_ref="设计 §12「明确不引入的外部依赖」",
        run=check_no_excluded_imports,
    ),
    Assertion(
        name="no_excluded_dependencies",
        design_ref="设计 §12「明确不引入的外部依赖」",
        run=check_no_excluded_dependencies,
    ),
)
