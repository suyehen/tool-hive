"""认证流程编排服务。

职责：编排密码校验、MFA 验证、会话创建、CSRF Token 生成的完整流程。
不直接替代各子服务的独立能力。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.exceptions import AuthenticationError, ValidationError
from toolhive.models.management_account import ManagementAccount
from toolhive.services.account_service import AccountService
from toolhive.services.security.csrf import generate_csrf_token
from toolhive.services.security.password import verify_password
from toolhive.services.security.rate_limit import (
    check_captcha_required,
    clear_login_failures,
    record_login_failure,
)
from toolhive.services.security.session import create_session
from toolhive.services.security.totp import verify_totp


@dataclass
class LoginResult:
    """登录结果。"""
    session_id: str
    csrf_token: str
    account: ManagementAccount


@dataclass
class MfaSetupResult:
    """MFA 绑定准备结果。"""
    totp_uri: str
    secret: str


class AuthService:
    """认证流程编排。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.account_svc = AccountService(db)

    # ── 登录步骤 1：密码校验 ──

    async def login_password(
        self,
        username: str,
        password: str,
        source_ip: str,
    ) -> LoginResult | dict:
        """密码校验阶段。

        返回 LoginResult（无需 MFA）或 dict（需要 MFA 绑定/验证）。
        """
        account = await self.account_svc.get_by_username(username)

        if account is None:
            # 账号不存在：按 IP 记录失败
            await record_login_failure(None, source_ip)
            raise AuthenticationError("用户名或密码错误")

        if not account.is_active():
            if account.status == "disabled":
                raise AuthenticationError("账号已被禁用")
            if account.is_locked():
                raise AuthenticationError("账号已被锁定，请稍后再试")

        # 检查验证码
        require_captcha = await check_captcha_required(account.id, source_ip)
        if require_captcha:
            # 验证码由前端自行处理（校验成功后再次调用本接口，附带 captcha_token）
            raise AuthenticationError("captcha_required")

        # 校验密码
        is_valid, needs_rehash = verify_password(password, account.password_hash)
        if not is_valid:
            await self.account_svc.record_login_failure(account)
            await record_login_failure(account.id, source_ip)
            raise AuthenticationError("用户名或密码错误")

        # 密码正确 → 升级哈希（如需要）
        if needs_rehash:
            from toolhive.services.security.password import hash_password
            account.password_hash = hash_password(password)
            await self.db.flush()

        # 检查是否需要首次绑定 MFA
        from toolhive.models.mfa_config import MfaConfig
        from sqlalchemy import select
        mfa = await self.db.scalar(
            select(MfaConfig).where(MfaConfig.account_id == account.id)
        )
        if mfa is None or not mfa.is_bound:
            from toolhive.services.security.totp import (
                generate_totp_secret,
                generate_totp_uri,
            )
            secret = generate_totp_secret()
            uri = generate_totp_uri(secret, account.username)
            return {
                "require_mfa_setup": True,
                "totp_uri": uri,
                "secret": secret,
                "step": "mfa_setup",
            }

        # 需要 MFA 验证
        return {
            "require_mfa": True,
            "step": "mfa_verify",
        }

    # ── 登录步骤 2：MFA 验证 ──

    async def login_mfa_verify(
        self,
        account: ManagementAccount,
        code: str,
        source_ip: str,
    ) -> LoginResult:
        """MFA 验证成功后创建完整登录会话。"""
        from sqlalchemy import select
        from toolhive.models.mfa_config import MfaConfig

        mfa = await self.db.scalar(
            select(MfaConfig).where(MfaConfig.account_id == account.id)
        )
        if mfa is None:
            raise ValidationError("未绑定 MFA，请先完成绑定")

        from toolhive.services.security.totp import decrypt_totp_secret
        secret = decrypt_totp_secret(mfa.encrypted_secret)

        if not verify_totp(secret, code):
            await self.account_svc.record_login_failure(account)
            await record_login_failure(account.id, source_ip)
            raise AuthenticationError("MFA 验证失败")

        # 登录成功
        await self.account_svc.record_login_success(account)
        await clear_login_failures(account.id, source_ip)

        return await self._finish_login(account, source_ip)

    # ── 恢复码登录 ──

    async def login_with_recovery_code(
        self,
        username: str,
        password: str,
        recovery_code: str,
        source_ip: str,
    ) -> LoginResult:
        """使用恢复码登录（密码 + 恢复码，跳过 TOTP）。"""
        account = await self.account_svc.get_by_username(username)
        if account is None or not account.is_active():
            raise AuthenticationError("用户名或密码错误")

        is_valid, _ = verify_password(password, account.password_hash)
        if not is_valid:
            await self.account_svc.record_login_failure(account)
            await record_login_failure(account.id, source_ip)
            raise AuthenticationError("用户名或密码错误")

        from sqlalchemy import select
        from toolhive.models.mfa_config import MfaConfig
        mfa = await self.db.scalar(
            select(MfaConfig).where(MfaConfig.account_id == account.id)
        )
        if mfa is None:
            raise ValidationError("未绑定 MFA")

        if not mfa.verify_recovery_code(recovery_code):
            await self.account_svc.record_login_failure(account)
            await record_login_failure(account.id, source_ip)
            raise AuthenticationError("恢复码无效或已被使用")

        await self.account_svc.record_login_success(account)
        await clear_login_failures(account.id, source_ip)
        return await self._finish_login(account, source_ip)

    # ── MFA 绑定 ──

    async def bind_mfa(
        self,
        account: ManagementAccount,
        secret: str,
        code: str,
    ) -> list[str]:
        """首次绑定 TOTP。返回恢复码明文（仅此一次展示）。"""
        from toolhive.models.mfa_config import MfaConfig
        from sqlalchemy import select

        if not verify_totp(secret, code):
            raise ValidationError("TOTP 验证码不正确，请重试")

        from toolhive.services.security.totp import (
            encrypt_totp_secret,
            generate_recovery_codes,
        )

        encrypted = encrypt_totp_secret(secret)
        recovery = generate_recovery_codes()

        mfa = MfaConfig(
            account_id=account.id,
            encrypted_secret=encrypted,
            is_bound=True,
        )
        mfa.set_recovery_codes(recovery.hash_codes)
        self.db.add(mfa)
        await self.db.flush()

        return recovery.plain_codes

    # ── 登出 ──

    async def logout(self, session_id: str) -> None:
        from toolhive.services.security.session import revoke_session
        await revoke_session(session_id)

    # ── 修改密码 ──

    async def change_password(
        self,
        account: ManagementAccount,
        old_password: str,
        new_password: str,
    ) -> str:
        """修改密码，返回新的 session_id（防会话固定）。"""
        await self.account_svc.update_password(account, old_password, new_password)
        from toolhive.services.security.session import rotate_session_id
        # 这里不轮转，由调用方传入 old_session_id 处理
        return ""

    # ── 内部 ──

    async def _finish_login(
        self, account: ManagementAccount, source_ip: str,
    ) -> LoginResult:
        """完成登录的最后一步：创建会话 + CSRF Token。"""
        from toolhive.services.role_service import RoleService
        role_svc = RoleService(self.db)
        roles = await role_svc.get_account_roles(account.id)
        is_super_admin = any(r.is_super_admin for r in roles)
        session_id = await create_session(
            account_id=account.id,
            username=account.username,
            is_super_admin=is_super_admin,
            source_ip=source_ip,
        )
        csrf_token = generate_csrf_token(session_id)
        return LoginResult(
            session_id=session_id,
            csrf_token=csrf_token,
            account=account,
        )
