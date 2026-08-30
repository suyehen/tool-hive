"""检索索引接口（一期嵌入式 Chroma）。

业务代码不直接依赖 Chroma 客户端；一期使用嵌入式 Chroma：
- 生产持久化目录固定为配置的 ``persist_directory``；
- 写并发一期固定为 1，所有写入只通过 Outbox 后台任务完成；
- Embedding 由业务层（RetrievalService）负责，索引只做向量存储与召回；
- 依赖未安装、目录不可用或初始化失败时抛出 ``VectorIndexError``。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from toolhive.config import ChromaSettings

logger = logging.getLogger(__name__)


class VectorIndexError(Exception):
    """检索索引错误。"""


class VectorIndex(ABC):
    """向量检索索引接口。"""

    @abstractmethod
    async def upsert(
        self,
        doc_id: str,
        embedding: list[float],
        document: str,
        metadata: dict,
    ) -> None:
        """写入或更新一条文档（幂等，按稳定业务 ID）。"""

    @abstractmethod
    async def delete(self, doc_id: str) -> None:
        """按稳定业务 ID 删除文档。"""

    @abstractmethod
    async def query(
        self, embedding: list[float], top_k: int = 10,
    ) -> list[tuple[str, float]]:
        """按向量召回候选，返回 ``(doc_id, distance)`` 列表。"""

    @abstractmethod
    async def rebuild_batch(
        self,
        entries: list[tuple[str, list[float], str, dict]],
    ) -> None:
        """清空并批量重建（``(doc_id, embedding, document, metadata)``）。"""


class EmbeddedChromaVectorIndex(VectorIndex):
    """一期嵌入式 Chroma 实现。"""

    COLLECTION_NAME = "tool_catalog"

    def __init__(self, chroma_settings: ChromaSettings) -> None:
        self._chroma = chroma_settings
        self._persist_directory = chroma_settings.persist_directory
        self._collection = None

    def _ensure_collection(self):
        """懒加载 chromadb 客户端与集合。"""
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
        except ImportError as exc:
            raise VectorIndexError(
                "chromadb 未安装，无法使用检索索引（需兼容 CPython 3.11.6）"
            ) from exc
        try:
            client = chromadb.PersistentClient(path=self._persist_directory)
            self._collection = client.get_or_create_collection(self.COLLECTION_NAME)
        except Exception as exc:
            raise VectorIndexError(
                f"Chroma 初始化失败（持久化目录不可用或依赖不兼容）: {exc}"
            ) from exc
        return self._collection

    async def upsert(
        self,
        doc_id: str,
        embedding: list[float],
        document: str,
        metadata: dict,
    ) -> None:
        collection = self._ensure_collection()
        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[document],
            metadatas=[metadata],
        )
        logger.info("chroma upsert doc_id=%s", doc_id)

    async def delete(self, doc_id: str) -> None:
        collection = self._ensure_collection()
        collection.delete(ids=[doc_id])
        logger.info("chroma delete doc_id=%s", doc_id)

    async def query(
        self, embedding: list[float], top_k: int = 10,
    ) -> list[tuple[str, float]]:
        collection = self._ensure_collection()
        result = collection.query(query_embeddings=[embedding], n_results=top_k)
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return list(zip(ids, distances))

    async def rebuild_batch(
        self,
        entries: list[tuple[str, list[float], str, dict]],
    ) -> None:
        """全量重建：清空集合后一次性写入全部文档。"""
        collection = self._ensure_collection()
        try:
            collection.delete(where={})
        except Exception:
            # 空集合删除可能无效果，忽略
            pass
        if not entries:
            logger.info("chroma full rebuild finished with empty dataset")
            return
        ids = [entry[0] for entry in entries]
        embeddings = [entry[1] for entry in entries]
        documents = [entry[2] for entry in entries]
        metadatas = [entry[3] for entry in entries]
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info("chroma full rebuild finished count=%s", len(entries))
