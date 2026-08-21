#!/usr/bin/env bash
# ToolHive 一期启动脚本（H11）：单 Uvicorn Worker，仅监听回环地址。
# 生产通过 Nginx 转发；启动前请先执行 install.sh、数据库初始化和 db-migrate。
set -euo pipefail

cd "$(dirname "$0")/.."

export TOOLHIVE_CONFIG_FILE="${TOOLHIVE_CONFIG_FILE:-/vdb/tool-hive/config/production.yaml}"

if [ ! -f "$TOOLHIVE_CONFIG_FILE" ]; then
    echo "配置文件不存在: $TOOLHIVE_CONFIG_FILE（启动失败）" >&2
    exit 1
fi

exec ./.venv/bin/uvicorn toolhive.main:app \
    --host 127.0.0.1 \
    --port 8100 \
    --workers 1
