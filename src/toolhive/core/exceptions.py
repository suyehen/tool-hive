"""自定义异常体系。"""

from __future__ import annotations


class ToolHiveError(Exception):
    """所有 ToolHive 异常的基类。"""


# ── 工具异常 ──
class ToolNotFoundError(ToolHiveError):
    """未找到指定工具或版本。"""


class ToolNotAvailableError(ToolHiveError):
    """工具存在但当前不可发现/不可执行。"""


class ToolVersionMismatchError(ToolHiveError):
    """版本状态不允许操作。"""


# ── 策略异常 ──
class PolicyDeniedError(ToolHiveError):
    """ToolPolicy 拒绝请求。"""

    def __init__(self, reason_code: str, message: str = ""):
        self.reason_code = reason_code
        super().__init__(message or reason_code)


class ConfirmationRequiredError(ToolHiveError):
    """高风险操作需确认。"""

    def __init__(self, confirmation_token: str, message: str = ""):
        self.confirmation_token = confirmation_token
        super().__init__(message)


# ── Provider 异常 ──
class ProviderUnavailableError(ToolHiveError):
    """Provider 健康检查失败或不可达。"""


class ProviderExecutionError(ToolHiveError):
    """Provider 执行失败。"""


# ── 校验异常 ──
class SchemaValidationError(ToolHiveError):
    """参数 JSON Schema 校验失败。"""


# ── 认证异常 ──
class AuthenticationError(ToolHiveError):
    """管理面认证失败。"""


class RuntimeAuthError(ToolHiveError):
    """运行面服务间认证失败。"""
