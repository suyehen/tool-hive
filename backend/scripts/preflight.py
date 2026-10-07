"""ToolHive M0 部署自检。

用法（必须使用 conda 环境的解释器，在 backend/ 目录下执行）：
    set TOOLHIVE_DATABASE_URL=postgresql://postgres:<PW>@127.0.0.1:5432/toolhive
    set TOOLHIVE_REDIS_URL=redis://:<PW>@132.232.176.80:6379/1
    set TOOLHIVE_EMBEDDING_API_KEY=<KEY>
    F:\\soft\\anaconda\\envs\\toolhive\\python.exe scripts\\preflight.py

退出码：0 = 无阻塞项；1 = 存在阻塞项。
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import sys
from collections.abc import Mapping

import asyncpg
import httpx
import redis.asyncio as aioredis

# Windows 控制台默认编码可能是 cp950 / cp936，本脚本输出全为中文，
# 不重设编码会直接抛 UnicodeEncodeError 而掩盖真正的检查结果。
# 放在 import 之后、任何输出之前 —— 这样不必用 noqa 绕过 E402。
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

EXPECTED_EMBEDDING_DIM = 2560
EXPECTED_TABLE_COUNT = 16

#: 这些表不是业务表，计数时必须排除，否则总数会多出来。
#: alembic 在执行 upgrade 时会自建 alembic_version。
NON_BUSINESS_TABLES = ("alembic_version",)

BLOCKING: list[str] = []
WARNING: list[str] = []


def is_single_active_index(row: Mapping[str, object] | None) -> bool:
    """检查指定索引的键、唯一性、有效性与谓词，不接受任意 UNIQUE。"""
    if row is None:
        return False
    predicate = re.sub(r"::(?:text|character varying)", "", str(row.get("predicate", "")))
    predicate = re.sub(r"[()\s]", "", predicate)
    return (
        bool(row.get("indisunique"))
        and bool(row.get("indisvalid"))
        and row.get("columns") == ["status"]
        and predicate == "status='active'"
    )


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")
    WARNING.append(msg)


def bad(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    BLOCKING.append(msg)


async def check_postgres() -> None:
    print("\n== PostgreSQL ==")
    dsn = os.environ.get("TOOLHIVE_DATABASE_URL")
    if not dsn:
        bad("未设置 TOOLHIVE_DATABASE_URL")
        return

    try:
        conn = await asyncpg.connect(dsn, timeout=10)
    except Exception as exc:
        bad(f"连接失败：{type(exc).__name__}: {exc}")
        print(
            "       ConnectionRefusedError = 隧道进程没了；"
            "TimeoutError = 隧道活着但转发失效。两者都要重启隧道（步骤 1）"
        )
        return

    try:
        version = str(await conn.fetchval("SELECT version()"))
        ok(f"连接成功：{version[:100]}")

        # 服务器是否提供所需扩展
        for name in ("vector", "pg_trgm"):
            row = await conn.fetchrow(
                "SELECT default_version FROM pg_available_extensions WHERE name = $1", name
            )
            if row:
                ok(f"服务器提供扩展 {name} (default {row['default_version']})")
            else:
                bad(f"服务器缺少扩展 {name} —— 见步骤 2（装 postgresql-contrib）")

        # 当前库是否已装
        installed = {r["extname"] for r in await conn.fetch("SELECT extname FROM pg_extension")}
        for name in ("vector", "pg_trgm"):
            if name in installed:
                ok(f"库内已安装 {name}")
            else:
                bad(f"库内未安装 {name} —— 执行 CREATE EXTENSION {name};（步骤 3）")

        # 表数量（排除 alembic 自建的 alembic_version 等非业务表）
        n = await conn.fetchval(
            "SELECT count(*) FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> ALL($1::text[])",
            list(NON_BUSINESS_TABLES),
        )
        if n == EXPECTED_TABLE_COUNT:
            ok(f"业务表数量 = {n}")
        else:
            bad(
                f"业务表数量 = {n}，期望 {EXPECTED_TABLE_COUNT} —— "
                "执行 `alembic upgrade head`（迁移由任务 C1 交付，见步骤 3）"
            )

        # halfvec 与余弦距离
        if "vector" in installed:
            try:
                d = float(
                    await conn.fetchval("SELECT '[1,0,0]'::halfvec(3) <=> '[0,1,0]'::halfvec(3)")
                )
                if abs(d - 1.0) < 1e-3:
                    ok(f"halfvec 余弦距离可用（正交向量 = {d:.3f}）")
                else:
                    warn(f"halfvec 距离异常：期望 1.000，实得 {d}")
            except Exception as exc:
                bad(f"halfvec 不可用：{exc}")

        # index_meta 单活唯一约束
        if n == EXPECTED_TABLE_COUNT:
            row = await conn.fetchrow(
                "SELECT i.indisunique, i.indisvalid, "
                "pg_get_expr(i.indpred, i.indrelid) AS predicate, "
                "ARRAY(SELECT a.attname::text FROM unnest(i.indkey) WITH ORDINALITY k(num, ord) "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.num "
                "WHERE k.ord <= i.indnkeyatts ORDER BY k.ord) AS columns "
                "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_class t ON t.oid = i.indrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = 'public' AND t.relname = 'index_meta' "
                "AND c.relname = 'uq_index_meta_single_active'"
            )
            if is_single_active_index(row):
                ok("index_meta 单活唯一约束存在且有效（uq_index_meta_single_active）")
            else:
                bad("index_meta 缺少 UNIQUE 约束 —— DDL 未正确执行")

        # 参数体检
        settings = {
            r["name"]: r["setting"]
            for r in await conn.fetch(
                "SELECT name, setting FROM pg_settings WHERE name IN "
                "('statement_timeout','idle_in_transaction_session_timeout')"
            )
        }
        if settings.get("statement_timeout") == "0":
            warn("statement_timeout = 0，建议按步骤 4 设为 5s")
        else:
            ok(f"statement_timeout = {settings.get('statement_timeout')}")
        if settings.get("idle_in_transaction_session_timeout") == "0":
            warn("idle_in_transaction_session_timeout = 0，建议按步骤 4 设为 30s")

        # 连接角色
        is_super = await conn.fetchval(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        who = await conn.fetchval("SELECT current_user")
        if is_super:
            warn(f"当前以超级用户 {who} 连接，正式环境建议改用专用角色（§8）")
        else:
            ok(f"连接角色 {who} 非超级用户")
    finally:
        await conn.close()


async def check_redis() -> None:
    print("\n== Redis ==")
    url = os.environ.get("TOOLHIVE_REDIS_URL")
    if not url:
        bad("未设置 TOOLHIVE_REDIS_URL")
        return

    client = aioredis.from_url(url, socket_connect_timeout=10, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        bad(f"连接失败：{type(exc).__name__}: {exc}")
        await client.aclose()
        return

    try:
        ok(f"连接成功：{url.rsplit('@', 1)[-1]}")

        db = await client.dbsize()
        if db == 0:
            ok("目标 DB 为空，未被其它应用占用")
        else:
            bad(f"目标 DB 已有 {db} 个键 —— 可能被别的应用占用，换一个 DB 编号（步骤 5）")

        cfg = await client.config_get("maxmemory", "maxmemory-policy")
        if cfg.get("maxmemory") in (None, "0"):
            warn("maxmemory = 0（不限制），建议按步骤 5 设置上限")
        else:
            ok(f"maxmemory = {cfg['maxmemory']}，policy = {cfg.get('maxmemory-policy')}")
    finally:
        await client.aclose()


async def check_embedding() -> None:
    print("\n== Embedding 服务 ==")
    key = os.environ.get("TOOLHIVE_EMBEDDING_API_KEY")
    base = os.environ.get("TOOLHIVE_EMBEDDING_BASE_URL", "https://tokenhub.tencentmaas.com").rstrip("/")
    model = os.environ.get("TOOLHIVE_EMBEDDING_MODEL", "kinfra-text-embedding-4b")

    if not key:
        warn("未设置 TOOLHIVE_EMBEDDING_API_KEY，跳过（这是必需项，见 §1.4）")
        return

    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                f"{base}/v1/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "input": "ping"},
            )
        if r.status_code != 200:
            bad(f"HTTP {r.status_code}：{r.text[:200]}")
            return
        dim = len(r.json()["data"][0]["embedding"])
        if dim == EXPECTED_EMBEDDING_DIM:
            ok(f"{model} 返回 {dim} 维，与 DDL 的 halfvec({EXPECTED_EMBEDDING_DIM}) 一致")
        else:
            bad(f"维度 = {dim}，期望 {EXPECTED_EMBEDDING_DIM} —— DDL 必须同步修改！")
    except Exception as exc:
        bad(f"请求失败：{type(exc).__name__}: {exc}")


async def main() -> int:
    print("ToolHive M0 部署自检")
    print("=" * 60)
    await check_postgres()
    await check_redis()
    await check_embedding()

    print("\n" + "=" * 60)
    print(f"阻塞项 {len(BLOCKING)} 个 / 警告项 {len(WARNING)} 个")
    if BLOCKING:
        print("\n阻塞项（必须解决）：")
        for m in BLOCKING:
            print(f"  - {m}")
    if WARNING:
        print("\n警告项（建议处理，不阻塞）：")
        for m in WARNING:
            print(f"  - {m}")
    if not BLOCKING:
        print("\n✅ 无阻塞项，环境已就绪。")
    return 1 if BLOCKING else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
