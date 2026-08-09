"""Chroma 工具索引 — 从 Catalog 派生检索摘要。"""

from __future__ import annotations


class ChromaToolIndex:
    """管理 Chroma 工具索引：同步 Outbox、检索、过滤。"""

    def __init__(self, host: str, port: int, collection: str):
        self.host = host
        self.port = port
        self.collection = collection

    async def sync_outbox(self):
        """消费 index_outbox 事件，同步 PG → Chroma。"""
        # TODO: 实现 Outbox 消费
        pass

    async def search(self, query: str, audience_scopes: list[str], top_k: int = 10):
        """混合召回：BM25 + Embedding → 去重 → 重排。"""
        # TODO: 实现混合召回
        return []
