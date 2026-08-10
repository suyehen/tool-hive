"""自定义异常体系。"""

from __future__ import annotations


class ToolHiveError(Exception):
    """所有 ToolHive 异常的基类。"""


class AuthenticationError(ToolHiveError):
    """认证失败。管理侧登录失败 / 运行侧签名验证失败。"""


class PermissionDeniedError(ToolHiveError):
    """缺少管理操作项 / 工具调用范围不足。"""


class ValidationError(ToolHiveError):
    """业务规则校验失败（如不能禁用最后一个超管、参数不符合 Schema）。"""


class NotFoundError(ToolHiveError):
    """资源不存在。"""


class ConflictError(ToolHiveError):
    """状态冲突（如重复启用、用户名已被占用）。"""


class ServiceUnavailableError(ToolHiveError):
    """Redis / DB 等基础设施不可用。"""
