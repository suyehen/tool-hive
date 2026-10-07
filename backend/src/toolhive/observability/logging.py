"""结构化日志、``trace_id`` 与延迟直方图（任务 A3）。设计 §11。

为什么是"日志 + 直方图桶"而不是 Prometheus
------------------------------------------
设计明确**不引入 OpenTelemetry 与 Prometheus**（§11、§12）。代价是**无法从原始日志直接算 p95**。
补救办法写在 §11 的「延迟分位」一行：**把预聚合的延迟直方图桶直接写进日志**——
固定边界（默认 10/25/50/100/200/500/1000/2000 ms），解析日志即可算分位，成本几乎为零。

本模块提供三样东西
------------------
1. :func:`configure_logging` —— 让每条日志都是 JSON，且**必带 ``trace_id``**。
2. :func:`trace` —— 在入口生成 ``trace_id`` 并贯穿 ``retrieve → authorize → execute → upstream``。
3. :class:`LatencyBuckets` / :class:`LatencyHistogram` —— 延迟桶的定界与累计。

以及 §11 提到的关键计数：:func:`log_counter`。
"""

from __future__ import annotations

import json
import logging
import math
import sys
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import IO, Any, Final

__all__ = [
    "LatencyBuckets",
    "LatencyHistogram",
    "bind_trace_id",
    "configure_logging",
    "current_trace_id",
    "get_logger",
    "log_counter",
    "log_latency",
    "new_trace_id",
    "trace",
]

#: 标准 LogRecord 自带的属性。格式化时要把它们排除，剩下的才是调用方传入的 `extra` 字段。
_RESERVED: Final[frozenset[str]] = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
        "pathname", "process", "processName", "relativeCreated", "stack_info",
        "taskName", "thread", "threadName",
    }
)

#: 当前请求的 trace_id。用 ContextVar 而非线程局部变量——服务是异步的，
#: 一个线程会交错处理多个请求，线程局部变量会串号。
_trace_id: ContextVar[str | None] = ContextVar("toolhive_trace_id", default=None)


# ---------------------------------------------------------------------------
# trace_id
# ---------------------------------------------------------------------------


def new_trace_id() -> str:
    """生成一个新的 ``trace_id``（32 位十六进制，与 W3C trace-id 同长度）。"""
    return uuid.uuid4().hex


def current_trace_id() -> str | None:
    """取当前上下文的 ``trace_id``；未设置时为 ``None``。"""
    return _trace_id.get()


def bind_trace_id(trace_id: str) -> Token[str | None]:
    """绑定 ``trace_id``，返回可用于 :func:`_trace_id.reset` 的令牌。

    绝大多数场景请用 :func:`trace` 上下文管理器，它会保证复位。
    """
    return _trace_id.set(trace_id)


@contextmanager
def trace(trace_id: str | None = None) -> Iterator[str]:
    """在入口处开启一个 trace 上下文，退出时自动复位。

    ``trace_id`` 为 ``None`` 时自动生成。退出时**恢复上一个值**而不是清空——
    这样嵌套调用（外层已有 trace）不会把外层的 trace_id 抹掉。
    """
    resolved = trace_id or new_trace_id()
    token = _trace_id.set(resolved)
    try:
        yield resolved
    finally:
        _trace_id.reset(token)


# ---------------------------------------------------------------------------
# JSON 格式化
# ---------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """把日志渲染成单行 JSON，并强制注入 ``trace_id`` 与 ``service``。

    ``trace_id`` 取自上下文，**不由调用方逐个传参**——否则迟早会漏掉某条日志，
    而"按 trace_id 串起整条链路"正是设计 §11 对 Trace 的全部要求。
    """

    def __init__(
        self, *, service: str = "toolhive", serializer: Callable[[object], str] | None = None
    ) -> None:
        super().__init__()
        self._service = service
        self._dumps = serializer or (lambda o: json.dumps(o, ensure_ascii=False, default=str))

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created))
            + f".{int(record.msecs):03d}",
            "level": record.levelname,
            "logger": record.name,
            "service": self._service,
            "msg": record.getMessage(),
            "trace_id": current_trace_id(),
        }

        # 调用方通过 extra={...} 传入的结构化字段
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return str(self._dumps(payload))


def configure_logging(
    *,
    level: str = "INFO",
    service: str = "toolhive",
    stream: IO[str] | None = None,
) -> None:
    """把根 logger 配置成 JSON 输出。**幂等**——重复调用不会叠加 handler。

    只挂一个 handler 到根 logger，并移除既有的：否则 uvicorn 等库自己也加了
    handler，会出现同一条日志打印两次、其中一次还不是 JSON。
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter(service=service))
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn / sqlalchemy 的 logger 自己会向上传播，交给根 logger 统一格式化。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def get_logger(name: str) -> logging.Logger:
    """取 logger。保留此包装是为了将来统一注入上下文，而不是直接到处用 ``logging.getLogger``。"""
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# 延迟直方图桶（设计 §11 的「延迟分位」）
# ---------------------------------------------------------------------------


class LatencyBuckets:
    """固定边界的延迟分桶（单位：毫秒）。

    用**累积桶**（``le_<bound>``，Prometheus 风格）而不是区间桶：
    算出 p95 只需找第一个累计占比超过 95% 的桶，区间桶则要在解析端再累加一次。
    """

    def __init__(self, bounds_ms: Sequence[int]) -> None:
        if not bounds_ms:
            raise ValueError("延迟桶边界不得为空（设计 §11）")
        ordered = tuple(sorted({int(b) for b in bounds_ms}))
        if any(b <= 0 for b in ordered):
            raise ValueError("延迟桶边界必须为正数（毫秒）")
        self._bounds = ordered

    @property
    def bounds(self) -> tuple[int, ...]:
        return self._bounds

    @property
    def labels(self) -> tuple[str, ...]:
        """累计桶名，含 +Inf；与单次观测的区间标签区分。"""
        labels = [f"le_{b}" for b in self._bounds]
        labels.append("le_+Inf")
        return tuple(labels)

    def label(self, latency_ms: float) -> str:
        """返回单次观测的区间标签；不返回累计桶名。

        首区间为 [0, upper]，后续为 (lower, upper]；溢出为 (lower, +Inf)。
        例如 30ms → range_25_50_ms，0ms → range_0_10_ms。
        """
        if not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("延迟必须是有限的非负毫秒值")
        lower = 0
        for bound in self._bounds:
            if latency_ms <= bound:
                return f"range_{lower}_{bound}_ms"
            lower = bound
        return f"range_{lower}_inf_ms"

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"LatencyBuckets({list(self._bounds)})"


class LatencyHistogram:
    """按操作名累计的延迟直方图。

    用途是把一批观测**聚合成一行日志**（而不是每次观测都写一行），
    这样"每 N 秒输出一次分位"的成本就只有一行日志。
    """

    def __init__(self, buckets: LatencyBuckets) -> None:
        self._buckets = buckets
        self._counts: dict[str, int] = dict.fromkeys(buckets.labels, 0)
        self._total = 0
        self._sum_ms = 0.0

    def observe(self, latency_ms: float) -> str:
        """更新累计桶，返回单次观测区间标签（不是累计桶名）。"""
        label = self._buckets.label(latency_ms)
        for bound in self._buckets.bounds:
            if latency_ms <= bound:
                self._counts[f"le_{bound}"] += 1
        self._counts["le_+Inf"] += 1
        self._total += 1
        self._sum_ms += latency_ms
        return label

    @property
    def count(self) -> int:
        return self._total

    def snapshot(self) -> dict[str, Any]:
        """buckets 是完整累计序列，含 le_+Inf；最后一项等于 count。"""
        return {
            "count": self._total,
            "sum_ms": round(self._sum_ms, 3),
            "avg_ms": round(self._sum_ms / self._total, 3) if self._total else 0.0,
            "buckets": dict(self._counts),
        }

    def reset(self) -> None:
        for label in self._counts:
            self._counts[label] = 0
        self._total = 0
        self._sum_ms = 0.0


# ---------------------------------------------------------------------------
# 写入辅助
# ---------------------------------------------------------------------------


def log_latency(
    logger: logging.Logger,
    *,
    operation: str,
    latency_ms: float,
    buckets: LatencyBuckets,
    level: int = logging.INFO,
    **fields: object,
) -> str:
    """记录一次延迟观测。返回单次区间标签，日志使用 latency_interval。

    典型用法::

        log_latency(log, operation="retrieval.search", latency_ms=42.7, buckets=b)
        # → {"msg": "latency", "operation": "retrieval.search",
        #    "latency_ms": 42.7, "latency_interval": "range_25_50_ms", "trace_id": "..."}
    """
    label = buckets.label(latency_ms)
    logger.log(
        level,
        "latency",
        extra={
            "operation": operation,
            "latency_ms": round(latency_ms, 3),
            "latency_interval": label,
            **fields,
        },
    )
    return label


def log_counter(
    logger: logging.Logger,
    *,
    name: str,
    value: int = 1,
    **fields: object,
) -> None:
    """记录一次关键计数。设计 §11：QPS、错误率、配额拒绝、熔断次数、检索降级率走日志。

    不引入 Prometheus 时，这是把这些指标送出去的唯一通道；命名保持稳定，
    将来若要接入监控体系，日志解析端可以直接复用。
    """
    logger.info("counter", extra={"counter": name, "value": value, **fields})


def latency_buckets_from_settings(bounds_ms: Sequence[int]) -> LatencyBuckets:
    """从配置构造 :class:`LatencyBuckets`。

    用法：``latency_buckets_from_settings(settings.logging.latency_buckets)``
    """
    return LatencyBuckets(list(bounds_ms))
