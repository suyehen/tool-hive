"""MCP 运行侧 Bearer Token 认证服务与来源限制判定。

阶段 2 定稿：SDK 原生 TokenVerifier 无法感知来源 IP，因此完整认证放在宿主侧
鉴权中间件（middleware.py），本模块提供可测试的认证逻辑。
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import IPRuleStatus, McpClientStatus, McpTokenStatus
from toolhive.models.mcp_client import McpClient
from toolhive.models.mcp_client_ip_rule import McpClientIpRule
from toolhive.models.mcp_client_token import McpClientToken
from toolhive.models.mcp_server_config import (
    MCP_SERVER_CONFIG_ID,
    McpServerConfig,
)
from toolhive.services.security.password import verify_password

logger = logging.getLogger(__name__)

# 当前请求认证身份（宿主中间件写入，供 MCP 低层 handler 读取）
current_mcp_identity: ContextVar[McpAuthIdentity | None] = ContextVar(
    "current_mcp_identity", default=None,
)

# MCP 认证错误码与 HTTP 状态
MCP_AUTH_TOKEN_INVALID = "MCP_AUTH_TOKEN_INVALID"
MCP_AUTH_CLIENT_DISABLED = "MCP_AUTH_CLIENT_DISABLED"
MCP_AUTH_SOURCE_NOT_ALLOWED = "MCP_AUTH_SOURCE_NOT_ALLOWED"
MCP_SERVER_DISABLED = "MCP_SERVER_DISABLED"


class McpAuthError(Exception):
    """MCP 认证拒绝（携带统一错误码与 HTTP 状态）。"""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass
class McpAuthIdentity:
    """认证结果：MCP 客户端、对应令牌记录与来源 IP。"""

    client: McpClient
    token: McpClientToken
    source_ip: str


class McpAuthService:
    """按 Bearer Token 认证 MCP 请求并校验客户端实时状态与来源限制。"""

    def __init__(self, db: AsyncSession, source_ip: str):
        self.db = db
        self.source_ip = source_ip

    async def authenticate(self, token: str) -> McpAuthIdentity:
        """执行完整认证；任一步失败抛出 McpAuthError。"""
        if not token:
            raise McpAuthError(
                MCP_AUTH_TOKEN_INVALID, "缺少访问令牌", 401,
            )
        # Server 全局停用：所有 MCP 请求直接拒绝
        config = await self.db.get(McpServerConfig, MCP_SERVER_CONFIG_ID)
        if config is not None and not config.enabled:
            raise McpAuthError(
                MCP_SERVER_DISABLED, "MCP 入口已停用", 403,
            )
        # 用 token_key 精确定位 ACTIVE 令牌，再做 argon2 比对
        token_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        token_record = await self.db.scalar(
            select(McpClientToken).where(
                McpClientToken.token_key == token_key,
                McpClientToken.status == McpTokenStatus.ACTIVE,
            )
        )
        if token_record is None:
            raise McpAuthError(
                MCP_AUTH_TOKEN_INVALID, "认证失败", 401,
            )
        client = await self.db.get(McpClient, token_record.client_id)
        if (
            client is None
            or client.status != McpClientStatus.ENABLED
        ):
            raise McpAuthError(
                MCP_AUTH_CLIENT_DISABLED, "客户端不可用", 401,
            )
        valid, _ = verify_password(token, token_record.token_hash)
        if not valid:
            raise McpAuthError(
                MCP_AUTH_TOKEN_INVALID, "认证失败", 401,
            )
        # 来源 IP 规则实时校验（默认拒绝：无规则或全部停用则拒绝）
        rules = await self._list_active_ip_rules(client.id)
        if not self._source_allowed(self.source_ip, rules):
            raise McpAuthError(
                MCP_AUTH_SOURCE_NOT_ALLOWED,
                f"来源不在允许范围: {self.source_ip}",
                403,
            )
        return McpAuthIdentity(
            client=client, token=token_record, source_ip=self.source_ip,
        )

    async def _list_active_ip_rules(
        self, client_id: str,
    ) -> list[McpClientIpRule]:
        """查询客户端 ACTIVE 来源规则。"""
        result = await self.db.execute(
            select(McpClientIpRule).where(
                McpClientIpRule.client_id == client_id,
                McpClientIpRule.status == IPRuleStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())

    @staticmethod
    def _source_allowed(
        source_ip: str, rules: list[McpClientIpRule],
    ) -> bool:
        """判断来源 IP 是否命中任一 ACTIVE 规则；无规则或非法规则默认拒绝。"""
        if not source_ip:
            return False
        try:
            address = ipaddress.ip_address(source_ip)
        except ValueError:
            return False
        for rule in rules:
            value = rule.ip_cidr.strip()
            if value == "*":
                return True
            try:
                if "/" in value:
                    network = ipaddress.ip_network(value, strict=False)
                    if address in network:
                        return True
                elif address == ipaddress.ip_address(value):
                    return True
            except ValueError:
                logger.error(
                    "mcp ip rule invalid client=%s cidr=%s",
                    rule.client_id, value,
                )
        return False
