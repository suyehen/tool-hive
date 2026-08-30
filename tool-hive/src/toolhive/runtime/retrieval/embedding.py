"""腾讯云 TokenHub Embedding 客户端。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from toolhive.config import RetrievalSettings

logger = logging.getLogger(__name__)

_EMBEDDING_ENDPOINT = "https://tokenhub.tencentmaas.com/v1/embeddings"


class EmbeddingUnavailableError(Exception):
    """Embedding 服务不可用（Key 缺失 / 调用失败 / 响应非法）。"""


class EmbeddingService:
    """按配置调用腾讯云 Embedding API 生成向量。"""

    def __init__(self, retrieval: RetrievalSettings):
        self._retrieval = retrieval

    def is_available(self) -> bool:
        """模型 Key 与模型名均已配置时可用。"""
        return bool(
            self._retrieval.model_api_key and self._retrieval.embedding_model
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成文本向量；任一步失败抛出 EmbeddingUnavailableError。"""
        if not self.is_available():
            raise EmbeddingUnavailableError("Embedding 模型 Key 或模型名未配置")
        payload = {"model": self._retrieval.embedding_model, "input": texts}
        headers = {
            "Authorization": f"Bearer {self._retrieval.model_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._retrieval.timeout_seconds)
            ) as client:
                response = await client.post(
                    _EMBEDDING_ENDPOINT, json=payload, headers=headers,
                )
                response.raise_for_status()
                data = response.json()
            vectors: list[Any] = [item["embedding"] for item in data["data"]]
        except Exception as exc:
            logger.error("embedding request failed: %s", exc)
            raise EmbeddingUnavailableError("Embedding 调用失败") from exc
        if len(vectors) != len(texts):
            raise EmbeddingUnavailableError(
                "Embedding 返回数量与输入不一致"
            )
        return [
            [float(value) for value in vector] for vector in vectors
        ]

    async def embed_one(self, text: str) -> list[float]:
        """生成单条文本向量。"""
        vectors = await self.embed([text])
        return vectors[0]
