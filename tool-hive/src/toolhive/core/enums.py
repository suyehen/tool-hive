"""应用状态枚举。

所有状态值统一由代码层定义与校验，数据库层不添加 CHECK；
新增状态值只需修改本文件与对应 Service 的状态流转。
"""

from __future__ import annotations

from enum import StrEnum


class AccountStatus(StrEnum):
    """管理账号状态。"""

    ENABLED = "enabled"
    DISABLED = "disabled"
    LOCKED = "locked"
    OFFBOARDED = "offboarded"


class RoleStatus(StrEnum):
    """后台角色状态。"""

    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class OperationStatus(StrEnum):
    """管理操作项状态。"""

    ACTIVE = "active"
    DEPRECATED = "deprecated"


class CallerSystemStatus(StrEnum):
    """调用系统生命周期状态。"""

    DRAFT = "draft"
    ENABLED = "enabled"
    DISABLED = "disabled"
    REVOKED = "revoked"


class PublicKeyStatus(StrEnum):
    """调用系统公钥状态。"""

    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"
    EXPIRED = "expired"
    REVOKED = "revoked"


class IPRuleStatus(StrEnum):
    """调用系统来源 IP 规则状态。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class ToolScopeType(StrEnum):
    """工具范围类型：能力包或具体工具。"""

    CAPABILITY = "capability"
    TOOL = "tool"


class ToolScopeStatus(StrEnum):
    """工具范围条目状态。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class AuditResult(StrEnum):
    """审计结果。"""

    SUCCESS = "success"
    FAILURE = "failure"


class OutboxStatus(StrEnum):
    """Outbox 事件与投递状态。"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    RETRY = "RETRY"
    SUCCEEDED = "SUCCEEDED"
    DEAD = "DEAD"
