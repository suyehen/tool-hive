"""检索服务：向量优先 + 关键词降级 + 调用控制过滤 + 索引同步与重建。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.config import settings
from toolhive.core.enums import CatalogObjectStatus
from toolhive.infrastructure.vector_index import (
    EmbeddedChromaVectorIndex,
    VectorIndexError,
)
from toolhive.models.catalog_tool import CatalogTool
from toolhive.runtime.errors import (
    RUNTIME_RETRIEVAL_UNAVAILABLE,
    RuntimeApiError,
)
from toolhive.runtime.retrieval.embedding import (
    EmbeddingService,
    EmbeddingUnavailableError,
)
from toolhive.runtime.retrieval.keyword import KeywordRetrieval, fetch_default_versions
from toolhive.runtime.tool_control.service import CallControlService

logger = logging.getLogger(__name__)


def build_tool_document(tool: CatalogTool, version: str | None) -> str:
    """构造工具索引文档文本（名称/完整标识/描述/风险/版本）。"""
    parts = [tool.name, tool.full_code]
    if tool.description:
        parts.append(tool.description)
    parts.append(f"风险等级: {tool.risk_level}")
    if version:
        parts.append(f"版本: {version}")
    return "\n".join(parts)


def build_tool_metadata(tool: CatalogTool, version: str | None) -> dict[str, Any]:
    """构造工具索引元数据。"""
    return {
        "namespace": tool.namespace,
        "tool_code": tool.tool_code,
        "name": tool.name,
        "risk_level": tool.risk_level,
        "version": version or "",
    }


class RetrievalService:
    """Discover 检索与 Catalog 派生索引同步（Chroma 不可全量重建）。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def discover(
        self, system_id: str, query: str, limit: int = 20,
    ) -> tuple[list[dict], bool, float]:
        """向量检索优先；失败降级关键词；返回 (items, degraded, coverage)。"""
        try:
            items = await self._vector_discover(system_id, query, limit)
            degraded = False
        except (VectorIndexError, EmbeddingUnavailableError) as exc:
            logger.warning(
                "vector retrieval unavailable, fallback keyword: %s", exc,
            )
            items = await self._keyword_discover(system_id, query, limit)
            degraded = True
        except Exception as exc:
            # 非特定异常也统一受控降级，避免向调用方暴露内部错误
            logger.error(
                "vector retrieval failed unexpectedly, fallback keyword: %s", exc,
            )
            items = await self._keyword_discover(system_id, query, limit)
            degraded = True
        total = len(
            await CallControlService(self.db).list_discoverable_tools(system_id)
        )
        coverage = round(len(items) / total, 4) if total else 0.0
        return items, degraded, coverage

    async def sync_tool(self, tool_id: str) -> None:
        """按工具当前状态同步索引：启用+可发现+已发布 → upsert，否则 delete。"""
        tool = await self.db.get(CatalogTool, tool_id)
        if tool is None:
            return
        index = EmbeddedChromaVectorIndex(settings.chroma)
        versions = await fetch_default_versions(self.db, [tool])
        version = versions.get(tool.id)
        if (
            tool.status != CatalogObjectStatus.ENABLED
            or not tool.discoverable
            or version is None
        ):
            await self._safe_delete(index, tool.full_code)
            return
        document = build_tool_document(tool, version)
        embedding = await EmbeddingService(settings.retrieval).embed_one(document)
        await index.upsert(
            tool.full_code,
            embedding,
            document,
            build_tool_metadata(tool, version),
        )

    async def rebuild_index(self) -> int:
        """以 PostgreSQL 为唯一事实来源全量重建索引。"""
        tools = list(
            (
                await self.db.execute(
                    select(CatalogTool).where(
                        CatalogTool.status == CatalogObjectStatus.ENABLED,
                        CatalogTool.discoverable.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        versions = await fetch_default_versions(self.db, tools)
        kept = [tool for tool in tools if versions.get(tool.id)]
        documents = [
            build_tool_document(tool, versions.get(tool.id)) for tool in kept
        ]
        embeddings = await EmbeddingService(settings.retrieval).embed(documents)
        entries = [
            (
                tool.full_code,
                embedding,
                document,
                build_tool_metadata(tool, versions.get(tool.id)),
            )
            for tool, document, embedding in zip(kept, documents, embeddings)
        ]
        index = EmbeddedChromaVectorIndex(settings.chroma)
        await index.rebuild_batch(entries)
        return len(entries)

    async def _vector_discover(
        self, system_id: str, query: str, limit: int,
    ) -> list[dict]:
        """Chroma 向量召回 + 调用控制过滤（不扩大可见范围）。"""
        embedding_service = EmbeddingService(settings.retrieval)
        if not embedding_service.is_available():
            raise EmbeddingUnavailableError("Embedding 未配置")
        try:
            embedding = await embedding_service.embed_one(query)
        except Exception as exc:
            raise EmbeddingUnavailableError("向量化失败") from exc
        index = EmbeddedChromaVectorIndex(settings.chroma)
        hits = await index.query(embedding, top_k=limit * 3)
        codes = [doc_id for doc_id, _ in hits]
        tools_by_code = await self._load_tools_by_code(codes)
        allowed = await CallControlService(self.db).list_discoverable_tools(
            system_id
        )
        allowed_ids = {tool.id for tool in allowed}
        ranked: list[tuple[float, CatalogTool]] = []
        for doc_id, distance in hits:
            tool = tools_by_code.get(doc_id)
            if tool is None or tool.id not in allowed_ids:
                continue
            ranked.append((distance, tool))
            if len(ranked) >= limit:
                break
        ranked.sort(key=lambda item: item[0])
        tools = [tool for _, tool in ranked]
        versions = await fetch_default_versions(self.db, tools)
        return self._to_items(tools, versions)

    async def _keyword_discover(
        self, system_id: str, query: str, limit: int,
    ) -> list[dict]:
        """关键词降级检索；数据库层失败返回检索暂不可用。"""
        try:
            tools = await KeywordRetrieval(self.db).search(
                system_id, query, limit,
            )
        except Exception as exc:
            logger.error("keyword retrieval failed: %s", exc)
            raise RuntimeApiError(
                RUNTIME_RETRIEVAL_UNAVAILABLE, "检索暂不可用", 503,
            ) from exc
        versions = await fetch_default_versions(self.db, tools)
        return self._to_items(tools, versions)

    async def _load_tools_by_code(
        self, codes: list[str],
    ) -> dict[str, CatalogTool]:
        """按完整工具标识批量加载工具。"""
        if not codes:
            return {}
        result = await self.db.execute(
            select(CatalogTool).where(
                (CatalogTool.namespace + "." + CatalogTool.tool_code).in_(codes)
            )
        )
        return {tool.full_code: tool for tool in result.scalars().all()}

    @staticmethod
    def _to_items(
        tools: list[CatalogTool], versions: dict[str, str],
    ) -> list[dict]:
        """组装 Discover 候选条目。"""
        return [
            {
                "tool_code": tool.full_code,
                "name": tool.name,
                "description": tool.description,
                "risk_level": tool.risk_level,
                "version": versions.get(tool.id, ""),
            }
            for tool in tools
        ]

    @staticmethod
    async def _safe_delete(index, doc_id: str) -> None:
        """删除索引文档；文档不存在等错误不阻断同步。"""
        try:
            await index.delete(doc_id)
        except Exception as exc:
            logger.warning("chroma delete ignored doc_id=%s error=%s", doc_id, exc)
