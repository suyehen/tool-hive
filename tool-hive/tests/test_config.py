"""测试 ToolHive 配置模块。"""


def test_settings_defaults():
    from toolhive.config import settings

    assert settings.app_name == "ToolHive"
    assert settings.runtime_port == 8100
    assert settings.management_port == 8101
