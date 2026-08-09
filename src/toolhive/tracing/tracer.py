"""全链路追踪 — trace_id 贯穿 Resolve → Execute。"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

current_trace_id: ContextVar[str] = ContextVar("trace_id", default="")

logger = logging.getLogger("toolhive")


def generate_trace_id() -> str:
    return uuid.uuid4().hex[:24]


def set_trace_id(trace_id: str):
    current_trace_id.set(trace_id)


def get_trace_id() -> str:
    return current_trace_id.get()
