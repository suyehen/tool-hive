"""初始化状态接口测试（H03）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from toolhive.api.admin.router import admin_app


def test_bootstrap_status_not_initialized() -> None:
    with patch("toolhive.api.admin.bootstrap.AccountService") as acct_cls:
        svc = acct_cls.return_value
        svc.has_any_account = AsyncMock(return_value=False)
        client = TestClient(admin_app)
        resp = client.get("/bootstrap/status")
    assert resp.status_code == 200
    assert resp.json() == {"initialized": False}


def test_bootstrap_status_initialized() -> None:
    with patch("toolhive.api.admin.bootstrap.AccountService") as acct_cls:
        svc = acct_cls.return_value
        svc.has_any_account = AsyncMock(return_value=True)
        client = TestClient(admin_app)
        resp = client.get("/bootstrap/status")
    assert resp.status_code == 200
    assert resp.json() == {"initialized": True}
