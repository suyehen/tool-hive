"""M0 domain persistence models (design §4, reviewed initial DDL)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.adapters.db.base import AuditMixin, Base, SnowflakePrimaryKeyMixin


class IndexMeta(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "index_meta"
    __table_args__ = (
        Index("uq_index_meta_version", "index_version", unique=True),
        Index(
            "uq_index_meta_single_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    index_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolEmbedding(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "tool_embedding"
    __table_args__ = (
        Index("uq_tool_embedding", "tool_id", "index_version", "chunk_kind", unique=True),
        Index("idx_tool_embedding_version", "index_version"),
        Index(
            "idx_tool_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
        ),
    )

    tool_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tool.id"), nullable=False)
    index_version: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    embedding: Mapped[Any] = mapped_column(HALFVEC(2560), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
