"""补齐历史库缺失的外键约束。

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-06
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_FKS = [
    (
        "fk_management_account_auth_state_account",
        "management_account_auth_state",
        "management_account",
        ["account_id"],
        ["id"],
    ),
    (
        "fk_management_account_role_account",
        "management_account_role",
        "management_account",
        ["account_id"],
        ["id"],
    ),
    (
        "fk_management_account_role_role",
        "management_account_role",
        "management_role",
        ["role_id"],
        ["id"],
    ),
    (
        "fk_management_account_password_history_account",
        "management_account_password_history",
        "management_account",
        ["account_id"],
        ["id"],
    ),
    (
        "fk_management_role_operation_role",
        "management_role_operation",
        "management_role",
        ["role_id"],
        ["id"],
    ),
    (
        "fk_management_role_operation_operation",
        "management_role_operation",
        "management_operation",
        ["operation_code"],
        ["operation_code"],
    ),
    (
        "fk_caller_runtime_policy_system",
        "caller_runtime_policy",
        "caller_system",
        ["system_id"],
        ["system_id"],
    ),
    (
        "fk_caller_tool_scope_system",
        "caller_tool_scope",
        "caller_system",
        ["system_id"],
        ["system_id"],
    ),
    (
        "fk_caller_public_key_system",
        "caller_public_key",
        "caller_system",
        ["system_id"],
        ["system_id"],
    ),
    (
        "fk_caller_ip_rule_system",
        "caller_ip_rule",
        "caller_system",
        ["system_id"],
        ["system_id"],
    ),
]


def _add_constraint_sql(
    name: str,
    table: str,
    parent: str,
    columns: list[str],
    parent_columns: list[str],
) -> str:
    """生成幂等补加外键的 DO 块 SQL。"""
    column_list = ", ".join(columns)
    parent_column_list = ", ".join(parent_columns)
    return f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = '{name}'
    ) THEN
        ALTER TABLE {table}
            ADD CONSTRAINT {name}
            FOREIGN KEY ({column_list})
            REFERENCES {parent}({parent_column_list}) ON DELETE CASCADE;
    END IF;
END $$;
"""


def _drop_constraint_sql(name: str, table: str) -> str:
    """生成幂等删除外键的 DO 块 SQL。"""
    return f"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = '{name}'
    ) THEN
        ALTER TABLE {table} DROP CONSTRAINT {name};
    END IF;
END $$;
"""


def upgrade() -> None:
    """为旧库补加与 ORM 一致的外键，已存在的约束自动跳过。"""
    for name, table, parent, columns, parent_columns in _FKS:
        op.execute(
            _add_constraint_sql(name, table, parent, columns, parent_columns)
        )


def downgrade() -> None:
    """回滚时移除本迁移新增的外键约束。"""
    for name, table, _parent, _columns, _parent_columns in _FKS:
        op.execute(_drop_constraint_sql(name, table))
