"""收藏维度通用抓取流水线。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from app.collection.collection_items import run_collect_items
from app.collection.collection_magnets import run_collection_magnets
from app.collection.collection_works import run_collection_works
from app.collection.routes import get_scope_config


@dataclass(frozen=True)
class CollectionPipeline:
    run_collect: Callable[..., Any]
    run_works: Callable[..., Any]
    run_magnets: Callable[..., Any]


def get_collection_pipeline(scope: str) -> CollectionPipeline:
    """返回指定收藏维度的通用抓取流水线。"""
    normalized_scope = get_scope_config(scope)
    resolved_scope = str(scope).strip().lower()
    del normalized_scope

    def _normalize_collection_filters(
        values: Sequence[str] | None,
    ) -> list[str] | None:
        if not values:
            return None
        normalized = [
            str(value).strip() for value in values if str(value).strip()
        ]
        return normalized or None

    def _run_collect(*, cookie_path: str, db_path: str, fetch_config: Any):
        return run_collect_items(
            scope=resolved_scope,
            cookie_json=cookie_path,
            db_path=db_path,
            fetch_config=fetch_config,
        )

    def _run_works(
        *,
        db_path: str,
        tags: str,
        cookie_path: str,
        filter_mode: str,
        filter_values: Sequence[str],
        fetch_config: Any,
    ):
        del tags, filter_mode
        return run_collection_works(
            scope=resolved_scope,
            db_path=db_path,
            cookie_json=cookie_path,
            collection_name=_normalize_collection_filters(filter_values),
            fetch_config=fetch_config,
        )

    def _run_magnets(
        *,
        output_dir: str,
        cookie_path: str,
        db_path: str,
        filter_mode: str,
        filter_values: Sequence[str],
        fetch_config: Any,
    ):
        del output_dir, filter_mode
        return run_collection_magnets(
            scope=resolved_scope,
            cookie_json=cookie_path,
            db_path=db_path,
            collection_name=_normalize_collection_filters(filter_values),
            fetch_config=fetch_config,
        )

    return CollectionPipeline(
        run_collect=_run_collect,
        run_works=_run_works,
        run_magnets=_run_magnets,
    )
