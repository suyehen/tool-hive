"""日志脱敏过滤器。确保敏感信息不写入日志。"""

from __future__ import annotations

import logging
import re

# 敏感 key 黑名单（小写匹配）。日志中检测到这些 key 时替换 value。
SENSITIVE_KEYS = frozenset({
    "password",
    "password_hash",
    "secret",
    "totp",
    "session_id",
    "sessionid",
    "csrf_token",
    "csrftoken",
    "token",
    "private_key",
    "privatekey",
    "recovery_code",
    "recoverycode",
    "api_key",
    "apikey",
    "authorization",
})

# 敏感模式：JSON 风格 "key": "value"
_SENSITIVE_JSON_RE = re.compile(
    r'("(?:' + "|".join(SENSITIVE_KEYS) + r')"\s*:\s*")[^"]*(")',
    re.IGNORECASE,
)

# 敏感模式：key=value 风格
_SENSITIVE_KV_RE = re.compile(
    r'((?:' + "|".join(SENSITIVE_KEYS) + r')=[^\s&]*)',
    re.IGNORECASE,
)

REPLACEMENT = "***"


class SensitiveDataFilter(logging.Filter):
    """日志过滤器：将敏感 key 对应的 value 替换为 ***。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg and isinstance(record.msg, str):
            record.msg = _SENSITIVE_JSON_RE.sub(rf"\1{REPLACEMENT}\2", record.msg)
            record.msg = _SENSITIVE_KV_RE.sub(rf"\1{REPLACEMENT}", record.msg)
        if record.args and isinstance(record.args, dict):
            sanitized = {}
            for k, v in record.args.items():
                if k.lower() in SENSITIVE_KEYS:
                    sanitized[k] = REPLACEMENT
                else:
                    sanitized[k] = v
            record.args = sanitized
        return True
