"""领域合法性错误；协议映射由后续内核/适配器提供。"""


class DomainError(Exception):
    """领域服务错误基类，不携带敏感数据。"""


class InvalidDefinitionError(DomainError):
    """定义、绑定或授权范围不合法。"""


class InvalidTransitionError(DomainError):
    """当前状态不允许该迁移。"""


class ImmutableDefinitionError(DomainError):
    """修改已冻结定义或追加型记录。"""


class InvalidApiKeyError(DomainError):
    """API Key 无效；消息不区分不存在、吊销与过期。"""
