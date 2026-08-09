"""测试 ToolHive 配置模块。"""


def test_settings_defaults():
    from toolhive.config import settings

    assert settings.app_name == "ToolHive"
    assert settings.runtime_port == 8100
    assert settings.management_port == 8101


def test_coverage_enum():
    from toolhive.schemas.common import CoverageResult

    assert CoverageResult.full_coverage.value == "full_coverage"
    assert CoverageResult.unsupported.value == "unsupported"
