"""全局常量定义。"""

from __future__ import annotations

# ── 管理会话 ──
SESSION_COOKIE_KEY: str = "toolhive_session"
SESSION_ID_BYTES: int = 32  # 256 位
SESSION_COOKIE_PATH: str = "/api/admin"

# ── Nonce ──
NONCE_BYTES: int = 16  # 128 位

# ── 临时密码 ──
TEMP_PASSWORD_BYTES: int = 24

# ── system_id ──
CALLER_SYSTEM_ID_PREFIX: str = "sys_"
