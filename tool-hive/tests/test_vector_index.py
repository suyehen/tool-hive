"""检索索引接口测试。"""

from __future__ import annotations

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
        """未安装 chromadb 时（当前环境），调用应抛出 VectorIndexError。"""
        index = EmbeddedChromaVectorIndex(
            ChromaSettings(persist_directory=":memory:"),
        )
        with pytest.raises(VectorIndexError):
            await index.query("test")
