"""初始基线：以 sql/init.sql 作为空库建表与种子数据来源。

Revision ID: 0001
Revises:
Create Date: 2026-09-06
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_ALL_TABLES = [
    "runtime_confirmation",
    "runtime_trace_log",
    "catalog_publish_history",
    "catalog_review_record",
    "catalog_execution_binding",
    "catalog_tool_version",
    "catalog_tool",
    "catalog_capability_pack_system",
    "catalog_capability_pack_tool",
    "catalog_capability_pack",
    "catalog_provider",
    "outbox_delivery",
    "outbox_event",
    "caller_ip_rule",
    "caller_public_key",
    "caller_tool_scope",
    "caller_runtime_policy",
    "caller_system",
    "management_account_password_history",
    "management_audit_log",
    "management_role_operation",
    "management_operation",
    "management_account_role",
    "management_role",
    "management_account_auth_state",
    "management_account",
]


def _init_sql_statements() -> list[str]:
    """读取 sql/init.sql 并按顶层分号切分为可独立执行的语句。"""
    sql_path = Path(__file__).resolve().parents[2] / "sql" / "init.sql"
    statements: list[str] = []
    buffer: list[str] = []
    in_dollar = False
    for raw_line in sql_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.upper() in ("BEGIN;", "COMMIT;"):
            continue
        if not line and not buffer:
            continue
        if "$$" in line:
            in_dollar = not in_dollar
        buffer.append(raw_line)
        if not in_dollar and line.endswith(";"):
            statements.append("\n".join(buffer))
            buffer = []
    if buffer:
        statements.append("\n".join(buffer))
    return statements


def upgrade() -> None:
    """在空库上执行当前基线 SQL。"""
    for statement in _init_sql_statements():
        op.execute(statement)


def downgrade() -> None:
    """回滚基线：删除本基线创建的全部业务表。"""
    op.execute(
        "DROP TABLE IF EXISTS "
        + ", ".join(f'"{table}"' for table in _ALL_TABLES)
        + " CASCADE"
    )
