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


class SigningAlgorithm(StrEnum):
    """调用系统请求签名算法（与验签器注册表一一对应）。"""

    RSA_PSS_SHA256 = "RSA-PSS-SHA256"
    ED25519 = "Ed25519"


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


class CatalogObjectStatus(StrEnum):
    """Catalog 配置对象状态（工具 / Provider / 能力包通用）。"""

    ENABLED = "enabled"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class ProviderType(StrEnum):
    """Provider 执行通道类型。"""

    BUILTIN = "builtin"
    HTTP = "http"


class ToolVersionStatus(StrEnum):
    """工具版本状态（唯一走完整审核发布流程的对象）。"""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    DISABLED = "disabled"
    WITHDRAWN = "withdrawn"
    ARCHIVED = "archived"


class RiskLevel(StrEnum):
    """工具风险等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewDecision(StrEnum):
    """审核结论。"""

    APPROVE = "approve"
    REJECT = "reject"


class CatalogHistoryAction(StrEnum):
    """Catalog 发布历史动作。"""

    SUBMIT_REVIEW = "submit_review"
    APPROVE = "approve"
    REJECT = "reject"
    PUBLISH = "publish"
    ENABLE = "enable"
    DISABLE = "disable"
    WITHDRAW = "withdraw"
    ARCHIVE = "archive"
    SET_DEFAULT = "set_default"


class ConfirmationStatus(StrEnum):
    """高风险执行确认状态。"""

    PENDING = "pending"
    CONSUMED = "consumed"
    EXPIRED = "expired"
