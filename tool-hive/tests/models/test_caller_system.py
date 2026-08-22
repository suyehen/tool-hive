"""调用系统模型有效期状态测试（生命周期状态与有效期解耦）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from toolhive.core.enums import CallerSystemStatus
from toolhive.models.caller_system import CallerSystem


def _system(**kwargs) -> CallerSystem:
    defaults = dict(
        system_id="sys_1",
        name="测试系统",
        environment="production",
        status=CallerSystemStatus.ENABLED,
    )
    defaults.update(kwargs)
    return CallerSystem(**defaults)


def test_effective_state_not_started() -> None:
    s = _system(effective_from=datetime.now(UTC) + timedelta(days=1))
    assert s.effective_state == "not_started"
    assert not s.is_enabled()


def test_effective_state_expired() -> None:
    s = _system(effective_to=datetime.now(UTC) - timedelta(minutes=1))
    assert s.effective_state == "expired"
    assert not s.is_enabled()


def test_effective_state_effective_without_window() -> None:
    s = _system()
    assert s.effective_state == "effective"
    assert s.is_enabled()


def test_effective_state_effective_within_window() -> None:
    s = _system(
        effective_from=datetime.now(UTC) - timedelta(days=1),
        effective_to=datetime.now(UTC) + timedelta(days=1),
    )
    assert s.effective_state == "effective"
    assert s.is_enabled()


def test_is_enabled_requires_enabled_status() -> None:
    s = _system(status=CallerSystemStatus.DRAFT)
    assert s.effective_state == "effective"
    assert not s.is_enabled()
