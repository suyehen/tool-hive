"""范围集合去重的共享逻辑测试（调用系统 / MCP 客户端共用）。"""

from __future__ import annotations

from toolhive.services.catalog_scope_validator import dedupe_scope_items


def test_dedupe_scope_items_removes_duplicates() -> None:
    """同一 (scope_type, scope_code) 只保留首次出现。"""
    items = [
        {"scope_type": "tool", "scope_code": "math.basic.add", "status": "active"},
        {"scope_type": "tool", "scope_code": "math.basic.add", "status": "active"},
        {"scope_type": "tool", "scope_code": "math.basic.sub", "status": "active"},
    ]
    deduped = dedupe_scope_items(items)
    assert [item["scope_code"] for item in deduped] == [
        "math.basic.add",
        "math.basic.sub",
    ]


def test_dedupe_scope_items_ignores_surrounding_whitespace() -> None:
    """编码首尾空白不产生新的范围行。"""
    items = [
        {"scope_type": "tool", "scope_code": " math.basic.add ", "status": "active"},
        {"scope_type": "tool", "scope_code": "math.basic.add", "status": "active"},
    ]
    assert len(dedupe_scope_items(items)) == 1


def test_dedupe_scope_items_keeps_distinct_types() -> None:
    """同编码但范围类型不同属于两条独立范围。"""
    items = [
        {"scope_type": "tool", "scope_code": "math.basic", "status": "active"},
        {"scope_type": "namespace", "scope_code": "math.basic", "status": "active"},
    ]
    assert len(dedupe_scope_items(items)) == 2
