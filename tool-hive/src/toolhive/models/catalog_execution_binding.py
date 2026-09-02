"""Catalog 执行绑定 ORM 模型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CatalogExecutionBinding(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """执行绑定：工具版本 ↔ Provider 的固定映射（一对一）。"""

    __tablename__ = "catalog_execution_binding"

    version_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("catalog_tool_version.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("catalog_provider.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    method: Mapped[str] = mapped_column(
        String(16), nullable=False, default="COMPUTE",
    )  # builtin: COMPUTE | http: GET/POST/PUT/DELETE
    path_template: Mapped[str] = mapped_column(
        String(512), nullable=False,
    )  # http 路径模板或 builtin://math/{operation}
    parameter_mapping: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )
    allowed_headers: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True,
    )
    response_handling: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )  # 一期描述性元数据：无运行时转换规则，二期需定义结构后才可执行
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )  # Provider 幂等声明：一期仅管理端展示，不改变 Execute 幂等去重
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
