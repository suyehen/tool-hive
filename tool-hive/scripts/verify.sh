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

echo "== MCP 运行入口配置 =="
if [ -f "$NGINX_CONF" ] && grep -q "location /mcp/" "$NGINX_CONF"; then
    echo "MCP 入口配置存在（$NGINX_CONF）"
else
    echo "MCP 入口配置缺失或未包含 /mcp/ 转发（$NGINX_CONF）" >&2
    exit 1
fi

echo "验收通过：服务可访问，初始化状态接口正常，运行入口配置就绪。"

# ── 可选完整 E2E：TOOLHIVE_E2E=1 时执行签名→发现→解析→执行链路 ──
if [ "${TOOLHIVE_E2E:-0}" = "1" ]; then
    CLI="${TOOLHIVE_CLI:-./.venv/bin/toolhive}"
    RUNTIME_URL="${TOOLHIVE_RUNTIME_URL:-http://127.0.0.1:8081}"
    TOOL_CODE="${TOOLHIVE_TOOL_CODE:-math.basic.calculator}"

    for var in TOOLHIVE_SYSTEM_ID TOOLHIVE_KEY_ID TOOLHIVE_PRIVATE_KEY; do
        if [ -z "${!var:-}" ]; then
            echo "E2E 缺少必需环境变量: $var" >&2
            exit 1
        fi
    done
    if [ ! -f "$TOOLHIVE_PRIVATE_KEY" ]; then
        echo "E2E 私钥文件不存在: $TOOLHIVE_PRIVATE_KEY" >&2
        exit 1
    fi

    echo "== 运行入口 E2E（签名请求） =="

    run_signed() {
        local method="$1" path="$2" body="$3"
        eval "$("$CLI" sign-request \
            --method "$method" \
            --path "$path" \
            --body "$body" \
            --system-id "$TOOLHIVE_SYSTEM_ID" \
            --key-id "$TOOLHIVE_KEY_ID" \
            --private-key "$TOOLHIVE_PRIVATE_KEY" \
            --base-url "$RUNTIME_URL" 2>/dev/null)"
    }

    PING_RESPONSE="$(run_signed POST /api/runtime/v1/ping '{}')"
    case "$PING_RESPONSE" in
        *'"status":"ok"'*) ;;
        *) echo "E2E ping 失败: $PING_RESPONSE" >&2; exit 1 ;;
    esac

    DISCOVER_RESPONSE="$(run_signed POST /api/runtime/v1/tools/discover '{"query":"数学"}')"
    RESOLVE_RESPONSE="$(run_signed POST /api/runtime/v1/tools/resolve "{\"tool_code\":\"$TOOL_CODE\"}")"
    EXECUTE_RESPONSE="$(run_signed POST "/api/runtime/v1/tools/$TOOL_CODE/execute" '{"arguments":{"a":1,"b":2,"operation":"add"}}')"

    case "$RESOLVE_RESPONSE" in
        *"$TOOL_CODE"*) ;;
        *) echo "E2E resolve 未返回目标工具: $RESOLVE_RESPONSE" >&2; exit 1 ;;
    esac
    case "$EXECUTE_RESPONSE" in
        *'"result"'*) ;;
        *) echo "E2E execute 未返回结果: $EXECUTE_RESPONSE" >&2; exit 1 ;;
    esac

    echo "E2E 通过：签名认证、发现、解析、执行均成功。"

    # 可选 Trace 落库核验：提供 TOOLHIVE_DATABASE_URL 时校验 runtime_trace_log
    if [ -n "${TOOLHIVE_DATABASE_URL:-}" ]; then
        TRACE_ID="$(printf '%s' "$EXECUTE_RESPONSE" | python3 -c \
            'import json,sys; print(json.load(sys.stdin).get("trace_id",""))' 2>/dev/null)"
        if [ -z "$TRACE_ID" ]; then
            echo "E2E 无法从 execute 响应解析 trace_id" >&2
            exit 1
        fi
        TRACE_COUNT="$(psql "$TOOLHIVE_DATABASE_URL" -Atc \
            "SELECT count(*) FROM runtime_trace_log WHERE trace_id = '$TRACE_ID';" 2>/dev/null)"
        if [ "${TRACE_COUNT:-0}" -ge 1 ] 2>/dev/null; then
            echo "Trace 落库核验通过：trace_id=$TRACE_ID"
        else
            echo "E2E Trace 未在 runtime_trace_log 找到: trace_id=$TRACE_ID" >&2
            exit 1
        fi
    fi
fi

# ── 可选 MCP E2E：TOOLHIVE_MCP_E2E=1 时执行 initialize→tools/list→tools/call ──
if [ "${TOOLHIVE_MCP_E2E:-0}" = "1" ]; then
    MCP_PYTHON="${TOOLHIVE_MCP_PYTHON:-./.venv/bin/python}"
    MCP_URL="${TOOLHIVE_MCP_URL:-http://127.0.0.1:8082/mcp/}"
    MCP_TOKEN="${TOOLHIVE_MCP_TOKEN:-}"
    MCP_TOOL_CODE="${TOOLHIVE_MCP_TOOL_CODE:-math.basic.calculator}"
    MCP_TOOL_ARGS="${TOOLHIVE_MCP_TOOL_ARGS:-}"
    if [ -z "$MCP_TOKEN" ]; then
        echo "MCP E2E 缺少必需环境变量: TOOLHIVE_MCP_TOKEN" >&2
        exit 1
    fi
    echo "== MCP E2E（Bearer + Streamable HTTP） =="
    MCP_URL="$MCP_URL" MCP_TOKEN="$MCP_TOKEN" \
    MCP_TOOL_CODE="$MCP_TOOL_CODE" MCP_TOOL_ARGS="$MCP_TOOL_ARGS" \
    "$MCP_PYTHON" - <<'PY'
import asyncio
import json
import os

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    url = os.environ["MCP_URL"]
    token = os.environ["MCP_TOKEN"]
    tool_code = os.environ["MCP_TOOL_CODE"]
    raw_args = os.environ.get("MCP_TOOL_ARGS", "") or "{}"
    arguments = json.loads(raw_args)
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}
    ) as http_client:
        async with streamable_http_client(
            url, http_client=http_client,
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init = await session.initialize()
                print(f"MCP initialize ok: {init.server_info.name}")
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                print(f"MCP tools/list count={len(names)}")
                if tool_code not in names:
                    raise SystemExit(
                        f"MCP E2E 工具不可发现: {tool_code}"
                    )
                result = await session.call_tool(tool_code, arguments)
                text = " ".join(
                    part.text for part in result.content if hasattr(part, "text")
                )
                print(f"MCP tools/call is_error={result.is_error}")
                print(f"MCP tools/call text={text}")
                if result.is_error:
                    raise SystemExit("MCP E2E 工具调用返回错误")


asyncio.run(main())
PY
    echo "MCP E2E 通过：认证、发现、执行均成功。"
fi
