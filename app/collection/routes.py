"""JavDB 收藏维度路由配置。"""

from __future__ import annotations

from typing import Any

COLLECTION_SCOPE_CONFIG: dict[str, dict[str, Any]] = {
    "actor": {
        "list_path": "/users/collection_actors",
        "detail_prefix": "/actors/",
        "list_container": "#actors",
        "list_item_selector": ".box.actor-box",
    },
    "series": {
        "list_path": "/users/collection_series",
        "detail_prefix": "/series/",
        "list_container": "#series",
        "list_item_selector": ".box",
    },
    "maker": {
        "list_path": "/users/collection_makers",
        "detail_prefix": "/makers/",
        "detail_default_query": {
            "f": "download"
        },
        "list_container": "#makers",
        "list_item_selector": ".box",
    },
    "director": {
        "list_path": "/users/collection_directors",
        "detail_prefix": "/directors/",
        "list_container": "#directors",
        "list_item_selector": ".box",
    },
    "code": {
        "list_path": "/users/collection_codes",
        "detail_prefix": "/video_codes/",
        "list_container": "#codes",
        "list_item_selector": ".box",
    },
}


def get_scope_config(scope: str) -> dict[str, Any]:
    """返回指定收藏维度的路由配置。"""
    normalized_scope = str(scope or "").strip().lower()
    if normalized_scope not in COLLECTION_SCOPE_CONFIG:
        raise ValueError(f"不支持的收藏维度：{scope}")
    return dict(COLLECTION_SCOPE_CONFIG[normalized_scope])
