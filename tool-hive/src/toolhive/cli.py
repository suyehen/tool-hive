"""ToolHive 命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import sys

from toolhive.config import load_settings
from toolhive.infrastructure.vector_index import EmbeddedChromaVectorIndex


async def _rebuild_chroma() -> int:
    """以 PostgreSQL 为来源全量重建 Chroma 索引。"""
    from toolhive.config import settings
    index = EmbeddedChromaVectorIndex(settings.chroma)
    await index.rebuild()
    return 0


def main(argv: list[str] | None = None) -> int:
    """ToolHive 管理命令入口。"""
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
    args = parser.parse_args(argv)

    load_settings(args.config)

    if args.command == "rebuild-chroma":
        return asyncio.run(_rebuild_chroma())
    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
