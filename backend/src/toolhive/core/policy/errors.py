"""D 使用公共错误语义；F 也复用同一错误定义。"""

from toolhive.core.errors import ToolHiveError as PolicyError

__all__ = ["PolicyError"]
