"""FastAPI 依赖：配置分区注入。

业务模块（路由/服务）通过依赖获取所需配置分区，不依赖完整全局 Settings。
"""

from __future__ import annotations

from toolhive.config import AdminSecuritySettings, settings


def get_admin_security() -> AdminSecuritySettings:
    """提供管理安全配置分区。"""
    return settings.admin_security
