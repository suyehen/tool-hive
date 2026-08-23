"""后台角色与操作权限服务。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import AccountStatus, OperationStatus, RoleStatus
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import (
    SUPER_ADMIN_ROLE_NAME,
    OperationCode,
)
from toolhive.infrastructure.transactions import transactional
from toolhive.models.account_role import AccountRole
from toolhive.models.management_account import ManagementAccount
from toolhive.models.management_operation import ManagementOperation
from toolhive.models.management_role import ManagementRole
from toolhive.models.management_role_operation import ManagementRoleOperation
from toolhive.services.audit_service import AuditService, get_current_operator_id

logger = logging.getLogger(__name__)


class RoleService:
    """后台角色与权限判定。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ═════════════════════════════════════════════════════════════
    # 角色 CRUD
    # ═════════════════════════════════════════════════════════════

    async def list_roles(
        self, offset: int = 0, limit: int = 50,
    ) -> tuple[list[ManagementRole], int]:
        result = await self.db.execute(
            select(ManagementRole)
            .order_by(ManagementRole.create_time.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list(result.scalars().all())
        total = await self.db.scalar(
            select(func.count()).select_from(ManagementRole)
        )
        return items, total or 0

    async def get_role(self, role_id: str) -> ManagementRole:
        role = await self.db.get(ManagementRole, role_id)
        if role is None:
            raise NotFoundError(f"角色不存在: {role_id}")
        return role

    def _ensure_role_mutable(self, role: ManagementRole) -> None:
        """归档角色为终态，禁止任何修改操作。"""
        if role.status == RoleStatus.ARCHIVED:
            raise ValidationError("已归档角色不可修改")

    @transactional()
    async def create_role(
        self, name: str, description: str | None = None,
    ) -> ManagementRole:
        if name == SUPER_ADMIN_ROLE_NAME:
            raise ValidationError("内置超级管理员角色不可创建")
        existing = await self.db.scalar(
            select(ManagementRole).where(ManagementRole.name == name)
        )
        if existing:
            raise ConflictError(f"角色名 '{name}' 已被使用")

        # 创建角色：显式写入创建时间与当前操作人 ID
        role = ManagementRole(
            name=name,
            description=description,
            is_super_admin=False,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        self.db.add(role)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="role.create",
            object_type="role",
            object_id=role.id,
            after_summary={"name": name, "is_super_admin": role.is_super_admin},
        )
        return role

    @transactional()
    async def update_role(
        self,
        role_id: str,
        name: str | None = None,
        description: str | None = None,
        expected_row_version: int | None = None,
    ) -> ManagementRole:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            raise ValidationError("不能修改超级管理员角色")
        self._ensure_role_mutable(role)
        if (
            expected_row_version is not None
            and role.row_version != expected_row_version
        ):
            raise ConflictError("数据已被他人修改，请刷新后重试")
        if name and name == SUPER_ADMIN_ROLE_NAME:
            raise ValidationError("内置超级管理员角色名不可使用")

        before = {"name": role.name, "description": role.description}
        if name and name != role.name:
            existing = await self.db.scalar(
                select(ManagementRole).where(ManagementRole.name == name)
            )
            if existing:
                raise ConflictError(f"角色名 '{name}' 已被使用")
            role.name = name

        if description is not None:
            role.description = description

        # 修改角色：记录修改时间与当前操作人
        role.update_time = datetime.now(UTC)
        role.update_by = get_current_operator_id()
        role.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="role.update",
            object_type="role",
            object_id=role.id,
            before_summary=before,
            after_summary={"name": role.name, "description": role.description},
        )
        return role

    @transactional()
    async def update_role_status(
        self, role_id: str, status: str,
    ) -> ManagementRole:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            raise ValidationError("不能修改超级管理员角色状态")
        if role.status == RoleStatus.ARCHIVED:
            raise ValidationError("已归档角色状态不可变更")
        if status not in tuple(RoleStatus):
            raise ValidationError(f"无效状态: {status}")
        role.status = RoleStatus(status)
        # 修改角色状态：记录修改时间与当前操作人
        role.update_time = datetime.now(UTC)
        role.update_by = get_current_operator_id()
        role.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="role.status",
            object_type="role",
            object_id=role.id,
            after_summary={"status": role.status},
        )
        return role

    # ═════════════════════════════════════════════════════════════
    # 操作项分配
    # ═════════════════════════════════════════════════════════════

    async def get_role_operations(self, role_id: str) -> list[ManagementOperation]:
        await self.get_role(role_id)
        result = await self.db.execute(
            select(ManagementOperation)
            .join(
                ManagementRoleOperation,
                ManagementRoleOperation.operation_code
                == ManagementOperation.operation_code,
            )
            .where(ManagementRoleOperation.role_id == role_id)
            .where(ManagementOperation.status == OperationStatus.ACTIVE)
        )
        return list(result.scalars().all())

    @transactional()
    async def assign_operations(
        self, role_id: str, operation_codes: list[str],
    ) -> None:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            raise ValidationError("超级管理员自动拥有全部操作项，无需分配")
        self._ensure_role_mutable(role)

        for code in operation_codes:
            existing = await self.db.scalar(
                select(ManagementRoleOperation).where(
                    ManagementRoleOperation.role_id == role_id,
                    ManagementRoleOperation.operation_code == code,
                )
            )
            if not existing:
                # 分配操作项：显式写入创建时间与当前操作人 ID
                op = ManagementRoleOperation(
                    role_id=role_id,
                    operation_code=code,
                    create_time=datetime.now(UTC),
                    create_by=get_current_operator_id(),
                )
                self.db.add(op)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="role.operations.assign",
            object_type="role",
            object_id=role_id,
            after_summary={"operation_codes": operation_codes},
        )

    @transactional()
    async def remove_operations(
        self, role_id: str, operation_codes: list[str],
    ) -> None:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            raise ValidationError("不能移除超级管理员的任何操作项")
        self._ensure_role_mutable(role)

        for code in operation_codes:
            existing = await self.db.scalar(
                select(ManagementRoleOperation).where(
                    ManagementRoleOperation.role_id == role_id,
                    ManagementRoleOperation.operation_code == code,
                )
            )
            if existing:
                await self.db.delete(existing)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="role.operations.remove",
            object_type="role",
            object_id=role_id,
            after_summary={"operation_codes": operation_codes},
        )

    # ═════════════════════════════════════════════════════════════
    # 账号 — 角色关联
    # ═════════════════════════════════════════════════════════════

    async def get_account_roles(self, account_id: str) -> list[ManagementRole]:
        result = await self.db.execute(
            select(ManagementRole)
            .join(AccountRole, AccountRole.role_id == ManagementRole.id)
            .where(AccountRole.account_id == account_id)
            .where(ManagementRole.status == RoleStatus.ACTIVE)
        )
        return list(result.scalars().all())

    async def get_role_accounts(self, role_id: str) -> list[ManagementAccount]:
        """查询分配了指定角色的账号列表（先确认角色存在）。"""
        await self.get_role(role_id)
        result = await self.db.execute(
            select(ManagementAccount)
            .join(AccountRole, AccountRole.account_id == ManagementAccount.id)
            .where(AccountRole.role_id == role_id)
            .order_by(ManagementAccount.create_time.desc())
        )
        return list(result.scalars().all())

    @transactional()
    async def assign_role_to_account(
        self, account_id: str, role_id: str, operator_id: str,
    ) -> None:
        role = await self.get_role(role_id)
        self._ensure_role_mutable(role)
        if role.is_super_admin:
            # 只有超管可以授予超管角色
            operator_roles = await self.get_account_roles(operator_id)
            if not any(r.is_super_admin for r in operator_roles):
                raise ValidationError("只有超级管理员可以授予超级管理员角色")

        existing = await self.db.scalar(
            select(AccountRole).where(
                AccountRole.account_id == account_id,
                AccountRole.role_id == role_id,
            )
        )
        if existing:
            raise ConflictError("该账号已拥有此角色")

        # 分配角色：显式写入创建时间与执行操作人 ID
        acct_role = AccountRole(
            account_id=account_id,
            role_id=role_id,
            create_time=datetime.now(UTC),
            create_by=operator_id,
        )
        self.db.add(acct_role)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="account_role.assign",
            object_type="account",
            object_id=account_id,
            actor_account_id=operator_id,
            after_summary={"role_id": role_id},
        )

    @transactional()
    async def remove_role_from_account(
        self, account_id: str, role_id: str, operator_id: str,
    ) -> None:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            operator_roles = await self.get_account_roles(operator_id)
            if not any(r.is_super_admin for r in operator_roles):
                raise ValidationError("只有超级管理员可以移除超级管理员角色")

            # 不允许移除最后一个超管的超管角色
            super_admin_role_ids = await self._get_super_admin_role_ids()
            all_super_admin_accounts = set()
            for sa_role_id in super_admin_role_ids:
                result = await self.db.execute(
                    select(AccountRole.account_id).where(
                        AccountRole.role_id == sa_role_id,
                    )
                )
                all_super_admin_accounts.update(r[0] for r in result)
            if len(all_super_admin_accounts) <= 1 and account_id in all_super_admin_accounts:
                raise ValidationError("不能移除最后一个超级管理员的超级管理员角色")

        ar = await self.db.scalar(
            select(AccountRole).where(
                AccountRole.account_id == account_id,
                AccountRole.role_id == role_id,
            )
        )
        if ar:
            await self.db.delete(ar)
            await self.db.flush()
            AuditService(self.db).add_record(
                action="account_role.remove",
                object_type="account",
                object_id=account_id,
                actor_account_id=operator_id,
                after_summary={"role_id": role_id},
            )

    # ═════════════════════════════════════════════════════════════
    # 权限判定
    # ═════════════════════════════════════════════════════════════

    async def get_effective_operations(
        self, account_id: str,
    ) -> set[OperationCode]:
        """计算账号的有效管理操作项（所有角色所含操作码的并集）。"""
        roles = await self.get_account_roles(account_id)

        # 超管拥有全部有效操作项
        if any(r.is_super_admin for r in roles):
            result = await self.db.execute(
                select(ManagementOperation.operation_code).where(
                    ManagementOperation.status == OperationStatus.ACTIVE
                )
            )
            return {OperationCode(r[0]) for r in result}

        # 普通角色：收集所有操作码
        ops: set[OperationCode] = set()
        for role in roles:
            result = await self.db.execute(
                select(ManagementRoleOperation.operation_code).where(
                    ManagementRoleOperation.role_id == role.id,
                )
            )
            for row in result:
                try:
                    ops.add(OperationCode(row[0]))
                except ValueError:
                    logger.warning("无效操作码 in DB: %s", row[0])

        return ops

    async def check_operation(
        self, account_id: str, required: OperationCode,
    ) -> bool:
        return required in await self.get_effective_operations(account_id)

    async def is_super_admin_account(self, account_id: str) -> bool:
        """账号是否持有 active 的超管角色。"""
        result = await self.db.execute(
            select(AccountRole.id)
            .join(ManagementRole, AccountRole.role_id == ManagementRole.id)
            .where(AccountRole.account_id == account_id)
            .where(ManagementRole.is_super_admin.is_(True))
            .where(ManagementRole.status == RoleStatus.ACTIVE)
            .limit(1)
        )
        return result.first() is not None

    async def count_enabled_super_admins(self) -> int:
        """统计启用状态且持有 active 超管角色的账号数。"""
        count = await self.db.scalar(
            select(func.count(func.distinct(AccountRole.account_id)))
            .join(ManagementRole, AccountRole.role_id == ManagementRole.id)
            .join(ManagementAccount, ManagementAccount.id == AccountRole.account_id)
            .where(ManagementRole.is_super_admin.is_(True))
            .where(ManagementRole.status == RoleStatus.ACTIVE)
            .where(ManagementAccount.status == AccountStatus.ENABLED)
        )
        return count or 0

    # ═════════════════════════════════════════════════════════════
    # 启动同步
    # ═════════════════════════════════════════════════════════════

    @transactional()
    async def sync_operation_codes(self) -> None:
        """启动时同步操作码到数据库（幂等）。"""
        all_codes = set(OperationCode)

        # 列出数据库中所有现有操作码
        result = await self.db.execute(select(ManagementOperation))
        db_codes: dict[str, ManagementOperation] = {
            r.operation_code: r for r in result.scalars().all()
        }

        # 新增操作码 → 插入
        for code in all_codes:
            if code not in db_codes:
                op = ManagementOperation(
                    operation_code=str(code),
                    display_name=str(code),  # 默认用 operation_code 作显示名
                    status=OperationStatus.ACTIVE,
                )
                self.db.add(op)
                logger.info("新增操作码: %s", code)

            # 授予超管
            super_admin_roles = await self._get_super_admin_role_ids()
            for sa_role_id in super_admin_roles:
                existing = await self.db.scalar(
                    select(ManagementRoleOperation).where(
                        ManagementRoleOperation.role_id == sa_role_id,
                        ManagementRoleOperation.operation_code == code,
                    )
                )
                if not existing:
                    self.db.add(ManagementRoleOperation(
                        role_id=sa_role_id,
                        operation_code=code,
                    ))

        # 废弃的操作码 → 标记（不删除）
        db_code_set = set(db_codes.keys())
        for code in db_code_set - all_codes:
            op = db_codes[code]
            if op.status != OperationStatus.DEPRECATED:
                op.status = OperationStatus.DEPRECATED
                self.db.add(op)
                logger.info("废弃操作码: %s", code)

        await self.db.flush()

    @transactional()
    async def ensure_super_admin_role(self) -> ManagementRole:
        """确保超级管理员角色存在（首次启动时创建）。"""
        role = await self.db.scalar(
            select(ManagementRole).where(ManagementRole.name == SUPER_ADMIN_ROLE_NAME)
        )
        if role is None:
            role = ManagementRole(
                name=SUPER_ADMIN_ROLE_NAME,
                description="内置超级管理员角色，不可删除、不可修改",
                is_super_admin=True,
                status=RoleStatus.ACTIVE,
            )
            self.db.add(role)
            await self.db.flush()
        return role

    # ═════════════════════════════════════════════════════════════
    # 内部
    # ═════════════════════════════════════════════════════════════

    async def _get_super_admin_role_ids(self) -> list[str]:
        result = await self.db.execute(
            select(ManagementRole.id).where(ManagementRole.is_super_admin)
        )
        return [r[0] for r in result]
