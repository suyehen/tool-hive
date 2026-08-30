"""腾讯云 Embedding 客户端测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.config import RetrievalSettings
from toolhive.runtime.retrieval.embedding import (
    EmbeddingService,
    EmbeddingUnavailableError,
)


def _settings(**kwargs) -> RetrievalSettings:
    defaults = dict(
        model_api_key="sk-test",
        embedding_model="kinfra-text-embedding-4b",
        timeout_seconds=10,
    )
    defaults.update(kwargs)
    return RetrievalSettings(**defaults)


async def test_embedding_requires_config() -> None:
    """模型 Key 或模型名缺失时不可用。"""
    svc = EmbeddingService(_settings(model_api_key=""))
    assert not svc.is_available()
    with pytest.raises(EmbeddingUnavailableError):
        await svc.embed(["hello"])


async def test_embedding_success() -> None:
    """调用成功返回向量列表。"""
    response_mock = MagicMock()
    response_mock.raise_for_status = MagicMock()
    response_mock.json = MagicMock(
        return_value={
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ]
        }
    )
    client_mock = AsyncMock()
    client_mock.post = AsyncMock(return_value=response_mock)
    cm = AsyncMock()
    cm.__aenter__.return_value = client_mock
    cm.__aexit__.return_value = False
    factory = MagicMock(return_value=cm)
    svc = EmbeddingService(_settings())
    import toolhive.runtime.retrieval.embedding as embedding_module
    with patch.object(embedding_module.httpx, "AsyncClient", factory):
        vectors = await svc.embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


async def test_embedding_failure_raises() -> None:
    """API 失败时抛出 EmbeddingUnavailableError。"""
    client_mock = AsyncMock()
    client_mock.post = AsyncMock(side_effect=RuntimeError("network down"))
    cm = AsyncMock()
    cm.__aenter__.return_value = client_mock
    cm.__aexit__.return_value = False
    factory = MagicMock(return_value=cm)
    svc = EmbeddingService(_settings())
    import toolhive.runtime.retrieval.embedding as embedding_module
    with patch.object(embedding_module.httpx, "AsyncClient", factory):
        with pytest.raises(EmbeddingUnavailableError):
            await svc.embed(["a"])
