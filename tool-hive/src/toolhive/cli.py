"""ToolHive 命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import os
import secrets
import sys
import time

from toolhive.config import load_settings


async def _rebuild_chroma() -> int:
    """以 PostgreSQL 为来源全量重建 Chroma 索引。"""
    from toolhive.config import settings
    from toolhive.infrastructure import database as database
    from toolhive.runtime.retrieval.service import RetrievalService

    database.init_infrastructure(settings.infrastructure, debug=settings.debug)
    try:
        async with database.async_session_factory() as session:
            count = await RetrievalService(session).rebuild_index()
    except Exception as exc:
        print(f"Chroma 索引重建失败: {exc}", file=sys.stderr)
        return 1
    print(f"Chroma 索引重建完成，共 {count} 条")
    return 0


async def _seed_tools() -> int:
    """接入首批数学计算工具（幂等：已存在已发布版本则跳过）。"""
    from sqlalchemy import select

    from toolhive.config import settings
    from toolhive.core.enums import RiskLevel, ToolVersionStatus
    from toolhive.core.exceptions import ToolHiveError
    from toolhive.infrastructure import database as database
    from toolhive.models.catalog_provider import CatalogProvider
    from toolhive.services.catalog_tool_service import CatalogToolService
    from toolhive.services.catalog_version_service import CatalogVersionService

    database.init_infrastructure(settings.infrastructure, debug=settings.debug)
    async with database.async_session_factory() as session:
        provider = await session.scalar(
            select(CatalogProvider).where(
                CatalogProvider.provider_code == "builtin-math"
            )
        )
        if provider is None:
            print(
                "未找到 builtin-math Provider，请先执行 sql/init.sql 建表与种子数据",
                file=sys.stderr,
            )
            return 1
        tool_svc = CatalogToolService(session)
        version_svc = CatalogVersionService(session)
        input_schema = {
            "type": "object",
            "required": ["a", "b", "operation"],
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
                "operation": {
                    "type": "string",
                    "enum": [
                        "add", "subtract", "multiply",
                        "divide", "power", "modulo",
                    ],
                },
            },
            "additionalProperties": False,
        }
        output_schema = {
            "type": "object",
            "required": ["result"],
            "properties": {"result": {"type": "number"}},
        }
        try:
            tool = await tool_svc.get_by_full_code("math.basic.calculator")
            if tool is None:
                tool = await tool_svc.create_tool(
                    namespace="math.basic",
                    tool_code="calculator",
                    name="数学计算器",
                    description="常规数学计算：加/减/乘/除/幂/取模",
                    risk_level=RiskLevel.LOW,
                    discoverable=True,
                    executable=True,
                    input_schema=input_schema,
                    output_schema=output_schema,
                )
            versions = await version_svc.list_versions(tool.id)
            version = next(
                (v for v in versions if v.version == "1.0.0"), None,
            )
            if version is None:
                version = await version_svc.create_version(
                    tool.id,
                    "1.0.0",
                    input_schema=input_schema,
                    output_schema=output_schema,
                    release_note="首批数学计算占位工具",
                    binding={
                        "provider_id": provider.id,
                        "method": "COMPUTE",
                        "path_template": "builtin://math/calculate",
                        "parameter_mapping": {
                            "a": "$.a",
                            "b": "$.b",
                            "operator": "$.operation",
                        },
                        "timeout_seconds": 5,
                        "retry_max": 1,
                        "idempotent": True,
                    },
                )
            if version.status in (
                ToolVersionStatus.DRAFT,
                ToolVersionStatus.REJECTED,
            ):
                await version_svc.submit_review(version.id, "提交首批工具")
            if version.status == ToolVersionStatus.PENDING_REVIEW:
                await version_svc.approve(version.id, "内置低风险工具，审核通过")
            if version.status == ToolVersionStatus.APPROVED:
                await version_svc.publish(
                    version.id, set_default=True, comment="发布首批工具",
                )
        except ToolHiveError as exc:
            print(f"首批工具接入失败: {exc}", file=sys.stderr)
            return 1
        print("首批数学计算工具接入完成: math.basic.calculator (1.0.0)")
        return 0


def _sign_request(args) -> int:
    """生成签名请求 curl 命令（不自动发起请求）。"""
    from toolhive.runtime.authentication.service import (
        build_canonical,
        normalize_query,
    )

    timestamp = args.timestamp or str(int(time.time()))
    nonce = args.nonce or secrets.token_hex(16)
    body_bytes = args.body.encode("utf-8") if args.body else b""
    canonical = build_canonical(
        method=args.method,
        path=args.path,
        query_string=args.query,
        timestamp=timestamp,
        nonce=nonce,
        body=body_bytes,
    )
    try:
        with open(args.private_key, "rb") as f:
            private_key = _load_private_key(f.read())
        signature = _sign_bytes(private_key, canonical)
    except Exception as exc:
        print(f"签名失败: {exc}", file=sys.stderr)
        return 1
    signature_b64 = base64.b64encode(signature).decode("ascii")
    url = f"{args.base_url.rstrip('/')}{args.path}"
    # 将规范化后的查询串写入输出 URL，与服务端验签内容保持一致
    query_string = normalize_query(args.query)
    if query_string:
        url = f"{url}?{query_string}"
    lines = [
        f'curl -X {args.method} "{url}"',
        f'  -H "X-ToolHive-System-Id: {args.system_id}"',
        f'  -H "X-ToolHive-Key-Id: {args.key_id}"',
        f'  -H "X-ToolHive-Timestamp: {timestamp}"',
        f'  -H "X-ToolHive-Nonce: {nonce}"',
        f'  -H "X-ToolHive-Signature: {signature_b64}"',
        '  -H "Content-Type: application/json"',
    ]
    if args.body:
        lines.append(f"  -d '{args.body}'")
    print(" \\\n".join(lines))
    return 0


def _load_private_key(pem_bytes: bytes):
    """加载 PEM 私钥（PKCS8/PKCS1）。"""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    return load_pem_private_key(pem_bytes, password=None)


def _sign_bytes(private_key, canonical: bytes) -> bytes:
    """按私钥类型签名：RSA-PSS-SHA256（salt=32）或 Ed25519。"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

    if isinstance(private_key, rsa.RSAPrivateKey):
        return private_key.sign(
            canonical,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=32,
            ),
            hashes.SHA256(),
        )
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        return private_key.sign(canonical)
    raise ValueError("不支持的私钥类型（仅支持 RSA-PSS-SHA256 或 Ed25519）")


async def _init_admin(account: str, real_name: str) -> int:
    """初始化首个超级管理员（仅当无任何管理账号时可用）。"""
    from toolhive.config import settings
    from toolhive.core.exceptions import ToolHiveError

    # 通过模块对象访问会话工厂，确保拿到 init_infrastructure 初始化后的最新值
    from toolhive.infrastructure import database as database
    from toolhive.services.account_service import AccountService

    # 密码来源：优先环境变量 TOOLHIVE_INIT_ADMIN_PASSWORD，否则交互式输入两次
    password = os.environ.get("TOOLHIVE_INIT_ADMIN_PASSWORD", "").strip()
    if password:
        print("已从环境变量 TOOLHIVE_INIT_ADMIN_PASSWORD 读取初始密码")
    else:
        p1 = getpass.getpass("请输入初始密码（不显示输入内容）: ")
        p2 = getpass.getpass("请再次输入初始密码: ")
        if p1 != p2:
            print("两次输入的密码不一致，初始化失败", file=sys.stderr)
            return 1
        password = p1
    if not password:
        print("初始密码不能为空，初始化失败", file=sys.stderr)
        return 1

    database.init_infrastructure(settings.infrastructure, debug=settings.debug)
    async with database.async_session_factory() as session:
        svc = AccountService(session, settings.admin_security)
        try:
            await svc.init_super_admin(
                account=account, real_name=real_name, password=password,
            )
        except ToolHiveError as exc:
            print(f"初始化失败: {exc}", file=sys.stderr)
            return 1

    print("超级管理员初始化成功")
    return 0


def _reconfigure_console_encoding() -> None:
    """Windows 控制台代码页可能不支持中文，统一以 UTF-8 输出避免 UnicodeEncodeError。"""
    # 对标准输出与错误输出分别重配置编码，兼容不支持 reconfigure 的流
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    """ToolHive 管理命令入口。"""
    # 入口处先修正控制台编码，避免中文提示在 cp936/cp950 等代码页下抛 UnicodeEncodeError
    _reconfigure_console_encoding()
    parser = argparse.ArgumentParser(
        prog="toolhive", description="ToolHive 管理命令",
    )
    parser.add_argument(
        "--config", default=None, help="外挂配置文件路径",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "rebuild-chroma",
        help="以 PostgreSQL 为来源全量重建 Chroma 索引",
    )
    sub.add_parser(
        "seed-tools",
        help="接入首批数学计算工具（幂等）",
    )
    sign_parser = sub.add_parser(
        "sign-request",
        help="生成运行 API 签名请求 curl 命令（不自动发起请求）",
    )
    sign_parser.add_argument("--method", default="POST", help="HTTP 方法")
    sign_parser.add_argument("--path", required=True, help="完整版本路径，如 /api/runtime/v1/ping")
    sign_parser.add_argument("--query", default="", help="查询串（可选）")
    sign_parser.add_argument("--body", default="", help="请求体 JSON（可选）")
    sign_parser.add_argument("--system-id", dest="system_id", required=True)
    sign_parser.add_argument("--key-id", dest="key_id", required=True)
    sign_parser.add_argument(
        "--private-key", dest="private_key", required=True,
        help="私钥 PEM 文件路径",
    )
    sign_parser.add_argument(
        "--base-url", dest="base_url",
        default="http://127.0.0.1:8081", help="运行入口地址",
    )
    sign_parser.add_argument("--timestamp", default=None, help="固定时间戳（可选，默认当前时间）")
    sign_parser.add_argument("--nonce", default=None, help="固定 Nonce（可选，默认随机生成）")
    init_parser = sub.add_parser(
        "init-admin",
        help="初始化首个超级管理员（仅当无管理账号时可执行）",
        description=(
            "仅当管理账号表为空时创建首个超级管理员，并自动授予超管角色。\n"
            "密码来源：优先读取环境变量 TOOLHIVE_INIT_ADMIN_PASSWORD；"
            "未设置该环境变量时交互式输入两次（不显示输入内容）。\n"
            "已存在管理账号时拒绝执行并返回非零退出码，不覆盖任何数据。"
        ),
    )
    init_parser.add_argument(
        "--account",
        required=True,
        help="首个超级管理员账号（必填）",
    )
    init_parser.add_argument(
        "--real-name",
        dest="real_name",
        required=True,
        help="首个超级管理员姓名（必填）",
    )
    args = parser.parse_args(argv)

    load_settings(args.config)

    if args.command == "rebuild-chroma":
        return asyncio.run(_rebuild_chroma())
    if args.command == "seed-tools":
        return asyncio.run(_seed_tools())
    if args.command == "sign-request":
        return _sign_request(args)
    if args.command == "init-admin":
        return asyncio.run(_init_admin(args.account, args.real_name))
    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
