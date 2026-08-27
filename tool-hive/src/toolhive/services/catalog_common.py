"""Catalog 公共校验与工具函数。"""

from __future__ import annotations

import ipaddress
import re

from toolhive.core.exceptions import ValidationError

_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}\.[a-z][a-z0-9-]{0,63}$")
_TOOL_CODE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")
_OBJECT_CODE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,31}$")


def validate_namespace(namespace: str) -> str:
    """校验命名空间格式：点分两级 ``{项目}.{子域}``。"""
    value = (namespace or "").strip()
    if not _NAMESPACE_RE.match(value):
        raise ValidationError(
            "命名空间必须是点分两级小写格式（如 math.basic），"
            "仅允许字母、数字与连字符"
        )
    return value


def validate_tool_code(tool_code: str) -> str:
    """校验工具编码：小写字母开头，命名空间内唯一。"""
    value = (tool_code or "").strip()
    if not _TOOL_CODE_RE.match(value):
        raise ValidationError(
            "工具编码必须是小写字母开头，允许字母、数字、下划线与连字符，最长 128 位"
        )
    return value


def validate_object_code(code: str, label: str) -> str:
    """校验 Provider / 能力包编码：全局唯一，小写字母开头。"""
    value = (code or "").strip()
    if not _OBJECT_CODE_RE.match(value):
        raise ValidationError(
            f"{label}必须是小写字母开头，允许字母、数字、下划线与连字符，最长 128 位"
        )
    return value


def validate_version(version: str) -> str:
    """校验工具版本号（如 ``1.0.0``）。"""
    value = (version or "").strip()
    if not _VERSION_RE.match(value):
        raise ValidationError("版本号格式无效（如 1.0.0）")
    return value


def validate_cidr_list(cidrs: list[str] | None) -> list[str]:
    """校验 CIDR 列表格式并返回规范化结果。"""
    if not cidrs:
        return []
    normalized: list[str] = []
    for item in cidrs:
        value = (item or "").strip()
        if not value:
            raise ValidationError("允许 CIDR 列表不能包含空项")
        try:
            normalized.append(str(ipaddress.ip_network(value, strict=False)))
        except ValueError:
            raise ValidationError(f"无效的 CIDR: {value}")
    return normalized


def validate_http_target_config(config: dict | None) -> dict | None:
    """校验 http 类型 Provider 的目标安全配置。"""
    if not config:
        raise ValidationError("http 类型 Provider 必须提供目标安全配置")
    allowed_domains = config.get("allowed_domains")
    if not isinstance(allowed_domains, list) or not allowed_domains:
        raise ValidationError("allowed_domains 不能为空")
    protocols = config.get("protocols") or ["https"]
    if not isinstance(protocols, list) or any(p != "https" for p in protocols):
        raise ValidationError("一期仅允许 https 协议")
    allowed_ports = config.get("allowed_ports") or []
    if not isinstance(allowed_ports, list) or any(
        not isinstance(p, int) or not (1 <= p <= 65535) for p in allowed_ports
    ):
        raise ValidationError("allowed_ports 必须是 1-65535 的端口号列表")
    path_prefix = config.get("path_prefix")
    if path_prefix is not None and not str(path_prefix).startswith("/"):
        raise ValidationError("path_prefix 必须以 / 开头")
    return {
        "allowed_domains": [str(d) for d in allowed_domains],
        "allowed_ports": [int(p) for p in allowed_ports],
        "path_prefix": str(path_prefix) if path_prefix else None,
        "protocols": ["https"],
        "dns_tls_verification": bool(config.get("dns_tls_verification", True)),
        "allowed_cidrs": validate_cidr_list(config.get("allowed_cidrs")),
    }
