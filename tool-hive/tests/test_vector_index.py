"""检索索引接口测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from toolhive.config import ChromaSettings
from toolhive.infrastructure.vector_index import (
    EmbeddedChromaVectorIndex,
    VectorIndex,
    VectorIndexError,
)


class TestVectorIndex:
    def test_abstract_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            VectorIndex()  # type: ignore[abstract]


class TestEmbeddedChromaVectorIndex:
    async def test_missing_dependency_raises_vector_index_error(self) -> None:
        """chromadb 不可导入时调用应抛出 VectorIndexError。"""
        index = EmbeddedChromaVectorIndex(
            ChromaSettings(persist_directory=":memory:"),
        )
        with patch.dict("sys.modules", {"chromadb": None}):
            with pytest.raises(VectorIndexError):
                await index.query([0.1])

    async def test_missing_dependency_on_upsert_and_rebuild(self) -> None:
        """chromadb 不可导入时 upsert 与全量重建同样抛 VectorIndexError。"""
        index = EmbeddedChromaVectorIndex(
            ChromaSettings(persist_directory=":memory:"),
        )
        with patch.dict("sys.modules", {"chromadb": None}):
            with pytest.raises(VectorIndexError):
                await index.upsert("doc-1", [0.1], "text", {})
            with pytest.raises(VectorIndexError):
                await index.rebuild_batch([("doc-1", [0.1], "text", {})])
