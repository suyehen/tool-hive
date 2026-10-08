"""基础领域仓储；状态变更使用 CatalogService。"""

from toolhive.adapters.db.repository import Repository
from toolhive.core.domain.models import Principal, Provider, Tool, ToolVersion


class PrincipalRepository(Repository[Principal]):
    model = Principal


class ProviderRepository(Repository[Provider]):
    model = Provider


class ToolRepository(Repository[Tool]):
    model = Tool


class VersionRepository(Repository[ToolVersion]):
    model = ToolVersion
