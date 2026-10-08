"""D6：M0 只判断并拒绝需要确认的请求，不实现令牌生命周期。"""

from collections.abc import Iterable

from toolhive.core.domain.models import ToolVersion
from toolhive.core.policy.contracts import GrantPolicy
from toolhive.core.policy.errors import PolicyError


def confirmation_required(version: ToolVersion, grants: Iterable[GrantPolicy] = ()) -> bool:
    return (
        version.side_effect != "read"
        or version.risk == "high"
        or any(grant.constraints.require_confirmation for grant in grants)
    )


def enforce_confirmation(version: ToolVersion, grants: Iterable[GrantPolicy] = ()) -> None:
    if confirmation_required(version, grants):
        raise PolicyError("TH_CONFIRMATION_REQUIRED")
