"""ORM 写入保护：服务是公开写入入口，事务内 flush 也保护冻结定义。"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import LoaderCallableStatus, ORMExecuteState, Session

from toolhive.adapters.db.base import Base
from toolhive.core.domain.contracts import BINDING_FIELDS, DEFINITION_FIELDS
from toolhive.core.domain.errors import ImmutableDefinitionError, InvalidTransitionError
from toolhive.core.domain.models import (
    AuditLog,
    ExecutionBinding,
    Invocation,
    Provider,
    ReviewRecord,
    SearchEvent,
    Tool,
    ToolChannel,
    ToolVersion,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_APPEND_ONLY = (AuditLog, Invocation, ReviewRecord, SearchEvent)
_GOVERNANCE = "toolhive.domain.governance"
_SNAPSHOT = "toolhive.domain.snapshot"
NO_VALUE = LoaderCallableStatus.NO_VALUE


def _snapshot_fields(entity: object) -> tuple[str, ...]:
    if isinstance(entity, (Tool, ToolVersion)):
        return DEFINITION_FIELDS
    if isinstance(entity, ExecutionBinding):
        return BINDING_FIELDS
    if isinstance(entity, Provider):
        return ("type", "base_url", "auth_ref", "tls_config", "limits", "status")
    return ()


def _remember(entity: Base) -> None:
    fields = _snapshot_fields(entity)
    state = inspect(entity)
    if fields and all(state.attrs[name].loaded_value is not NO_VALUE for name in fields):
        state.info[_SNAPSHOT] = {name: deepcopy(state.attrs[name].loaded_value) for name in fields}


@event.listens_for(Base, "load", propagate=True)
def remember_loaded(entity: Base, context: object) -> None:
    _remember(entity)


@event.listens_for(Base, "refresh", propagate=True)
def remember_refreshed(entity: Base, context: object, attrs: object) -> None:
    _remember(entity)


@event.listens_for(Session, "after_flush_postexec")
def remember_flushed(session: Session, context: object) -> None:
    for entity in session.identity_map.values():
        if isinstance(entity, Base):
            _remember(entity)


def _check_nested_changes(session: Session) -> None:
    for entity in session.identity_map.values():
        if not isinstance(entity, Base):
            continue
        state = inspect(entity)
        baseline: dict[str, Any] | None = state.info.get(_SNAPSHOT)
        if baseline is None or not any(
            state.attrs[name].loaded_value is not NO_VALUE
            and state.attrs[name].loaded_value != value
            for name, value in baseline.items()
        ):
            continue
        if isinstance(entity, ToolVersion):
            history = state.attrs.status.history
            original_status = history.deleted[0] if history.deleted else entity.status
            if original_status != "draft":
                raise ImmutableDefinitionError("送审后版本定义已冻结（含嵌套 JSON）")
        if isinstance(entity, Tool) and not session.info.get(_GOVERNANCE, False):
            raise ImmutableDefinitionError("生产投影只能随 stable 更新")
        if isinstance(entity, Provider) and not session.info.get(_GOVERNANCE, False):
            raise InvalidTransitionError("Provider 配置须通过领域服务治理")
        if isinstance(entity, ExecutionBinding):
            version = session.get(ToolVersion, entity.version_id)
            if version is None or version.status != "draft":
                raise ImmutableDefinitionError("送审后执行绑定已冻结（含嵌套 JSON）")


@event.listens_for(Session, "before_commit")
def protect_nested_commit(session: Session) -> None:
    # SQLAlchemy 的普通 JSON 不追踪嵌套修改；无 dirty 时 flush 事件不会触发。
    _check_nested_changes(session)


@event.listens_for(Session, "do_orm_execute")
def protect_bulk_writes(execution: ORMExecuteState) -> None:
    if not (execution.is_update or execution.is_delete):
        return
    table = getattr(execution.statement, "table", None)
    if table is not None and table.name == "provider":
        raise ImmutableDefinitionError("Provider 配置不允许批量改写")
    if table is not None and table.name in {
        "tool_version",
        "execution_binding",
        "tool_channel",
        "invocation",
        "audit_log",
        "review_record",
        "search_event",
    }:
        raise ImmutableDefinitionError("冻结定义和历史记录不允许批量改写")


@contextmanager
def governance(session: Session) -> Iterator[None]:
    previous = session.info.get(_GOVERNANCE, False)
    session.info[_GOVERNANCE] = True
    try:
        yield
    finally:
        session.info[_GOVERNANCE] = previous


@event.listens_for(Session, "before_flush")
def protect_definitions(session: Session, context: object, instances: object) -> None:
    allowed = session.info.get(_GOVERNANCE, False)
    _check_nested_changes(session)
    for entity in session.deleted:
        if isinstance(entity, (*_APPEND_ONLY, ToolVersion, ExecutionBinding, ToolChannel)):
            raise ImmutableDefinitionError("版本、绑定、通道及历史记录不能删除")
    for entity in session.new:
        if isinstance(entity, ToolVersion) and entity.status not in {None, "draft"} and not allowed:
            raise InvalidTransitionError("新版本必须从 draft 创建")
        if isinstance(entity, ToolChannel) and not allowed:
            raise InvalidTransitionError("通道须通过领域服务创建")
        if isinstance(entity, ExecutionBinding):
            version = session.get(ToolVersion, entity.version_id)
            if version is not None and version.status not in {None, "draft"}:
                raise ImmutableDefinitionError("不能给冻结版本添加绑定")
    for entity in session.dirty:
        state = inspect(entity)
        if not session.is_modified(entity, include_collections=True):
            continue
        if isinstance(entity, _APPEND_ONLY):
            raise ImmutableDefinitionError("历史记录只允许追加")
        if isinstance(entity, Provider) and not allowed:
            raise InvalidTransitionError("Provider 配置须通过领域服务治理")
        if isinstance(entity, ToolVersion):
            if any(
                state.attrs[name].history.has_changes() for name in ("id", "tool_id", "version")
            ):
                raise ImmutableDefinitionError("版本身份不可修改")
            history = state.attrs.status.history
            previous = history.deleted[0] if history.deleted else entity.status
            if history.has_changes() and not allowed:
                raise InvalidTransitionError("版本状态须通过领域服务迁移")
            if previous != "draft" and any(
                state.attrs[name].history.has_changes() for name in DEFINITION_FIELDS
            ):
                raise ImmutableDefinitionError("送审后版本定义已冻结")
        if (
            isinstance(entity, Tool)
            and not allowed
            and any(state.attrs[name].history.has_changes() for name in DEFINITION_FIELDS)
        ):
            raise ImmutableDefinitionError("生产投影只能随 stable 更新")
        if isinstance(entity, ToolChannel) and not allowed:
            raise InvalidTransitionError("通道须通过领域服务切换")
        if isinstance(entity, ExecutionBinding):
            if any(state.attrs[name].history.has_changes() for name in ("id", "version_id")):
                raise ImmutableDefinitionError("绑定身份不可修改")
            version = session.get(ToolVersion, entity.version_id)
            if (version is None or version.status != "draft") and any(
                state.attrs[name].history.has_changes() for name in BINDING_FIELDS
            ):
                raise ImmutableDefinitionError("送审后执行绑定已冻结")
