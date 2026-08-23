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
    CALLER_SYSTEM_POLICY = "caller_system:policy"

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

    # ── 系统任务（Outbox） ──
    SYSTEM_TASK_VIEW = "system_task:view"
    SYSTEM_TASK_RETRY = "system_task:retry"


# 超管角色名（内置，不可删除/改名）
SUPER_ADMIN_ROLE_NAME = "super_admin"


# 操作码元数据（唯一权威，启动同步时强制刷新 management_operation 的对应字段）
# 每个操作码包含：category（分类）、display_name（中文名）、description（说明）、
# sort_order（分类内排序）
OPERATION_META: dict[str, dict[str, str | int | None]] = {
    # ── 管理账号 ──
    "admin_account:view": {
        "category": "account",
        "display_name": "查看管理账号",
        "description": "查看管理账号列表与详情",
        "sort_order": 10,
    },
    "admin_account:create": {
        "category": "account",
        "display_name": "创建管理账号",
        "description": "创建管理账号并生成临时密码",
        "sort_order": 20,
    },
    "admin_account:manage": {
        "category": "account",
        "display_name": "管理管理账号",
        "description": "启用/禁用/解锁/重置密码/强制下线/离职等账号管理操作",
        "sort_order": 30,
    },
    # ── 后台角色 ──
    "role:view": {
        "category": "role",
        "display_name": "查看后台角色",
        "description": "查看角色列表、操作权限与分配情况",
        "sort_order": 10,
    },
    "role:create": {
        "category": "role",
        "display_name": "创建后台角色",
        "description": "创建新的后台角色",
        "sort_order": 20,
    },
    "role:edit": {
        "category": "role",
        "display_name": "编辑后台角色",
        "description": "修改角色资料与操作权限",
        "sort_order": 30,
    },
    "role:manage": {
        "category": "role",
        "display_name": "管理后台角色",
        "description": "启用/停用/归档角色",
        "sort_order": 40,
    },
    "role:assign": {
        "category": "role",
        "display_name": "分配角色",
        "description": "给账号分配/移除角色",
        "sort_order": 50,
    },
    # ── 调用系统 ──
    "caller_system:view": {
        "category": "caller_system",
        "display_name": "查看调用系统",
        "description": "查看调用系统列表与详情",
        "sort_order": 10,
    },
    "caller_system:create": {
        "category": "caller_system",
        "display_name": "登记调用系统",
        "description": "登记新的调用系统",
        "sort_order": 20,
    },
    "caller_system:edit": {
        "category": "caller_system",
        "display_name": "编辑调用系统",
        "description": "修改调用系统资料",
        "sort_order": 30,
    },
    "caller_system:manage": {
        "category": "caller_system",
        "display_name": "管理调用系统",
        "description": "启用/停用/恢复/注销调用系统及公钥/IP 规则管理",
        "sort_order": 40,
    },
    "caller_system:allow_any_ip": {
        "category": "caller_system",
        "display_name": "允许通配 IP 规则",
        "description": "高风险：允许为调用系统配置通配（*）来源 IP 规则",
        "sort_order": 50,
    },
    "caller_system:policy": {
        "category": "caller_system",
        "display_name": "配置运行策略",
        "description": "配置调用系统运行策略、工具范围与紧急禁用",
        "sort_order": 60,
    },
    # ── 工具 ──
    "tool:view": {
        "category": "tool",
        "display_name": "查看工具",
        "description": "查看工具目录与版本",
        "sort_order": 10,
    },
    "tool:create": {
        "category": "tool",
        "display_name": "创建工具",
        "description": "创建工具定义",
        "sort_order": 20,
    },
    "tool:edit": {
        "category": "tool",
        "display_name": "编辑工具",
        "description": "修改工具定义与版本",
        "sort_order": 30,
    },
    "tool:review": {
        "category": "tool",
        "display_name": "审核工具",
        "description": "审核工具发布申请",
        "sort_order": 40,
    },
    "tool:publish": {
        "category": "tool",
        "display_name": "发布工具",
        "description": "发布工具版本",
        "sort_order": 50,
    },
    "tool:manage": {
        "category": "tool",
        "display_name": "管理工具",
        "description": "启停/归档工具",
        "sort_order": 60,
    },
    # ── Provider ──
    "provider:view": {
        "category": "provider",
        "display_name": "查看 Provider",
        "description": "查看 Provider 定义与配置",
        "sort_order": 10,
    },
    "provider:create": {
        "category": "provider",
        "display_name": "创建 Provider",
        "description": "创建 Provider",
        "sort_order": 20,
    },
    "provider:edit": {
        "category": "provider",
        "display_name": "编辑 Provider",
        "description": "修改 Provider 定义",
        "sort_order": 30,
    },
    "provider:manage": {
        "category": "provider",
        "display_name": "管理 Provider",
        "description": "启停/归档 Provider",
        "sort_order": 40,
    },
    # ── 系统任务 ──
    "system_task:view": {
        "category": "system_task",
        "display_name": "查看系统任务",
        "description": "查看 Outbox 投递任务列表",
        "sort_order": 10,
    },
    "system_task:retry": {
        "category": "system_task",
        "display_name": "重试系统任务",
        "description": "人工重投失败的投递任务",
        "sort_order": 20,
    },
}
