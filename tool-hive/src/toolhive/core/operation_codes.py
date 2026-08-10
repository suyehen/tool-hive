"""管理操作项枚举定义。

所有管理操作码在此集中声明。新增操作码需同时：
1. 在此添加枚举成员
2. 在对应 API 路由中使用 Depends(require_operation(...))
3. 前端菜单/按钮关联
4. 启动时自动同步到数据库
"""

from __future__ import annotations

from enum import StrEnum


class OperationCode(StrEnum):
    """管理操作项枚举。新增操作码默认只对超级管理员生效。"""

    # ── 管理账号 ──
    ADMIN_ACCOUNT_VIEW = "admin_account:view"
    ADMIN_ACCOUNT_CREATE = "admin_account:create"
    ADMIN_ACCOUNT_MANAGE = "admin_account:manage"

    # ── 后台角色 ──
    ROLE_VIEW = "role:view"
    ROLE_CREATE = "role:create"
    ROLE_EDIT = "role:edit"
    ROLE_MANAGE = "role:manage"
    ROLE_ASSIGN = "role:assign"

    # ── 调用系统 ──
    CALLER_SYSTEM_VIEW = "caller_system:view"
    CALLER_SYSTEM_CREATE = "caller_system:create"
    CALLER_SYSTEM_EDIT = "caller_system:edit"
    CALLER_SYSTEM_MANAGE = "caller_system:manage"
    CALLER_SYSTEM_ALLOW_ANY_IP = "caller_system:allow_any_ip"

    # ── 工具 ──
    TOOL_VIEW = "tool:view"
    TOOL_CREATE = "tool:create"
    TOOL_EDIT = "tool:edit"
    TOOL_REVIEW = "tool:review"
    TOOL_PUBLISH = "tool:publish"
    TOOL_MANAGE = "tool:manage"

    # ── Provider ──
    PROVIDER_VIEW = "provider:view"
    PROVIDER_CREATE = "provider:create"
    PROVIDER_EDIT = "provider:edit"
    PROVIDER_MANAGE = "provider:manage"


# 超管角色名（内置，不可删除/改名）
SUPER_ADMIN_ROLE_NAME = "super_admin"
