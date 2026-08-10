"""配置系统测试。"""

from __future__ import annotations

import pytest

from toolhive.config import Settings, settings


class TestSettingsDefaults:
    """默认值测试。"""

    def test_default_app_name(self) -> None:
        s = Settings()
        assert s.app_name == "ToolHive"

    def test_default_app_version(self) -> None:
        s = Settings()
        assert s.app_version == "0.1.0"

    def test_default_debug_false(self) -> None:
        s = Settings()
        assert s.debug is False

    def test_default_runtime_bind(self) -> None:
        s = Settings()
        assert s.runtime_host == "127.0.0.1"
        assert s.runtime_port == 8100

    def test_default_management_bind(self) -> None:
        s = Settings()
        assert s.management_host == "0.0.0.0"
        assert s.management_port == 8101


class TestSettingsSecurityDefaults:
    """安全参数默认值测试。"""

    def test_login_lock_defaults(self) -> None:
        s = Settings()
        assert s.login_max_failures == 5
        assert s.login_lock_minutes == 30

    def test_captcha_defaults(self) -> None:
        s = Settings()
        assert s.captcha_trigger_failures == 3
        assert s.captcha_trigger_window_minutes == 10

    def test_password_length_defaults(self) -> None:
        s = Settings()
        assert s.password_min_length == 12
        assert s.password_max_length == 128
        assert s.password_history_count == 5

    def test_session_timeout_defaults(self) -> None:
        s = Settings()
        assert s.session_idle_timeout_minutes == 30
        assert s.session_absolute_timeout_hours == 8

    def test_signature_defaults(self) -> None:
        s = Settings()
        assert s.signature_time_window_seconds == 300
        assert s.nonce_retention_minutes == 10
        assert s.signing_key_min_bits == 2048
        assert s.signing_algorithm == "RSA-PSS-SHA256"
        assert s.signature_version == "TOOLHIVE-SIGN-V1"


class TestSettingsEnvOverride:
    """环境变量覆盖测试。"""

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TOOLHIVE_APP_NAME", "TestApp")
        monkeypatch.setenv("TOOLHIVE_DEBUG", "true")
        monkeypatch.setenv("TOOLHIVE_LOGIN_MAX_FAILURES", "10")
        s = Settings()
        assert s.app_name == "TestApp"
        assert s.debug is True
        assert s.login_max_failures == 10

    def test_env_prefix_isolation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 TOOLHIVE_ 前缀的变量不应被读取。"""
        monkeypatch.setenv("APP_NAME", "ShouldNotBeRead")
        s = Settings()
        assert s.app_name == "ToolHive"


class TestGlobalSettingsInstance:
    """模块级 settings 单例测试。"""

    def test_settings_is_instance(self) -> None:
        assert isinstance(settings, Settings)

    def test_settings_has_app_name(self) -> None:
        assert len(settings.app_name) > 0
