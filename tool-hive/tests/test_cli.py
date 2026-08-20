"""CLI 命令测试（H03：init-admin）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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


def test_init_admin_requires_username() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["init-admin"])
    assert exc.value.code == 2


def test_init_admin_dispatches_with_username() -> None:
    with patch("toolhive.cli.load_settings") as load:
        with patch("toolhive.cli._init_admin", new=AsyncMock(return_value=0)) as init:
            code = cli.main(["init-admin", "--username", "admin"])
    assert code == 0
    load.assert_called_once_with(None)
    init.assert_awaited_once_with("admin")
