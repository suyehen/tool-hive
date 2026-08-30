"""配置系统测试。"""

from __future__ import annotations

import pytest

from toolhive.config import (
    Settings,
    load_settings,
    settings,
    validate_production_settings,
)


class TestSettingsDefaults:
    """默认值测试。"""

    def test_default_app_name(self) -> None:
        # _env_file=None：避免读取测试工作目录下的 .env，保证默认值断言不受本地配置影响
        s = Settings(_env_file=None)
        assert s.app_name == "ToolHive"

    def test_default_app_version(self) -> None:
        s = Settings(_env_file=None)
        assert s.app_version == "0.1.0"

    def test_default_debug_false(self) -> None:
        s = Settings(_env_file=None)
        assert s.debug is False

    def test_default_bind(self) -> None:
        s = Settings(_env_file=None)
        assert s.bind_host == "127.0.0.1"
        assert s.bind_port == 8100


class TestSettingsSecurityDefaults:
    """安全参数默认值测试。"""

    def test_login_lock_defaults(self) -> None:
        s = Settings()
        assert s.login_max_failures == 5
        assert s.login_lock_minutes == 30

    def test_captcha_defaults(self) -> None:
        s = Settings()
        assert s.login_failure_window_minutes == 10
        assert s.captcha_ttl_seconds == 300
        assert s.captcha_code_length == 4

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


class TestLoadSettings:
    """外挂配置加载测试。"""

    def test_yaml_loaded(self, tmp_path: pytest.TempPathFactory) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "app_name: TestAppYaml\noutbox:\n  poll_interval_ms: 2000\n",
            encoding="utf-8",
        )
        s = load_settings(cfg)
        assert s.app_name == "TestAppYaml"
        assert s.outbox.poll_interval_ms == 2000

    def test_env_overrides_yaml(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "app_name: FromYaml\noutbox:\n  poll_interval_ms: 2000\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("TOOLHIVE_APP_NAME", "FromEnv")
        monkeypatch.setenv("TOOLHIVE_OUTBOX_POLL_INTERVAL_MS", "3000")
        s = load_settings(cfg)
        assert s.app_name == "FromEnv"
        assert s.outbox.poll_interval_ms == 3000

    def test_yaml_overrides_default(self, tmp_path: pytest.TempPathFactory) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("snowflake:\n  worker_id: 7\n", encoding="utf-8")
        s = load_settings(cfg)
        assert s.snowflake.worker_id == 7
        assert s.snowflake.datacenter_id == 1

    def test_missing_config_file_raises(self, tmp_path: pytest.TempPathFactory) -> None:
        with pytest.raises(FileNotFoundError):
            load_settings(tmp_path / "not_exist.yaml")

    def test_invalid_yaml_raises(self, tmp_path: pytest.TempPathFactory) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("key: [1, 2\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_settings(cfg)

    def test_yaml_not_mapping_raises(self, tmp_path: pytest.TempPathFactory) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_settings(cfg)

    def test_defaults_without_config(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 切换到无 .env 的临时目录，避免读取测试工作目录下的本地配置
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TOOLHIVE_CONFIG_FILE", raising=False)
        s = load_settings(None)
        assert s.app_name == "ToolHive"
        assert s.outbox.poll_interval_ms == 1000
        assert s.chroma.mode == "embedded"
        assert s.snowflake.datacenter_id == 1


class TestProductionValidation:
    """生产配置校验（H11）。"""

    def test_development_skips_validation(self) -> None:
        s = Settings(_env_file=None, debug=True)
        validate_production_settings(s)  # 不应抛出

    def test_production_rejects_insecure_defaults(self) -> None:
        s = Settings(_env_file=None)
        with pytest.raises(ValueError) as exc_info:
            validate_production_settings(s)
        message = str(exc_info.value)
        assert "csrf_secret" in message
        assert "changeme" in message

    def test_production_accepts_secure_settings(self) -> None:
        s = Settings(
            _env_file=None,
            csrf_secret="x" * 32,
            database_url="postgresql+asyncpg://toolhive:realpass@db:5432/toolhive",
            redis_url="redis://:realpass@redis:6379/0",
        )
        validate_production_settings(s)  # 不应抛出

    def test_production_rejects_loopback_direct(self) -> None:
        s = Settings(
            _env_file=None,
            csrf_secret="x" * 32,
            database_url="postgresql+asyncpg://toolhive:realpass@db:5432/toolhive",
            redis_url="redis://:realpass@redis:6379/0",
            network={"allow_loopback_direct": True},
        )
        with pytest.raises(ValueError) as exc_info:
            validate_production_settings(s)
        assert "allow_loopback_direct" in str(exc_info.value)

    def test_production_rejects_invalid_signing_config(self) -> None:
        """运行侧签名配置非法时拒绝启动。"""
        s = Settings(
            _env_file=None,
            csrf_secret="x" * 32,
            database_url="postgresql+asyncpg://toolhive:realpass@db:5432/toolhive",
            redis_url="redis://:realpass@redis:6379/0",
            signing_algorithm="HMAC",
            signature_version="v2",
        )
        with pytest.raises(ValueError) as exc_info:
            validate_production_settings(s)
        message = str(exc_info.value)
        assert "signing_algorithm" in message
        assert "signature_version" in message

    def test_production_rejects_embedding_key_mismatch(self) -> None:
        """embedding_model 与 model_api_key 必须成对配置。"""
        s = Settings(
            _env_file=None,
            csrf_secret="x" * 32,
            database_url="postgresql+asyncpg://toolhive:realpass@db:5432/toolhive",
            redis_url="redis://:realpass@redis:6379/0",
            embedding_model="kinfra-text-embedding-4b",
            model_api_key="",
        )
        with pytest.raises(ValueError) as exc_info:
            validate_production_settings(s)
        assert "embedding_model" in str(exc_info.value)

    def test_production_rejects_non_embedded_chroma(self) -> None:
        """一期 chroma.mode 必须为 embedded。"""
        s = Settings(
            _env_file=None,
            csrf_secret="x" * 32,
            database_url="postgresql+asyncpg://toolhive:realpass@db:5432/toolhive",
            redis_url="redis://:realpass@redis:6379/0",
            chroma={"mode": "service"},
        )
        with pytest.raises(ValueError) as exc_info:
            validate_production_settings(s)
        assert "chroma.mode" in str(exc_info.value)

    def test_production_rejects_zero_provider_limits(self) -> None:
        """Provider 出站限制参数必须大于 0。"""
        s = Settings(
            _env_file=None,
            csrf_secret="x" * 32,
            database_url="postgresql+asyncpg://toolhive:realpass@db:5432/toolhive",
            redis_url="redis://:realpass@redis:6379/0",
            provider_max_response_bytes=0,
        )
        with pytest.raises(ValueError) as exc_info:
            validate_production_settings(s)
        assert "provider_max_response_bytes" in str(exc_info.value)


class TestDotenvAndEnvLoading:
    """.env 文件与复杂环境变量的加载测试（支持嵌套与列表字段）。"""

    def test_dotenv_flat_field(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """.env 平铺字段可被读取。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("TOOLHIVE_DEBUG=true\n", encoding="utf-8")
        s = load_settings(None)
        assert s.debug is True

    def test_dotenv_nested_field(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """.env 嵌套字段（network）可被读取。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "TOOLHIVE_NETWORK_ALLOW_LOOPBACK_DIRECT=true\n", encoding="utf-8",
        )
        s = load_settings(None)
        assert s.network.allow_loopback_direct is True

    def test_dotenv_list_field(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """.env 列表字段（JSON 数组）可被解析。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            'TOOLHIVE_NETWORK_TRUSTED_PROXIES=["127.0.0.1/32","::1/128"]\n',
            encoding="utf-8",
        )
        s = load_settings(None)
        assert s.network.trusted_proxies == ["127.0.0.1/32", "::1/128"]

    def test_dotenv_chroma_field(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """.env 嵌套字段（chroma）可被读取。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "TOOLHIVE_CHROMA_PERSIST_DIRECTORY=./chroma_data\n", encoding="utf-8",
        )
        s = load_settings(None)
        assert s.chroma.persist_directory == "./chroma_data"

    def test_env_list_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """真实环境变量的 JSON 数组字段可被解析。"""
        monkeypatch.setenv(
            "TOOLHIVE_NETWORK_TRUSTED_PROXIES", '["10.0.0.0/8","::1/128"]',
        )
        s = load_settings(None)
        assert s.network.trusted_proxies == ["10.0.0.0/8", "::1/128"]

    def test_priority_env_over_yaml_over_dotenv(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """优先级：真实环境变量 > 外挂 YAML > .env > 默认值。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "TOOLHIVE_APP_NAME=FromDotenv\n", encoding="utf-8",
        )
        cfg = tmp_path / "config.yaml"
        cfg.write_text("app_name: FromYaml\n", encoding="utf-8")

        # 真实环境变量存在时最高优先级
        monkeypatch.setenv("TOOLHIVE_APP_NAME", "FromEnv")
        assert load_settings(cfg).app_name == "FromEnv"
        monkeypatch.delenv("TOOLHIVE_APP_NAME")

        # 未设置环境变量时，YAML 覆盖 .env
        assert load_settings(cfg).app_name == "FromYaml"
        # 未设置环境变量且无 YAML 时，.env 生效
        assert load_settings(None).app_name == "FromDotenv"
