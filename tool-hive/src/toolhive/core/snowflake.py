"""标准 64 位雪花 ID 生成器。

结构：1 位符号位（恒 0）+ 41 位时间戳（毫秒，相对 epoch）+ 10 位机器位
（datacenter_id 5 位 + worker_id 5 位）+ 12 位序列号。
生成器直接返回十进制字符串；时钟回退超过容差时拒绝生成 ID。
"""

from __future__ import annotations

import threading
import time

from toolhive.config import SnowflakeSettings


class SnowflakeGenerator:
    """线程安全的雪花 ID 生成器。"""

    def __init__(
        self,
        epoch_ms: int,
        datacenter_id: int,
        worker_id: int,
        clock_rollback_tolerance_ms: int = 5,
    ) -> None:
        if not 0 <= datacenter_id <= 31:
            raise ValueError("datacenter_id 必须在 0～31 之间")
        if not 0 <= worker_id <= 31:
            raise ValueError("worker_id 必须在 0～31 之间")
        if clock_rollback_tolerance_ms < 0:
            raise ValueError("clock_rollback_tolerance_ms 不能为负数")

        self._epoch_ms = epoch_ms
        self._datacenter_id = datacenter_id
        self._worker_id = worker_id
        self._tolerance_ms = clock_rollback_tolerance_ms
        self._lock = threading.Lock()
        self._last_ms = -1
        self._sequence = 0

    def next_id(self) -> str:
        """生成下一个 ID，返回十进制字符串。"""
        with self._lock:
            now_ms = time.time_ns() // 1_000_000

            if now_ms < self._last_ms:
                drift = self._last_ms - now_ms
                if drift > self._tolerance_ms:
                    raise RuntimeError(
                        f"系统时钟回退 {drift}ms，超过容差 "
                        f"{self._tolerance_ms}ms，拒绝生成 ID"
                    )
                # 容差内：等待时钟追平
                while time.time_ns() // 1_000_000 < self._last_ms:
                    time.sleep(0.001)
                now_ms = self._last_ms

            if now_ms == self._last_ms:
                self._sequence = (self._sequence + 1) & 0xFFF
                if self._sequence == 0:
                    # 当前毫秒序列耗尽，等待下一毫秒
                    while time.time_ns() // 1_000_000 <= self._last_ms:
                        time.sleep(0.001)
                    now_ms = time.time_ns() // 1_000_000
            else:
                self._sequence = 0

            self._last_ms = now_ms
            timestamp = now_ms - self._epoch_ms
            if timestamp < 0:
                raise RuntimeError("系统时间早于雪花 epoch，拒绝生成 ID")
            if timestamp >= (1 << 41):
                raise RuntimeError("雪花时间戳超出 41 位范围")

            value = (
                (timestamp << 22)
                | (self._datacenter_id << 17)
                | (self._worker_id << 12)
                | self._sequence
            )
            return str(value)


# 全局生成器：默认使用配置默认值，启动阶段由 configure_snowflake 覆盖
_default_settings = SnowflakeSettings()
_generator = SnowflakeGenerator(
    epoch_ms=_default_settings.epoch_ms,
    datacenter_id=_default_settings.datacenter_id,
    worker_id=_default_settings.worker_id,
    clock_rollback_tolerance_ms=_default_settings.clock_rollback_tolerance_ms,
)


def configure_snowflake(settings: SnowflakeSettings) -> None:
    """启动阶段绑定雪花配置（多实例需保证 datacenter_id + worker_id 唯一）。"""
    global _generator
    _generator = SnowflakeGenerator(
        epoch_ms=settings.epoch_ms,
        datacenter_id=settings.datacenter_id,
        worker_id=settings.worker_id,
        clock_rollback_tolerance_ms=settings.clock_rollback_tolerance_ms,
    )


def generate_id() -> str:
    """生成全局业务主键雪花 ID（十进制字符串）。"""
    return _generator.next_id()
