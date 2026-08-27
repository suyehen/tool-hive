"""运行侧调用系统签名认证服务。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote

from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from toolhive.config import RuntimeSecuritySettings
from toolhive.core.enums import CallerSystemStatus, IPRuleStatus
from toolhive.models.caller_ip_rule import CallerIPRule
from toolhive.models.caller_public_key import CallerPublicKey
from toolhive.models.caller_system import CallerSystem
from toolhive.runtime.authentication.verifiers import get_verifier
from toolhive.runtime.errors import (
    RUNTIME_AUTH_EXPIRED_TIMESTAMP,
    RUNTIME_AUTH_INVALID_SIGNATURE,
    RUNTIME_AUTH_INVALID_SYSTEM,
    RUNTIME_AUTH_IP_NOT_ALLOWED,
    RUNTIME_AUTH_REPLAYED_NONCE,
    RUNTIME_AUTH_SECURITY_UNAVAILABLE,
    RuntimeApiError,
)
from toolhive.services.caller_system_service import CallerSystemService

logger = logging.getLogger(__name__)

# 签名请求头（《一期下半设计冻结》4.2）
HDR_SYSTEM_ID = "x-toolhive-system-id"
HDR_KEY_ID = "x-toolhive-key-id"
HDR_TIMESTAMP = "x-toolhive-timestamp"
HDR_NONCE = "x-toolhive-nonce"
HDR_SIGNATURE = "x-toolhive-signature"
HDR_TRACE_ID = "x-toolhive-trace-id"

_NONCE_KEY_PREFIX = "toolhive:nonce:"


@dataclass
class RuntimeIdentity:
    """运行请求认证结果：调用系统、公钥、来源 IP 与 Trace ID。"""

    system: CallerSystem
    key: CallerPublicKey
    source_ip: str
    trace_id: str


def normalize_query(query_string: str) -> str:
    """规范化查询串：按 key/value 排序后重新编码，无查询串时返回空串。"""
    if not query_string:
        return ""
    pairs = parse_qsl(query_string, keep_blank_values=True)
    pairs.sort(key=lambda item: (item[0], item[1]))
    return "&".join(
        f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in pairs
    )


def build_canonical(
    *,
    method: str,
    path: str,
    query_string: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> bytes:
    """按冻结契约构造 canonical 串：METHOD\\nPATH\\nQUERY\\nTS\\nNONCE\\nSHA256(body)。"""
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = (
        f"{method}\n{path}\n{normalize_query(query_string)}\n"
        f"{timestamp}\n{nonce}\n{body_hash}"
    )
    return canonical.encode("utf-8")


class RuntimeAuthService:
    """调用系统请求认证：签名、时间窗、Nonce 与实时状态校验。"""

    def __init__(
        self,
        db: AsyncSession,
        redis: AsyncRedis,
        runtime_security: RuntimeSecuritySettings,
    ):
        self.db = db
        self.redis = redis
        self.security = runtime_security

    async def authenticate(self, request: Request, trace_id: str) -> RuntimeIdentity:
        """认证运行请求并返回调用系统身份；任一步失败抛出 RuntimeApiError。"""
        system_id = request.headers.get(HDR_SYSTEM_ID, "")
        key_id = request.headers.get(HDR_KEY_ID, "")
        timestamp_raw = request.headers.get(HDR_TIMESTAMP, "")
        nonce = request.headers.get(HDR_NONCE, "")
        signature_raw = request.headers.get(HDR_SIGNATURE, "")
        if not all((system_id, key_id, timestamp_raw, nonce, signature_raw)):
            raise RuntimeApiError(
                RUNTIME_AUTH_INVALID_SIGNATURE,
                "缺少签名请求头（system_id/key_id/timestamp/nonce/signature）",
                401,
            )

        # 查询调用系统并校验生命周期状态与有效期
        system = await self._load_system(system_id)
        if system is None or system.status != CallerSystemStatus.ENABLED:
            raise RuntimeApiError(
                RUNTIME_AUTH_INVALID_SYSTEM,
                "调用系统不存在或未启用",
                401,
            )
        if system.emergency_disabled:
            raise RuntimeApiError(
                RUNTIME_AUTH_INVALID_SYSTEM,
                "调用系统已被紧急禁用",
                401,
            )
        if system.effective_state != "effective":
            raise RuntimeApiError(
                RUNTIME_AUTH_INVALID_SYSTEM,
                "调用系统不在有效期内",
                401,
            )

        # 来源 IP 规则校验（复用一期上 IP 规则）
        source_ip = getattr(request.state, "client_ip", "") or (
            request.client.host if request.client else ""
        )
        rules = await self._load_ip_rules(system_id)
        if not CallerSystemService.verify_ip(system_id, source_ip, rules):
            raise RuntimeApiError(
                RUNTIME_AUTH_IP_NOT_ALLOWED,
                f"来源 IP 不在调用系统白名单: {source_ip}",
                401,
            )

        # 时间窗口校验
        try:
            timestamp = int(timestamp_raw)
        except ValueError:
            raise RuntimeApiError(
                RUNTIME_AUTH_EXPIRED_TIMESTAMP,
                "时间戳格式无效",
                401,
            )
        now = int(time.time())
        if abs(now - timestamp) > self.security.signature_time_window_seconds:
            raise RuntimeApiError(
                RUNTIME_AUTH_EXPIRED_TIMESTAMP,
                "请求时间戳超出允许的时间窗口",
                401,
            )

        # 公钥查询与实时状态校验（key_id 精确选择，算法以公钥记录为准）
        key = await self._load_key(key_id)
        if key is None or key.system_id != system_id or not key.is_valid():
            raise RuntimeApiError(
                RUNTIME_AUTH_INVALID_SIGNATURE,
                "公钥不存在、不属于该系统或已失效",
                401,
            )
        verifier = get_verifier(key.algorithm)

        # canonical 构造与签名验证
        body = await request.body()
        canonical = build_canonical(
            method=request.method,
            path=request.url.path,
            query_string=request.url.query,
            timestamp=timestamp_raw,
            nonce=nonce,
            body=body,
        )
        try:
            signature = base64.b64decode(signature_raw, validate=True)
        except (ValueError, binascii.Error):
            raise RuntimeApiError(
                RUNTIME_AUTH_INVALID_SIGNATURE,
                "签名格式无效（必须为 base64）",
                401,
            )
        if not verifier.verify(canonical, signature, key.public_key):
            raise RuntimeApiError(
                RUNTIME_AUTH_INVALID_SIGNATURE,
                "请求签名验证失败",
                401,
            )

        # Nonce 防重放：SET NX + TTL；Redis 不可用默认拒绝
        await self._consume_nonce(system_id, nonce)
        return RuntimeIdentity(
            system=system,
            key=key,
            source_ip=source_ip,
            trace_id=trace_id,
        )

    async def _load_system(self, system_id: str) -> CallerSystem | None:
        """按 system_id 查询调用系统。"""
        return await self.db.scalar(
            select(CallerSystem).where(CallerSystem.system_id == system_id)
        )

    async def _load_ip_rules(self, system_id: str) -> list[CallerIPRule]:
        """查询调用系统全部有效来源 IP 规则。"""
        result = await self.db.execute(
            select(CallerIPRule).where(
                CallerIPRule.system_id == system_id,
                CallerIPRule.status == IPRuleStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())

    async def _load_key(self, key_id: str) -> CallerPublicKey | None:
        """按 key_id 查询调用系统公钥。"""
        return await self.db.scalar(
            select(CallerPublicKey).where(CallerPublicKey.key_id == key_id)
        )

    async def _consume_nonce(self, system_id: str, nonce: str) -> None:
        """消费一次性 Nonce；已存在则判定为重放，Redis 不可用默认拒绝。"""
        key = f"{_NONCE_KEY_PREFIX}{system_id}:{nonce}"
        ttl = self.security.nonce_retention_minutes * 60
        try:
            created = await self.redis.set(key, "1", nx=True, ex=ttl)
        except Exception as exc:  # Redis 不可用：默认拒绝，不允许降级放行
            logger.error("nonce redis unavailable system=%s error=%s", system_id, exc)
            raise RuntimeApiError(
                RUNTIME_AUTH_SECURITY_UNAVAILABLE,
                "安全依赖不可用，请求被拒绝",
                503,
            ) from exc
        if not created:
            raise RuntimeApiError(
                RUNTIME_AUTH_REPLAYED_NONCE,
                "Nonce 重复，疑似重放请求",
                401,
            )
