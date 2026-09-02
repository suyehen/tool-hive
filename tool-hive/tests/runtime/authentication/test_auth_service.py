"""运行侧签名认证服务测试：canonical、验签、时间窗、Nonce、IP 与状态校验。"""

from __future__ import annotations

import base64
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from toolhive.config import RuntimeSecuritySettings
from toolhive.core.enums import (
    CallerSystemStatus,
    IPRuleStatus,
    PublicKeyStatus,
)
from toolhive.models.caller_ip_rule import CallerIPRule
from toolhive.models.caller_public_key import CallerPublicKey
from toolhive.models.caller_system import CallerSystem
from toolhive.runtime.authentication.service import (
    RuntimeAuthService,
    build_canonical,
    normalize_query,
)
from toolhive.runtime.errors import (
    RUNTIME_AUTH_EXPIRED_TIMESTAMP,
    RUNTIME_AUTH_INVALID_SIGNATURE,
    RUNTIME_AUTH_INVALID_SYSTEM,
    RUNTIME_AUTH_IP_NOT_ALLOWED,
    RUNTIME_AUTH_REPLAYED_NONCE,
    RUNTIME_AUTH_SECURITY_UNAVAILABLE,
    RuntimeApiError,
)


def _make_keypair() -> tuple[str, str]:
    """生成 RSA 密钥对，返回 (公钥 PEM, 私钥 PEM)。"""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption(),
    ).decode("utf-8")
    return public_pem, private_pem


def _sign(private_pem: str, canonical: bytes) -> str:
    """用 RSA-PSS-SHA256（salt=32）签名 canonical。"""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    private_key = load_pem_private_key(private_pem.encode(), password=None)
    signature = private_key.sign(
        canonical,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=32,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def _system() -> CallerSystem:
    return CallerSystem(
        system_id="sys_1",
        name="测试系统",
        environment="development",
        code="test",
        status=CallerSystemStatus.ENABLED,
        emergency_disabled=False,
    )


def _key(public_pem: str) -> CallerPublicKey:
    return CallerPublicKey(
        key_id="key_1",
        system_id="sys_1",
        public_key=public_pem,
        fingerprint="fp",
        algorithm="RSA-PSS-SHA256",
        status=PublicKeyStatus.ACTIVE,
        effective_from=datetime.now(UTC) - timedelta(hours=1),
        effective_to=None,
    )


def _rule() -> CallerIPRule:
    return CallerIPRule(
        system_id="sys_1", ip_cidr="10.0.0.0/8", status=IPRuleStatus.ACTIVE,
    )


class _FakeURL:
    path = "/api/runtime/v1/ping"
    query = "a=2&b=1"


class _FakeRequest:
    def __init__(self, headers: dict, body: bytes = b"{}", client_ip: str = "10.1.1.1"):
        self.headers = headers
        self._body = body
        self.method = "POST"
        self.url = _FakeURL()
        self.state = SimpleNamespace(client_ip=client_ip)

    async def body(self) -> bytes:
        return self._body


def _headers(private_pem: str, timestamp: int | None = None) -> dict:
    """构造签名请求头（canonical 覆盖方法与路径）。"""
    ts = str(timestamp if timestamp is not None else int(time.time()))
    headers = {
        "x-toolhive-system-id": "sys_1",
        "x-toolhive-key-id": "key_1",
        "x-toolhive-timestamp": ts,
        "x-toolhive-nonce": "nonce-1",
    }
    body = b"{}"
    canonical = build_canonical(
        method="POST",
        path="/api/runtime/v1/ping",
        query_string="a=2&b=1",
        timestamp=ts,
        nonce="nonce-1",
        body=body,
    )
    headers["x-toolhive-signature"] = _sign(private_pem, canonical)
    return headers


def _service(db: AsyncMock, redis: AsyncMock) -> RuntimeAuthService:
    return RuntimeAuthService(
        db,
        redis,
        RuntimeSecuritySettings(
            signature_time_window_seconds=300,
            nonce_retention_minutes=10,
        ),
    )


def _execute_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


async def test_normalize_query_sorts_and_reencodes() -> None:
    """查询串按 key/value 排序后重新编码。"""
    assert normalize_query("b=2&a=1") == "a=1&b=2"
    assert normalize_query("a=1&a=2") == "a=1&a=2"
    assert normalize_query("") == ""


async def test_authenticate_success() -> None:
    """有效签名 + 时间窗 + Nonce + IP + 公钥均通过时返回身份。"""
    public_pem, private_pem = _make_keypair()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), _key(public_pem)])
    db.execute = AsyncMock(return_value=_execute_result([_rule()]))
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    svc = _service(db, redis)

    identity = await svc.authenticate(_FakeRequest(_headers(private_pem)), "trace-1")
    assert identity.system.system_id == "sys_1"
    assert identity.source_ip == "10.1.1.1"
    assert identity.trace_id == "trace-1"
    redis.set.assert_awaited_once()


async def test_authenticate_rejects_pending_public_key() -> None:
    """待启用（PENDING）公钥未完成启用流程时拒绝认证。"""
    public_pem, private_pem = _make_keypair()
    pending_key = _key(public_pem)
    pending_key.status = PublicKeyStatus.PENDING
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), pending_key])
    db.execute = AsyncMock(return_value=_execute_result([_rule()]))
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    svc = _service(db, redis)

    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.authenticate(_FakeRequest(_headers(private_pem)), "trace-1")
    assert exc_info.value.code == RUNTIME_AUTH_INVALID_SIGNATURE
    redis.set.assert_not_awaited()


async def test_authenticate_rejects_bad_signature() -> None:
    """签名无效时返回 RUNTIME_AUTH_INVALID_SIGNATURE。"""
    public_pem, private_pem = _make_keypair()
    _, other_private = _make_keypair()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), _key(public_pem)])
    db.execute = AsyncMock(return_value=_execute_result([_rule()]))
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    svc = _service(db, redis)

    headers = _headers(other_private)
    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.authenticate(_FakeRequest(headers), "trace-1")
    assert exc_info.value.code == RUNTIME_AUTH_INVALID_SIGNATURE
    redis.set.assert_not_awaited()


async def test_authenticate_rejects_expired_timestamp() -> None:
    """超出时间窗口的时间戳被拒绝。"""
    public_pem, private_pem = _make_keypair()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), _key(public_pem)])
    db.execute = AsyncMock(return_value=_execute_result([_rule()]))
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    svc = _service(db, redis)

    headers = _headers(private_pem, timestamp=int(time.time()) - 1000)
    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.authenticate(_FakeRequest(headers), "trace-1")
    assert exc_info.value.code == RUNTIME_AUTH_EXPIRED_TIMESTAMP


async def test_authenticate_rejects_replayed_nonce() -> None:
    """Nonce 已存在时判定为重放。"""
    public_pem, private_pem = _make_keypair()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), _key(public_pem)])
    db.execute = AsyncMock(return_value=_execute_result([_rule()]))
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=False)
    svc = _service(db, redis)

    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.authenticate(_FakeRequest(_headers(private_pem)), "trace-1")
    assert exc_info.value.code == RUNTIME_AUTH_REPLAYED_NONCE


async def test_authenticate_rejects_ip_not_allowed() -> None:
    """来源 IP 不在白名单时拒绝。"""
    public_pem, private_pem = _make_keypair()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), _key(public_pem)])
    db.execute = AsyncMock(return_value=_execute_result([_rule()]))
    redis = AsyncMock()
    svc = _service(db, redis)

    request = _FakeRequest(_headers(private_pem), client_ip="8.8.8.8")
    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.authenticate(request, "trace-1")
    assert exc_info.value.code == RUNTIME_AUTH_IP_NOT_ALLOWED


async def test_authenticate_rejects_disabled_system() -> None:
    """系统已停用时拒绝。"""
    system = _system()
    system.status = CallerSystemStatus.DISABLED
    public_pem, private_pem = _make_keypair()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[system, _key(public_pem)])
    redis = AsyncMock()
    svc = _service(db, redis)

    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.authenticate(_FakeRequest(_headers(private_pem)), "trace-1")
    assert exc_info.value.code == RUNTIME_AUTH_INVALID_SYSTEM


async def test_authenticate_denies_when_redis_unavailable() -> None:
    """Redis 不可用时默认拒绝（不降级放行）。"""
    public_pem, private_pem = _make_keypair()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), _key(public_pem)])
    db.execute = AsyncMock(return_value=_execute_result([_rule()]))
    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
    svc = _service(db, redis)

    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.authenticate(_FakeRequest(_headers(private_pem)), "trace-1")
    assert exc_info.value.code == RUNTIME_AUTH_SECURITY_UNAVAILABLE
