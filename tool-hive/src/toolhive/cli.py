"""ToolHive 命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from toolhive.config import load_settings
from toolhive.infrastructure.vector_index import EmbeddedChromaVectorIndex


async def _rebuild_chroma() -> int:
    """以 PostgreSQL 为来源全量重建 Chroma 索引。"""
    from toolhive.config import settings
    index = EmbeddedChromaVectorIndex(settings.chroma)
    await index.rebuild()
    return 0


async def _init_admin(username: str) -> int:
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
            await svc.init_super_admin(username=username, password=password)
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
        "--username",
        required=True,
        help="首个超级管理员用户名（必填）",
    )
    args = parser.parse_args(argv)

    load_settings(args.config)

    if args.command == "rebuild-chroma":
        return asyncio.run(_rebuild_chroma())
    if args.command == "init-admin":
        return asyncio.run(_init_admin(args.username))
    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
