"""网络 IP 工具：来源 IP 解析与可信代理校验。"""

from __future__ import annotations

import ipaddress


def parse_client_ip(value: str) -> str | None:
    """解析单个 IP，统一处理 IPv4、IPv6 与 IPv4-mapped IPv6。

    非法格式返回 None。
    """
    raw = value.strip()
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return str(addr)


def is_loopback(host: str) -> bool:
    """判断主机地址是否为回环地址。"""
    addr = parse_client_ip(host)
    if addr is None:
        return False
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def is_trusted_proxy(host: str, trusted_proxies: list[str]) -> bool:
    """判断请求对端是否属于可信代理范围。"""
    addr = parse_client_ip(host)
    if addr is None:
        return False
    ip = ipaddress.ip_address(addr)
    for proxy in trusted_proxies:
        try:
            network = ipaddress.ip_network(proxy.strip(), strict=False)
        except ValueError:
            continue
        if ip.version == network.version and ip in network:
            return True
    return False
