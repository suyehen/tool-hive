"""MCP 传输安全配置测试：Host 白名单必须来自后台配置并可用于实际 Host 值。"""

from __future__ import annotations

from mcp.server.transport_security import (
    TransportSecurityMiddleware,
)

from toolhive.mcp.server import (
    DEFAULT_ALLOWED_HOSTS,
    apply_allowed_hosts,
    get_transport_security,
)


def test_allowed_hosts_normalized_with_wildcard_port() -> None:
    """不带端口的配置项要补出 host:* ，否则 Host: 127.0.0.1:8100 会被判非法。"""
    apply_allowed_hosts(["127.0.0.1", "localhost"])
    settings = get_transport_security()

    assert "127.0.0.1" in settings.allowed_hosts
    assert "127.0.0.1:*" in settings.allowed_hosts
    assert "localhost:*" in settings.allowed_hosts

    middleware = TransportSecurityMiddleware(settings)
    assert middleware._validate_host("127.0.0.1:8100") is True
    assert middleware._validate_host("evil.example.com") is False


def test_allowed_hosts_follows_admin_config() -> None:
    """后台配置的白名单必须真正生效（此前被硬编码忽略）。"""
    apply_allowed_hosts(["mcp.example.com"])
    settings = get_transport_security()
    middleware = TransportSecurityMiddleware(settings)

    assert middleware._validate_host("mcp.example.com") is True
    assert middleware._validate_host("mcp.example.com:443") is True
    assert middleware._validate_host("127.0.0.1:8100") is False


def test_allowed_hosts_empty_falls_back_to_loopback() -> None:
    """配置为空时退回回环默认值，避免把 MCP 入口整体锁死。"""
    apply_allowed_hosts([])
    settings = get_transport_security()

    assert set(DEFAULT_ALLOWED_HOSTS).issubset(set(settings.allowed_hosts))

    # 复位为默认值，避免影响同进程其他测试
    apply_allowed_hosts(list(DEFAULT_ALLOWED_HOSTS))
