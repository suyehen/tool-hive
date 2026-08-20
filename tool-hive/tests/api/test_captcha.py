"""验证码链路 API 测试（H04）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from toolhive.api.admin.router import admin_app


def test_captcha_challenge_endpoint() -> None:
    """POST /auth/captcha/challenge 返回验证码挑战。"""
    redis = AsyncMock()
    with patch("toolhive.services.security.captcha.get_redis", return_value=redis):
        client = TestClient(admin_app)
        resp = client.post("/auth/captcha/challenge")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"captcha_id", "image", "expires_in_seconds"}
    assert body["image"].startswith("data:image/png;base64,")


def test_login_rejects_wrong_captcha() -> None:
    """验证码错误或已过期时登录返回 401，不进入账号校验。"""
    with patch(
        "toolhive.services.auth_service.consume_captcha",
        AsyncMock(return_value=False),
    ) as consume:
        client = TestClient(admin_app)
        resp = client.post(
            "/auth/login",
            json={
                "username": "admin",
                "password": "whatever",
                "captcha_id": "cid-1",
                "captcha_code": "AB12",
            },
        )

    assert resp.status_code == 401
    assert "验证码" in resp.json()["detail"]
    consume.assert_awaited_once_with("cid-1", "AB12")


def test_login_continues_after_valid_captcha() -> None:
    """验证码校验通过后继续账号流程（账号不存在返回通用密码错误）。"""
    with (
        patch(
            "toolhive.services.auth_service.consume_captcha",
            AsyncMock(return_value=True),
        ),
        patch("toolhive.services.auth_service.AccountService") as acct_cls,
        patch(
            "toolhive.services.auth_service.record_login_failure",
            AsyncMock(),
        ),
    ):
        acct_svc = acct_cls.return_value
        acct_svc.get_by_username = AsyncMock(return_value=None)
        client = TestClient(admin_app)
        resp = client.post(
            "/auth/login",
            json={
                "username": "nobody",
                "password": "wrong-password",
                "captcha_id": "cid-2",
                "captcha_code": "CD34",
            },
        )

    assert resp.status_code == 401
    assert "用户名或密码错误" in resp.json()["detail"]


def test_login_success_creates_session_directly() -> None:
    """验证码与密码均正确时，直接创建会话并返回 session_id/csrf_token（H05）。"""
    account = MagicMock()
    account.id = "acc-1"
    account.username = "admin"
    account.security_version = "0"
    account.is_active.return_value = True

    with (
        patch(
            "toolhive.services.auth_service.consume_captcha",
            AsyncMock(return_value=True),
        ),
        patch("toolhive.services.auth_service.AccountService") as acct_cls,
        patch(
            "toolhive.services.auth_service.verify_password",
            MagicMock(return_value=(True, False)),
        ),
        patch(
            "toolhive.services.auth_service.create_session",
            AsyncMock(return_value="sid-1"),
        ),
        patch(
            "toolhive.services.auth_service.generate_csrf_token",
            MagicMock(return_value="csrf-1"),
        ),
        patch(
            "toolhive.services.auth_service.clear_login_failures",
            AsyncMock(),
        ),
    ):
        acct_svc = acct_cls.return_value
        acct_svc.get_by_username = AsyncMock(return_value=account)
        acct_svc.record_login_success = AsyncMock()
        client = TestClient(admin_app)
        resp = client.post(
            "/auth/login",
            json={
                "username": "admin",
                "password": "correct-password",
                "captcha_id": "cid-3",
                "captcha_code": "EF56",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sid-1"
    assert body["csrf_token"] == "csrf-1"
    assert body["username"] == "admin"
    assert "set-cookie" in resp.headers
