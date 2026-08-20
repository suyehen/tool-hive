"""数据库迁移执行服务（H11）。

轻量 SQL 迁移：按文件名顺序执行 ``sql/migrations/`` 下未应用的 ``*.sql``，
并通过 ``schema_migrations`` 表记录已应用的文件，保证可重复执行。
"""

from __future__ import annotations

from pathlib import Path

import asyncpg

_CREATE_SCHEMA_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def run_migrations(
    database_url: str, migrations_dir: Path,
) -> list[str]:
    """执行未应用的迁移，返回本次实际执行的文件名列表。"""
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(_CREATE_SCHEMA_MIGRATIONS)
        applied = {
            row["filename"]
            for row in await conn.fetch(
                "SELECT filename FROM schema_migrations",
            )
        }
        executed: list[str] = []
        for path in sorted(migrations_dir.glob("*.sql")):
            if path.name in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES ($1)",
                path.name,
            )
            executed.append(path.name)
        return executed
    finally:
        await conn.close()
