#!/usr/bin/env bash
# ToolHive 一期安装脚本（H11）：创建 CPython 3.11.6 虚拟环境并安装依赖。
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
echo "使用 Python: $($PYTHON_BIN --version)"

if [ ! -d .venv ]; then
    "$PYTHON_BIN" -m venv .venv
fi

./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -e ".[dev]"

./.venv/bin/python -c "import toolhive, captcha, PIL, chromadb; print('依赖安装完成，toolhive 可导入')"
