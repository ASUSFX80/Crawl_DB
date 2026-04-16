"""收藏维度作品磁链抓取。"""

from __future__ import annotations

import random
from typing import Any, Optional, Sequence

from app.collection.actors.actor_magnets import parse_magnets
from app.core.config import LOGGER
from app.core.fetch_runtime import (
    FetchConfig,
    create_fetcher,
    log_fetch_diagnostics,
    normalize_fetch_config,
)
from app.core.storage import Storage
from app.core.utils import (
    ensure_not_cancelled,
    load_cookie_dict,
    parse_delay_range,
    sleep_with_cancel,
)


def crawl_collection_magnets_for_row(
    fetcher, code: str, href: str, *, fetch_mode: str
):
    """抓取单个作品详情页中的磁链。"""
    result = fetcher.fetch(
        href,
        expected_selector="#magnets-content",
        stage="collection_magnets",
    )
    log_fetch_diagnostics(fetch_mode, result)
    if result.blocked:
        raise RuntimeError(
            f"检测到疑似拦截页（status={result.status_code}, title={result.title}, reason={result.blocked_reason}）"
        )
    return parse_magnets(result.html)


def _normalize_filters(value: Optional[Sequence[str] | str]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def run_collection_magnets(
    *,
    scope: str,
    cookie_json: str = "cookie.json",
    db_path: str = "userdata/actors.db",
    collection_name: Optional[Sequence[str] | str] = None,
    fetch_config: FetchConfig | dict[str, Any] | None = None,
) -> dict[str, list[int]]:
    """遍历 collection_works 并抓取对应磁链。"""
    resolved_fetch_config = normalize_fetch_config(fetch_config)
    cookies = load_cookie_dict(cookie_json)
    delay_low, delay_high = parse_delay_range(resolved_fetch_config.delay_range)

    with Storage(db_path) as store:
        all_works = store.get_all_collection_works(scope)
        if not all_works:
            LOGGER.warning("数据库中未找到收藏维度作品数据，请先执行作品抓取。")
            return {}

        collection_filters = _normalize_filters(collection_name)
        if collection_filters:
            all_works = {
                name: all_works[name]
                for name in collection_filters
                if name in all_works
            }
            if not all_works:
                LOGGER.warning("未找到指定收藏项：%s", ", ".join(collection_filters))
                return {}

        summary: dict[str, list[int]] = {}
        with create_fetcher(cookies, resolved_fetch_config) as fetcher:
            collection_items = sorted(
                all_works.items(), key=lambda item: item[0].lower()
            )
            for name, works in collection_items:
                ensure_not_cancelled()
                collection_href = store.get_collection_href(scope, name) or ""
                LOGGER.info("开始抓取收藏项磁链：scope=%s name=%s", scope, name)
                magnet_counts: list[int] = []
                for index, work in enumerate(works, start=1):
                    ensure_not_cancelled()
                    code = work["code"]
                    href = work["href"]
                    LOGGER.info(
                        "[%d/%d] %s -> %s", index, len(works), code, href
                    )
                    magnets = crawl_collection_magnets_for_row(
                        fetcher,
                        code,
                        href,
                        fetch_mode=resolved_fetch_config.mode,
                    )
                    if not magnets:
                        LOGGER.warning("%s 未解析到磁力。", code)
                    saved = store.save_collection_magnets(
                        scope,
                        name,
                        collection_href,
                        code,
                        magnets,
                        title=work.get("title"),
                        href=href,
                    )
                    magnet_counts.append(saved)
                    sleep_with_cancel(random.uniform(delay_low, delay_high))
                summary[name] = magnet_counts
        LOGGER.info("收藏维度磁链抓取完成：scope=%s", scope)
        return summary
