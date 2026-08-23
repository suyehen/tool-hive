"""CLI 命令测试（H03：init-admin）。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive import cli


def test_help_lists_init_admin_command(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "init-admin" in out


def test_init_admin_help_documents_password_env(capsys) -> None:
    """init-admin 帮助中必须说明初始密码环境变量，便于使用者了解。"""
    with pytest.raises(SystemExit) as exc:
        cli.main(["init-admin", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "TOOLHIVE_INIT_ADMIN_PASSWORD" in out


def test_init_admin_requires_account_and_real_name() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["init-admin"])
    assert exc.value.code == 2


def test_init_admin_dispatches_with_account_and_real_name() -> None:
    with patch("toolhive.cli.load_settings") as load:
        with patch("toolhive.cli._init_admin", new=AsyncMock(return_value=0)) as init:
            code = cli.main(["init-admin", "--account", "admin", "--real-name", "管理员"])
    assert code == 0
    load.assert_called_once_with(None)
    init.assert_awaited_once_with("admin", "管理员")


def test_init_admin_uses_initialized_session_factory() -> None:
    """回归：init-admin 必须使用初始化后的会话工厂，而非模块导入时的旧值。"""
    import toolhive.infrastructure.database as database

    session = AsyncMock()
    factory = MagicMock(return_value=session)

    def fake_init(*args, **kwargs) -> None:
        # 模拟真实 init_infrastructure：重新赋值模块级会话工厂
        database.async_session_factory = factory

    with patch.object(database, "async_session_factory", None):
        with patch.object(database, "init_infrastructure", side_effect=fake_init):
            with patch.dict("os.environ", {"TOOLHIVE_INIT_ADMIN_PASSWORD": "StrongPass123!"}):
                with patch("toolhive.services.account_service.AccountService") as account_cls:
                    svc = account_cls.return_value
                    svc.init_super_admin = AsyncMock()
                    code = asyncio.run(cli._init_admin("admin", "管理员"))

    assert code == 0
    svc.init_super_admin.assert_awaited_once_with(
        account="admin", real_name="管理员", password="StrongPass123!",
    )
