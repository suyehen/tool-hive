"""C 的本地契约检查；不读取环境配置，不连接外部服务。"""

from __future__ import annotations

import importlib.util
import io
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from sqlalchemy import create_mock_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from toolhive.adapters.db.base import Base
from toolhive.core.domain.contracts import BindingDefinition, ToolDefinition
from toolhive.core.domain.errors import InvalidDefinitionError
from toolhive.core.domain.grants import matches_scope, scope_predicate
from toolhive.core.domain.identity import IssuedApiKey
from toolhive.core.domain.models import Grant, Tool, ToolVersion

ROOT = Path(__file__).resolve().parents[1]


def initial_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "initial_migration",
        ROOT / "alembic/versions/0001_initial.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rejects(fn: Callable[[], object]) -> None:
    try:
        fn()
    except InvalidDefinitionError:
        return
    raise AssertionError("expected InvalidDefinitionError")


def check_schema() -> None:
    migration = initial_migration()
    assert len(Base.metadata.tables) == 16
    assert migration.revision == "0001_initial" and migration.down_revision is None
    dialect = create_mock_engine("postgresql://", lambda *args, **kwargs: None).dialect
    for table in Base.metadata.sorted_tables:
        assert f"CREATE TABLE {table.name} (" in migration._SQL
        assert table.c.id.autoincrement is False and table.c.id.server_default is None
        assert {
            "create_by_id",
            "create_by_name",
            "create_time",
            "update_by_id",
            "update_by_name",
            "update_time",
        } <= set(table.c.keys())
        assert all(not table.c[name].foreign_keys for name in ("create_by_id", "update_by_id"))
        assert str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            assert index.name in migration._SQL
            assert str(CreateIndex(index).compile(dialect=dialect))
    assert "halfvec(2560)" in migration._SQL
    assert "halfvec_cosine_ops" in migration._SQL


def check_semantics() -> None:
    read = ToolDefinition(name="Search", input_schema={}, side_effect="read", retry_safe=True)
    read.validate()
    assert read.executable
    assert not ToolDefinition(name="Unknown", input_schema={}).executable
    assert not ToolDefinition(name="Write", input_schema={}, side_effect="write").executable
    assert not ToolDefinition(
        name="Risky", input_schema={}, side_effect="read", risk="high"
    ).executable
    rejects(lambda: ToolDefinition(name="Unknown", input_schema={}, retry_safe=True).validate())
    rejects(lambda: ToolDefinition(name="Bad", input_schema={"type": "bad"}).validate())
    BindingDefinition(
        provider_id=1, method="POST", path_template="/search", param_mapping={}
    ).validate("http")
    BindingDefinition(provider_id=1, method="COMPUTE").validate("local")
    rejects(
        lambda: BindingDefinition(
            provider_id=1, method="GET", path_template="//other", param_mapping={}
        ).validate("http")
    )
    rejects(
        lambda: BindingDefinition(provider_id=1, method="COMPUTE", param_mapping={}).validate(
            "local"
        )
    )


def check_scopes() -> None:
    tool = Tool(
        id=11, code="demo.crm.customer.query", domain="demo", system="crm", tags=["entity:customer"]
    )
    version = ToolVersion(id=12, tool_id=11, domain="different", system="crm", tags=[])
    domain = Grant(scope_type="domain", scope_value="demo", status="active")
    assert matches_scope(domain, tool) and not matches_scope(domain, version)
    system = Grant(scope_type="system", scope_value="demo.crm", status="active")
    assert matches_scope(system, tool) and not matches_scope(system, version)
    assert "tool.domain" in str(scope_predicate(system))
    tag = Grant(scope_type="tag", scope_value="entity:customer", status="active")
    assert matches_scope(tag, tool) and not matches_scope(tag, version)
    fixed = Grant(scope_type="tool", scope_value="11", status="active")
    tool.code = "demo.crm.customer.renamed"
    assert matches_scope(fixed, tool) and matches_scope(fixed, version)
    assert "tool.id" in str(scope_predicate(fixed))
    fixed.status = "disabled"
    assert not matches_scope(fixed, tool)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    checks: tuple[Callable[[], None], ...] = (check_schema, check_semantics, check_scopes)
    for check in checks:
        check()
        print(f"[PASS] {check.__name__}")
    assert "secret" not in repr(IssuedApiKey(1, "prefix", "secret"))
    print(f"{len(checks)}/{len(checks)} domain groups passed (offline)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
