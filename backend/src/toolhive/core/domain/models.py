"""Import every domain table before using Base.metadata."""

from .api_key import ApiKey
from .binding import ExecutionBinding
from .channel import ToolChannel
from .credential import Credential
from .events import AuditLog, Invocation, OutboxEvent, ReviewRecord, SearchEvent
from .grant import Grant
from .index import IndexMeta, ToolEmbedding
from .principal import Principal
from .provider import Provider
from .tool import Tool
from .version import ToolVersion

__all__ = [
    "ApiKey",
    "AuditLog",
    "Credential",
    "ExecutionBinding",
    "Grant",
    "IndexMeta",
    "Invocation",
    "OutboxEvent",
    "Principal",
    "Provider",
    "ReviewRecord",
    "SearchEvent",
    "Tool",
    "ToolChannel",
    "ToolEmbedding",
    "ToolVersion",
]
