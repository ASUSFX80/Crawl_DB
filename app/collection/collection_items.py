"""收藏维度列表抓取与解析。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import app.core.config as app_config
from app.collection.routes import get_scope_config
from app.core.config import LOGGER
from app.core.fetch_runtime import (
    FetchConfig,
    create_fetcher,
    log_fetch_diagnostics,
    normalize_fetch_config,
)
from app.core.storage import Storage
from app.core.utils import (
    build_soup,
    ensure_not_cancelled,
    find_next_url,
    load_cookie_dict,
    parse_delay_range,
    sleep_with_cancel,
)


def _base_url() -> str:
    return app_config.BASE_URL


def _collection_list_url(scope: str) -> str:
    config = get_scope_config(scope)
    return f"{_base_url()}{config['list_path']}"


def parse_collection_items(scope: str, html: str) -> list[dict[str, str]]:
    """解析某个收藏维度页中的收藏项。"""
    config = get_scope_config(scope)
    soup = build_soup(html)
    rows: list[dict[str, str]] = []
    item_selector = f"{config['list_container']} {config['list_item_selector']}"
    for box in soup.select(item_selector):
        anchor = box.select_one("a[href]")
        strong = box.select_one("strong")
        if not anchor or not strong:
            continue
        href_raw = str(anchor.get("href") or "").strip()
        name = strong.get_text(strip=True)
        if not href_raw or not name:
            continue
        rows.append({
            "name": name,
            "href": urljoin(_base_url(), href_raw),
        })
    return rows


def crawl_collection_items(
    scope: str,
    cookie_json: str = "cookie.json",
    fetch_config: FetchConfig | dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """抓取指定收藏维度的全部收藏项。"""
    resolved_fetch_config = normalize_fetch_config(fetch_config)
    cookies = load_cookie_dict(cookie_json)
    delay_low, delay_high = parse_delay_range(resolved_fetch_config.delay_range)
    items: list[dict[str, str]] = []
    seen_hrefs: set[str] = set()

    with create_fetcher(cookies, resolved_fetch_config) as fetcher:
        url = _collection_list_url(scope)
        page = 1
        LOGGER.info("开始抓取收藏维度列表：scope=%s", scope)
        while url:
            ensure_not_cancelled()
            LOGGER.info("抓取第 %d 页: %s", page, url)
            result = fetcher.fetch(url, stage=f"collection_{scope}")
            log_fetch_diagnostics(resolved_fetch_config.mode, result)
            if result.blocked:
                raise RuntimeError(
                    f"检测到疑似拦截页（status={result.status_code}, title={result.title}, reason={result.blocked_reason}）"
                )
            page_items = parse_collection_items(scope, result.html)
            for item in page_items:
                href = item["href"]
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                items.append(item)
            next_url = find_next_url(result.html)
            if next_url and next_url != url:
                url = next_url
                page += 1
                sleep_with_cancel(
                    delay_high if delay_high == delay_low else delay_low
                )
            else:
                url = None

    LOGGER.info("收藏维度抓取完成：scope=%s，共 %d 条。", scope, len(items))
    return items


def run_collect_items(
    *,
    scope: str,
    cookie_json: str = "cookie.json",
    db_path: str = "userdata/actors.db",
    fetch_config: FetchConfig | dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """抓取收藏项并写入 collections 表。"""
    data = crawl_collection_items(
        scope=scope,
        cookie_json=cookie_json,
        fetch_config=fetch_config,
    )
    if data:
        with Storage(db_path) as store:
            saved = store.save_collections(scope, data)
        LOGGER.info("收藏维度已写入数据库 %s（更新 %d 条）。", db_path, saved)
    else:
        LOGGER.warning("未抓取到收藏维度数据：scope=%s", scope)
    return data
