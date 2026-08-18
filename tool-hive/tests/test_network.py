"""网络 IP 工具测试。"""

from __future__ import annotations

from toolhive.core.network import is_loopback, is_trusted_proxy, parse_client_ip


class TestParseClientIp:
    def test_ipv4(self) -> None:
        assert parse_client_ip("192.168.1.1") == "192.168.1.1"

    def test_ipv6(self) -> None:
        assert parse_client_ip("::1") == "::1"

    def test_ipv4_mapped_ipv6(self) -> None:
        assert parse_client_ip("::ffff:192.168.1.1") == "192.168.1.1"

    def test_invalid(self) -> None:
        assert parse_client_ip("not-an-ip") is None
        assert parse_client_ip("") is None


class TestIsLoopback:
    def test_loopback(self) -> None:
        assert is_loopback("127.0.0.1")
        assert is_loopback("::1")

    def test_not_loopback(self) -> None:
        assert not is_loopback("192.168.1.1")


class TestIsTrustedProxy:
    def test_trusted(self) -> None:
        assert is_trusted_proxy("127.0.0.1", ["127.0.0.1/32", "::1/128"])

    def test_untrusted(self) -> None:
        assert not is_trusted_proxy("10.0.0.1", ["127.0.0.1/32"])
