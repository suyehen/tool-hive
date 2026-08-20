"""数据库迁移执行服务测试（H11）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from toolhive.services.db_migration import run_migrations


def _write_migration(tmp_path, name: str, sql: str) -> None:
    (tmp_path / name).write_text(sql, encoding="utf-8")


async def test_run_migrations_applies_new_files_in_order(tmp_path) -> None:
    """未应用的迁移按文件名顺序执行并记录。"""
    _write_migration(tmp_path, "001_first.sql", "CREATE TABLE IF NOT EXISTS a (id int);")
    _write_migration(tmp_path, "002_second.sql", "CREATE TABLE IF NOT EXISTS b (id int);")

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.close = AsyncMock()

    with patch("toolhive.services.db_migration.asyncpg.connect", return_value=conn):
        executed = await run_migrations("postgresql://db", tmp_path)

    assert executed == ["001_first.sql", "002_second.sql"]
    # CREATE TABLE schema_migrations + 2 次执行 + 2 次 INSERT
    assert conn.execute.await_count == 5
    conn.close.assert_awaited_once()


async def test_run_migrations_skips_applied_files(tmp_path) -> None:
    """已应用的迁移被跳过。"""
    _write_migration(tmp_path, "001_done.sql", "SELECT 1;")
    _write_migration(tmp_path, "002_pending.sql", "SELECT 1;")

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"filename": "001_done.sql"}])
    conn.close = AsyncMock()

    with patch("toolhive.services.db_migration.asyncpg.connect", return_value=conn):
        executed = await run_migrations("postgresql://db", tmp_path)

    assert executed == ["002_pending.sql"]
    assert conn.execute.await_count == 3  # CREATE + 执行 002 + INSERT 002
