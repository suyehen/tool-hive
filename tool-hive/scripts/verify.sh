#!/usr/bin/env bash
# ToolHive 一期自动化验收脚本（H11）：健康检查 + 初始化状态检查。
# 生产环境应通过 Nginx 入口访问；本地直连验收需在配置中开启开发直连并携带入口 Header。
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8100}"

echo "== 健康检查 =="
curl -fsS "$BASE_URL/health"
echo

echo "== 管理初始化状态 =="
curl -fsS \
    -H "X-ToolHive-Ingress: admin" \
    -H "X-ToolHive-Client-IP: 127.0.0.1" \
    "$BASE_URL/api/admin/bootstrap/status"
echo

echo "== 运行入口配置 =="
NGINX_CONF="${NGINX_CONF:-../deploy/nginx/toolhive.conf}"
if [ -f "$NGINX_CONF" ] && grep -q "X-ToolHive-Ingress runtime" "$NGINX_CONF"; then
    echo "运行入口配置存在（$NGINX_CONF）"
else
    echo "运行入口配置缺失或未包含 runtime ingress（$NGINX_CONF）" >&2
    exit 1
fi

echo "验收通过：服务可访问，初始化状态接口正常，运行入口配置就绪。"
