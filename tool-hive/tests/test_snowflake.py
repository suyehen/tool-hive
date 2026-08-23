"""雪花 ID 生成器测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from toolhive.core.snowflake import SnowflakeGenerator

EPOCH_MS = 1767225600000


class TestSnowflakeGenerator:
    def test_next_id_is_decimal_string(self) -> None:
        gen = SnowflakeGenerator(epoch_ms=EPOCH_MS, datacenter_id=1, worker_id=0)
        value = gen.next_id()
        assert isinstance(value, str)
        assert value.isdigit()

    def test_ids_monotonic_increasing(self) -> None:
        gen = SnowflakeGenerator(epoch_ms=EPOCH_MS, datacenter_id=1, worker_id=0)
        previous = -1
        for _ in range(1000):
            current = int(gen.next_id())
            assert current > previous
            previous = current

    def test_machine_bits_encoded(self) -> None:
        gen = SnowflakeGenerator(epoch_ms=EPOCH_MS, datacenter_id=3, worker_id=5)
        value = int(gen.next_id())
        assert ((value >> 17) & 0x1F) == 3
        assert ((value >> 12) & 0x1F) == 5

    def test_sequence_does_not_collide_with_machine_bits(self) -> None:
        gen = SnowflakeGenerator(epoch_ms=EPOCH_MS, datacenter_id=0, worker_id=0)
        value = int(gen.next_id())
        # 序列号只占低 12 位
        assert (value & 0xFFF) == 0

    def test_invalid_machine_id(self) -> None:
        with pytest.raises(ValueError):
            SnowflakeGenerator(epoch_ms=EPOCH_MS, datacenter_id=32, worker_id=0)
        with pytest.raises(ValueError):
            SnowflakeGenerator(epoch_ms=EPOCH_MS, datacenter_id=1, worker_id=-1)

    def test_clock_rollback_beyond_tolerance_rejected(self) -> None:
        gen = SnowflakeGenerator(
            epoch_ms=EPOCH_MS,
            datacenter_id=1,
            worker_id=0,
            clock_rollback_tolerance_ms=5,
        )
        base_ms = 1770000000000
        with patch(
            "toolhive.core.snowflake.time.time_ns",
            side_effect=[base_ms * 1_000_000, (base_ms - 100) * 1_000_000],
        ):
            gen.next_id()
            with pytest.raises(RuntimeError):
                gen.next_id()

    def test_clock_rollback_within_tolerance_allowed(self) -> None:
        gen = SnowflakeGenerator(
            epoch_ms=EPOCH_MS,
            datacenter_id=1,
            worker_id=0,
            clock_rollback_tolerance_ms=5,
        )
        base_ms = 1770000000000
        with patch(
            "toolhive.core.snowflake.time.time_ns",
            side_effect=[
                base_ms * 1_000_000,
                (base_ms - 3) * 1_000_000,
                base_ms * 1_000_000,
            ],
        ):
            gen.next_id()
            value = gen.next_id()
            assert int(value) > 0


def test_module_generate_id_returns_snowflake_string() -> None:
    """模块级生成器返回十进制数字字符串。"""
    from toolhive.core.snowflake import generate_id
    value = generate_id()
    assert isinstance(value, str)
    assert value.isdigit()


def test_model_pk_default_uses_snowflake() -> None:
    """ORM 主键默认值生成雪花 ID（非 UUID 十六进制）。"""
    from toolhive.models.base import gen_id
    assert gen_id().isdigit()


def test_configure_snowflake_binds_settings() -> None:
    """启动阶段绑定配置后，生成器使用指定的机器位。"""
    from toolhive.config import SnowflakeSettings
    from toolhive.core import snowflake
    snowflake.configure_snowflake(
        SnowflakeSettings(datacenter_id=5, worker_id=7),
    )
    value = int(snowflake.generate_id())
    assert ((value >> 17) & 0x1F) == 5
    assert ((value >> 12) & 0x1F) == 7
