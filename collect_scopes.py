from __future__ import annotations

from typing import Literal, cast

from config import BASE_URL

CollectScope = Literal["actor", "series", "maker", "director", "code"]

_SCOPE_PATHS: dict[CollectScope, str] = {
    "actor": "/users/collection_actors",
    "series": "/users/collection_series",
    "maker": "/users/collection_makers",
    "director": "/users/collection_directors",
    "code": "/users/collection_codes",
}

_SCOPE_SELECTORS: dict[CollectScope, str] = {
    "actor": "div#actors div.box.actor-box",
    "series": "section a[href]",
    "maker": "section a[href]",
    "director": "section a[href]",
    "code": "section a[href]",
}


def normalize_collect_scope(scope: str | None) -> CollectScope:
    text = str(scope or "").strip().lower()
    if text in _SCOPE_PATHS:
        return cast(CollectScope, text)
    return "actor"


def build_collect_start_url(scope: str | None) -> str:
    normalized = normalize_collect_scope(scope)
    return f"{BASE_URL}{_SCOPE_PATHS[normalized]}"


def expected_selector_for_scope(scope: str | None) -> str:
    normalized = normalize_collect_scope(scope)
    return _SCOPE_SELECTORS[normalized]
