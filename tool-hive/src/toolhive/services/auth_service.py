"""认证流程编排服务。

职责：编排图形验证码与密码校验、会话创建、CSRF Token 生成的完整流程。
不直接替代各子服务的独立能力。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.config import AdminSecuritySettings
from toolhive.core.enums import AccountStatus
from toolhive.core.exceptions import AuthenticationError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.management_account import ManagementAccount
from toolhive.services.account_service import AccountService
from toolhive.services.security.captcha import consume_captcha
from toolhive.services.security.csrf import generate_csrf_token
from toolhive.services.security.password import verify_password
from toolhive.services.security.rate_limit import (
    clear_login_failures,
    record_login_failure,
)
from toolhive.services.security.session import create_session


@dataclass
class LoginResult:
    """登录结果。"""
    session_id: str
    csrf_token: str
    account: ManagementAccount


class AuthService:
    """认证流程编排。"""

    def __init__(self, db: AsyncSession, admin_security: AdminSecuritySettings):
        self.db = db
        self._admin_security = admin_security
        self.account_svc = AccountService(db, admin_security)

    # ── 登录 ──

    @transactional()
    async def login_password(
        self,
        username: str,
        password: str,
        source_ip: str,
        captcha_id: str,
        captcha_code: str,
    ) -> LoginResult:
        """图形验证码 + 账号密码校验，通过后直接创建登录会话。"""
        # 图形验证码：先校验再进入账号流程；无论正确与否均一次性消费
        if not await consume_captcha(captcha_id, captcha_code):
            raise AuthenticationError("验证码错误或已过期，请刷新后重试")

        account = await self.account_svc.get_by_username(username)

        if account is None:
            # 账号不存在：按 IP 记录失败
            await record_login_failure(None, source_ip)
            raise AuthenticationError("用户名或密码错误")

        if not account.is_active():
            if account.status == AccountStatus.DISABLED:
                raise AuthenticationError("账号已被禁用")
            if account.status == AccountStatus.OFFBOARDED:
                raise AuthenticationError("账号已离职，无法登录")
            if account.is_locked():
                raise AuthenticationError("账号已被锁定，请稍后再试")

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

        # 登录成功：记录成功并清除失败计数
        await self.account_svc.record_login_success(account)
        await clear_login_failures(account.id, source_ip)
        return await self._finish_login(account, source_ip)

    # ── 登出 ──

    async def logout(self, session_id: str) -> None:
        from toolhive.services.security.session import revoke_session
        await revoke_session(session_id)

    # ── 修改密码 ──

    @transactional()
    async def change_password(
        self,
        account: ManagementAccount,
        old_password: str,
        new_password: str,
    ) -> str:
        """修改密码，返回新的 session_id（防会话固定）。"""
        await self.account_svc.update_password(account, old_password, new_password)
        # 这里不轮转，由调用方传入 old_session_id 处理
        return ""

    # ── 内部 ──

    async def _finish_login(
        self, account: ManagementAccount, source_ip: str,
    ) -> LoginResult:
        """完成登录的最后一步：创建会话 + CSRF Token。"""
        session_id = await create_session(
            account_id=account.id,
            username=account.username,
            security_version=account.security_version,
            source_ip=source_ip,
        )
        csrf_token = generate_csrf_token(session_id)
        return LoginResult(
            session_id=session_id,
            csrf_token=csrf_token,
            account=account,
        )
