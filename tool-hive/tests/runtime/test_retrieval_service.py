"""检索服务测试：向量/降级、索引同步与重建。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from toolhive.core.enums import (
    CatalogObjectStatus,
)
from toolhive.models.catalog_tool import CatalogTool
from toolhive.runtime.retrieval.service import (
    RetrievalService,
    build_tool_document,
)


def _tool(status: str = CatalogObjectStatus.ENABLED, discoverable: bool = True) -> CatalogTool:
    return CatalogTool(
        id="tool-1",
        namespace="math.basic",
        tool_code="calculator",
        name="计算器",
        description="数学计算",
        status=status,
        discoverable=discoverable,
        row_version=0,
    )


async def test_build_tool_document_contains_key_fields() -> None:
    """索引文档包含名称/完整标识/描述/风险/版本。"""
    doc = build_tool_document(_tool(), "1.0.0")
    assert "计算器" in doc
    assert "math.basic.calculator" in doc
    assert "数学计算" in doc
    assert "1.0.0" in doc


async def test_discover_vector_success() -> None:
    """向量检索成功且不降级。"""
    db = AsyncMock()
    svc = RetrievalService(db)
    with (
        patch(
            "toolhive.runtime.retrieval.service.EmbeddingService"
        ) as embed_cls,
        patch(
            "toolhive.runtime.retrieval.service.EmbeddedChromaVectorIndex"
        ) as index_cls,
        patch(
            "toolhive.runtime.retrieval.service.CallControlService"
        ) as control_cls,
        patch(
            "toolhive.runtime.retrieval.service.fetch_default_versions",
            new=AsyncMock(return_value={"tool-1": "1.0.0"}),
        ),
    ):
        embed_cls.return_value.is_available.return_value = True
        embed_cls.return_value.embed_one = AsyncMock(return_value=[0.1])
        index_cls.return_value.query = AsyncMock(
            return_value=[("math.basic.calculator", 0.1)]
        )
        control_cls.return_value.list_discoverable_tools = AsyncMock(
            return_value=[_tool()]
        )
        db.execute = AsyncMock(
            return_value=MagicMock(
                scalars=MagicMock(
                    return_value=MagicMock(all=MagicMock(return_value=[_tool()]))
                )
            )
        )
        items, degraded, coverage = await svc.discover("sys_1", "计算", limit=20)
    assert not degraded
    assert items[0]["tool_code"] == "math.basic.calculator"
    assert coverage == 1.0


async def test_discover_falls_back_to_keyword() -> None:
    """向量检索失败时降级关键词并标记 degraded。"""
    db = AsyncMock()
    svc = RetrievalService(db)
    with (
        patch(
            "toolhive.runtime.retrieval.service.EmbeddingService"
        ) as embed_cls,
        patch(
            "toolhive.runtime.retrieval.service.EmbeddedChromaVectorIndex"
        ) as index_cls,
        patch(
            "toolhive.runtime.retrieval.service.KeywordRetrieval"
        ) as keyword_cls,
        patch(
            "toolhive.runtime.retrieval.service.CallControlService"
        ) as control_cls,
        patch(
            "toolhive.runtime.retrieval.service.fetch_default_versions",
            new=AsyncMock(return_value={"tool-1": "1.0.0"}),
        ),
    ):
        embed_cls.return_value.is_available.return_value = True
        embed_cls.return_value.embed_one = AsyncMock(
            side_effect=RuntimeError("embedding down")
        )
        index_cls.return_value.query = AsyncMock()
        keyword_cls.return_value.search = AsyncMock(return_value=[_tool()])
        control_cls.return_value.list_discoverable_tools = AsyncMock(
            return_value=[_tool()]
        )
        items, degraded, coverage = await svc.discover("sys_1", "计算", limit=20)
    assert degraded is True
    assert len(items) == 1
    assert coverage == 1.0


async def test_discover_falls_back_on_unexpected_vector_error() -> None:
    """向量链路非特定异常同样降级关键词，不向调用方暴露内部错误。"""
    db = AsyncMock()
    svc = RetrievalService(db)
    with (
        patch(
            "toolhive.runtime.retrieval.service.EmbeddingService"
        ) as embed_cls,
        patch(
            "toolhive.runtime.retrieval.service.EmbeddedChromaVectorIndex"
        ) as index_cls,
        patch(
            "toolhive.runtime.retrieval.service.KeywordRetrieval"
        ) as keyword_cls,
        patch(
            "toolhive.runtime.retrieval.service.CallControlService"
        ) as control_cls,
        patch(
            "toolhive.runtime.retrieval.service.fetch_default_versions",
            new=AsyncMock(return_value={"tool-1": "1.0.0"}),
        ),
    ):
        embed_cls.return_value.is_available.return_value = True
        embed_cls.return_value.embed_one = AsyncMock(
            side_effect=ValueError("unexpected")
        )
        index_cls.return_value.query = AsyncMock()
        keyword_cls.return_value.search = AsyncMock(return_value=[_tool()])
        control_cls.return_value.list_discoverable_tools = AsyncMock(
            return_value=[_tool()]
        )
        items, degraded, coverage = await svc.discover("sys_1", "计算", limit=20)
    assert degraded is True
    assert len(items) == 1
    assert coverage == 1.0


async def test_sync_tool_upserts_when_published() -> None:
    """启用+可发现+已发布工具 upsert 索引。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_tool())
    svc = RetrievalService(db)
    with (
        patch(
            "toolhive.runtime.retrieval.service.EmbeddingService"
        ) as embed_cls,
        patch(
            "toolhive.runtime.retrieval.service.EmbeddedChromaVectorIndex"
        ) as index_cls,
        patch(
            "toolhive.runtime.retrieval.service.fetch_default_versions",
            new=AsyncMock(return_value={"tool-1": "1.0.0"}),
        ),
    ):
        embed_cls.return_value.embed_one = AsyncMock(return_value=[0.1])
        index_cls.return_value.upsert = AsyncMock()
        await svc.sync_tool("tool-1")
    index_cls.return_value.upsert.assert_awaited_once()


async def test_sync_tool_deletes_when_disabled() -> None:
    """停用工具从索引删除。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_tool(status=CatalogObjectStatus.DISABLED))
    svc = RetrievalService(db)
    with (
        patch(
            "toolhive.runtime.retrieval.service.EmbeddedChromaVectorIndex"
        ) as index_cls,
        patch(
            "toolhive.runtime.retrieval.service.fetch_default_versions",
            new=AsyncMock(return_value={}),
        ),
    ):
        index_cls.return_value.delete = AsyncMock()
        await svc.sync_tool("tool-1")
    index_cls.return_value.delete.assert_awaited_once()


async def test_rebuild_index_embeds_all() -> None:
    """全量重建返回索引条数。"""
    db = AsyncMock()
    tools_result = MagicMock()
    tools_result.scalars.return_value.all.return_value = [_tool()]
    rows = MagicMock()
    rows.all.return_value = [("tool-1", "1.0.0")]
    db.execute = AsyncMock(side_effect=[tools_result, rows])
    svc = RetrievalService(db)
    with (
        patch(
            "toolhive.runtime.retrieval.service.EmbeddingService"
        ) as embed_cls,
        patch(
            "toolhive.runtime.retrieval.service.EmbeddedChromaVectorIndex"
        ) as index_cls,
    ):
        embed_cls.return_value.embed = AsyncMock(return_value=[[0.1]])
        index_cls.return_value.rebuild_batch = AsyncMock()
        count = await svc.rebuild_index()
    assert count == 1
    index_cls.return_value.rebuild_batch.assert_awaited_once()
