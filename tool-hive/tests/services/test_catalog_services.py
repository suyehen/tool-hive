"""Catalog 服务层测试：Provider/能力包/工具/版本状态机与事件发布。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from toolhive.core.enums import (
    CatalogObjectStatus,
    ToolVersionStatus,
)
from toolhive.core.exceptions import ConflictError, ValidationError
from toolhive.models.catalog_capability_pack import CatalogCapabilityPack
from toolhive.models.catalog_capability_pack_system import (
    CatalogCapabilityPackSystem,
)
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.models.catalog_publish_history import CatalogPublishHistory
from toolhive.models.catalog_review_record import CatalogReviewRecord
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.models.outbox_delivery import OutboxDelivery
from toolhive.models.outbox_event import OutboxEvent
from toolhive.services.audit_service import set_audit_actor
from toolhive.services.catalog_capability_service import CatalogCapabilityService
from toolhive.services.catalog_provider_service import CatalogProviderService
from toolhive.services.catalog_tool_service import CatalogToolService
from toolhive.services.catalog_version_service import CatalogVersionService


@pytest.fixture(autouse=True)
def _reset_actor() -> None:
    """每个测试前后清空当前操作人。"""
    set_audit_actor(None, None)
    yield
    set_audit_actor(None, None)


def _execute_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _fake_get(mapping: dict[type, object]):
    """构造 db.get 的 side_effect：按模型类型返回预置对象。"""

    async def fake_get(model_cls, pk):
        return mapping.get(model_cls)

    return fake_get


def _http_config() -> dict:
    return {
        "allowed_domains": ["api.example.com"],
        "allowed_ports": [443],
        "protocols": ["https"],
        "dns_tls_verification": True,
        "allowed_cidrs": [],
    }


# ═════════════════════════════════════════════════════════════
# Provider
# ═════════════════════════════════════════════════════════════


async def test_create_http_provider_validates_config() -> None:
    """http 类型 Provider 必须提供合法目标安全配置。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    svc = CatalogProviderService(db)
    set_audit_actor("acc-1", "operator")

    with pytest.raises(ValidationError):
        await svc.create_provider(
            provider_code="http1",
            name="外部服务",
            provider_type="http",
            target_security_config=None,
        )
    with pytest.raises(ValidationError):
        await svc.create_provider(
            provider_code="http1",
            name="外部服务",
            provider_type="http",
            target_security_config={"allowed_domains": []},
        )


async def test_create_provider_duplicate_code() -> None:
    """Provider 编码重复时拒绝创建。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=MagicMock())
    svc = CatalogProviderService(db)
    with pytest.raises(ConflictError):
        await svc.create_provider(
            provider_code="dup",
            name="重复",
            provider_type="builtin",
        )


async def test_archive_provider_blocked_when_bound() -> None:
    """存在未归档版本绑定时拒绝归档 Provider。"""
    provider = CatalogProvider(
        provider_code="p1", name="P1", provider_type="builtin",
        status=CatalogObjectStatus.ENABLED,
    )
    db = AsyncMock()
    db.get = AsyncMock(side_effect=_fake_get({CatalogProvider: provider}))
    result = MagicMock()
    result.first.return_value = (1,)
    db.execute = AsyncMock(return_value=result)
    svc = CatalogProviderService(db)

    with pytest.raises(ConflictError):
        await svc.set_status(provider.id, CatalogObjectStatus.ARCHIVED)


# ═════════════════════════════════════════════════════════════
# 工具
# ═════════════════════════════════════════════════════════════


async def test_create_tool_validates_namespace_and_code() -> None:
    """命名空间与工具编码格式非法时拒绝创建。"""
    db = AsyncMock()
    svc = CatalogToolService(db)

    with pytest.raises(ValidationError):
        await svc.create_tool(
            namespace="math", tool_code="calculator", name="计算器",
        )
    with pytest.raises(ValidationError):
        await svc.create_tool(
            namespace="Math.Basic", tool_code="calculator", name="计算器",
        )
    with pytest.raises(ValidationError):
        await svc.create_tool(
            namespace="math.basic", tool_code="Calculator", name="计算器",
        )


async def test_create_tool_duplicate_rejected() -> None:
    """命名空间 + 工具编码重复时拒绝创建。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=MagicMock())
    svc = CatalogToolService(db)

    with pytest.raises(ConflictError):
        await svc.create_tool(
            namespace="math.basic",
            tool_code="calculator",
            name="计算器",
        )


async def test_archive_tool_blocked_with_active_versions() -> None:
    """存在非草稿/驳回/归档版本时拒绝归档工具。"""
    tool = CatalogTool(
        namespace="math.basic", tool_code="calculator", name="计算器",
        status=CatalogObjectStatus.ENABLED,
    )
    db = AsyncMock()
    db.get = AsyncMock(side_effect=_fake_get({CatalogTool: tool}))
    result = MagicMock()
    result.first.return_value = (1,)
    db.execute = AsyncMock(return_value=result)
    svc = CatalogToolService(db)

    with pytest.raises(ConflictError):
        await svc.set_status(tool.id, CatalogObjectStatus.ARCHIVED)


# ═════════════════════════════════════════════════════════════
# 能力包
# ═════════════════════════════════════════════════════════════


async def test_replace_pack_tools_rejects_missing_and_archived() -> None:
    """能力包工具关联拒绝缺失或已归档的工具。"""
    db = AsyncMock()
    db.get = AsyncMock(
        side_effect=_fake_get({CatalogCapabilityPack: MagicMock()})
    )
    db.execute = AsyncMock(return_value=_execute_result([]))
    svc = CatalogCapabilityService(db)

    with pytest.raises(ValidationError):
        await svc.replace_pack_tools("pack-1", ["missing-id"])


async def test_replace_pack_systems_writes_batch() -> None:
    """能力包调用系统授权全量替换时批量写入关联。"""
    db = AsyncMock()
    db.get = AsyncMock(
        side_effect=_fake_get({CatalogCapabilityPack: MagicMock()})
    )
    system = MagicMock()
    system.system_id = "sys_1"
    db.execute = AsyncMock(return_value=_execute_result([system]))
    db.add = MagicMock()
    svc = CatalogCapabilityService(db)
    set_audit_actor("acc-1", "operator")

    result = await svc.replace_pack_systems("pack-1", ["sys_1"])
    assert len(result) == 1
    added = [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], CatalogCapabilityPackSystem)
    ]
    assert len(added) == 0  # 批量 insert 不经过 db.add


# ═════════════════════════════════════════════════════════════
# 工具版本状态机
# ═════════════════════════════════════════════════════════════


def _tool() -> CatalogTool:
    return CatalogTool(
        id="tool-1",
        namespace="math.basic",
        tool_code="calculator",
        name="计算器",
        status=CatalogObjectStatus.ENABLED,
        row_version=0,
    )


def _provider() -> CatalogProvider:
    return CatalogProvider(
        id="prov-1",
        provider_code="builtin-math",
        name="内置计算",
        provider_type="builtin",
        status=CatalogObjectStatus.ENABLED,
        row_version=0,
    )


def _version(tool_id: str = "tool-1", status: str = ToolVersionStatus.DRAFT) -> CatalogToolVersion:
    return CatalogToolVersion(
        id="ver-1",
        tool_id=tool_id,
        version="1.0.0",
        status=status,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        row_version=0,
    )


def _binding() -> CatalogExecutionBinding:
    return CatalogExecutionBinding(
        id="binding-1",
        version_id="ver-1",
        provider_id="prov-1",
        method="COMPUTE",
        path_template="builtin://math/add",
        row_version=0,
    )


async def test_create_version_requires_binding_provider_valid() -> None:
    """创建版本时校验执行绑定：builtin 必须用 COMPUTE + builtin:// 路径。"""
    tool = _tool()
    db = AsyncMock()
    db.get = AsyncMock(side_effect=_fake_get({CatalogTool: tool}))
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = CatalogVersionService(db)
    set_audit_actor("acc-1", "operator")

    with pytest.raises(ValidationError):
        await svc.create_version(
            "tool-1",
            "1.0.0",
            binding={
                "provider_id": "prov-1",
                "method": "GET",
                "path_template": "/x",
            },
        )


async def test_version_state_machine_full_flow() -> None:
    """完整状态机：草稿→送审→通过→发布→停用→启用→撤回→归档。"""
    tool = _tool()
    provider = _provider()
    version = _version()
    binding = _binding()
    db = AsyncMock()
    db.get = AsyncMock(
        side_effect=_fake_get(
            {CatalogTool: tool, CatalogProvider: provider, CatalogToolVersion: version}
        )
    )
    db.scalar = AsyncMock(return_value=binding)
    db.add = MagicMock()
    svc = CatalogVersionService(db)
    set_audit_actor("acc-1", "operator")

    # 送审
    await svc.submit_review("ver-1")
    assert version.status == ToolVersionStatus.PENDING_REVIEW
    # 审核通过
    await svc.approve("ver-1", "通过")
    assert version.status == ToolVersionStatus.APPROVED
    # 发布（首个发布必须默认）
    with pytest.raises(ValidationError):
        await svc.publish("ver-1", set_default=False)
    await svc.publish("ver-1", set_default=True)
    assert version.status == ToolVersionStatus.PUBLISHED
    assert tool.default_version_id == "ver-1"
    # 停用 → 重新启用
    await svc.disable("ver-1", "临时下线")
    assert version.status == ToolVersionStatus.DISABLED
    await svc.enable("ver-1")
    assert version.status == ToolVersionStatus.PUBLISHED
    # 撤回 → 归档
    await svc.withdraw("ver-1", "有问题")
    assert version.status == ToolVersionStatus.WITHDRAWN
    assert tool.default_version_id is None
    await svc.archive("ver-1")
    assert version.status == ToolVersionStatus.ARCHIVED
    # 归档后不可再变更
    with pytest.raises(ConflictError):
        await svc.archive("ver-1")


async def test_version_reject_and_resubmit() -> None:
    """驳回后可重新送审。"""
    tool = _tool()
    version = _version()
    binding = _binding()
    db = AsyncMock()
    db.get = AsyncMock(
        side_effect=_fake_get({CatalogTool: tool, CatalogToolVersion: version})
    )
    db.scalar = AsyncMock(return_value=binding)
    db.add = MagicMock()
    svc = CatalogVersionService(db)
    set_audit_actor("acc-1", "operator")

    await svc.submit_review("ver-1")
    await svc.reject("ver-1", "Schema 不完整")
    assert version.status == ToolVersionStatus.REJECTED
    assert version.review_comment == "Schema 不完整"
    await svc.submit_review("ver-1")
    assert version.status == ToolVersionStatus.PENDING_REVIEW


async def test_version_update_only_draft_or_rejected() -> None:
    """已送审 / 已发布版本不可编辑。"""
    version = _version(status=ToolVersionStatus.PUBLISHED)
    db = AsyncMock()
    db.get = AsyncMock(
        side_effect=_fake_get({CatalogToolVersion: version})
    )
    svc = CatalogVersionService(db)

    with pytest.raises(ConflictError):
        await svc.update_version("ver-1", release_note="不允许")


async def test_version_events_emitted_on_create() -> None:
    """创建版本时写入 Outbox 索引事件与 chroma 投递。"""
    tool = _tool()
    provider = _provider()
    db = AsyncMock()
    db.get = AsyncMock(
        side_effect=_fake_get({CatalogTool: tool, CatalogProvider: provider})
    )
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = CatalogVersionService(db)
    set_audit_actor("acc-1", "operator")

    await svc.create_version(
        "tool-1",
        "1.0.0",
        binding={
            "provider_id": "prov-1",
            "method": "COMPUTE",
            "path_template": "builtin://math/add",
        },
    )
    added = [call.args[0] for call in db.add.call_args_list]
    assert any(isinstance(item, OutboxEvent) for item in added)
    assert any(isinstance(item, OutboxDelivery) for item in added)
    assert any(isinstance(item, CatalogExecutionBinding) for item in added)


async def test_history_and_review_records_written() -> None:
    """审核与发布动作写入历史与审核记录。"""
    tool = _tool()
    version = _version()
    binding = _binding()
    db = AsyncMock()
    db.get = AsyncMock(
        side_effect=_fake_get({CatalogTool: tool, CatalogToolVersion: version})
    )
    db.scalar = AsyncMock(return_value=binding)
    db.add = MagicMock()
    svc = CatalogVersionService(db)
    set_audit_actor("acc-1", "operator")

    await svc.submit_review("ver-1")
    await svc.approve("ver-1")
    await svc.publish("ver-1", set_default=True)
    added = [call.args[0] for call in db.add.call_args_list]
    assert any(
        isinstance(item, CatalogReviewRecord)
        and item.action == "submit_review"
        for item in added
    )
    assert any(
        isinstance(item, CatalogReviewRecord) and item.action == "approve"
        for item in added
    )
    assert any(
        isinstance(item, CatalogPublishHistory) and item.action == "publish"
        for item in added
    )
