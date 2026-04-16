"""收藏维度详情页作品抓取。"""

from __future__ import annotations

import random
from typing import Any, Optional, Sequence
from urllib.parse import urljoin

import app.core.config as app_config
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


def parse_works(html: str) -> list[dict[str, str]]:
    """解析收藏维度详情页中的作品卡片。"""
    soup = build_soup(html)
    movie_grid = soup.select_one(
        "body > section > div > div.movie-list.h.cols-4.vcols-8"
    )
    if not movie_grid:
        movie_grid = soup.select_one("div.movie-list.h.cols-4.vcols-8"
                                    ) or soup.select_one("div.movie-list")
    items: list[dict[str, str]] = []
    if not movie_grid:
        LOGGER.warning("未找到作品列表容器 div.movie-list")
        return items

    cards = movie_grid.select(":scope > div")
    if not cards:
        cards = movie_grid.find_all("div", recursive=False)

    for card in cards:
        anchor = card.select_one("a[href]")
        if not anchor:
            continue
        href_raw = str(anchor.get("href") or "").strip()
        strong = anchor.select_one("div.video-title > strong")
        code = strong.get_text(strip=True) if strong else ""
        title_node = anchor.select_one("div.video-title")
        title = title_node.get_text(" ", strip=True) if title_node else code
        if not code or not href_raw:
            continue
        items.append({
            "code": code,
            "title": title,
            "href": urljoin(_base_url(), href_raw),
        })
    return items


def crawl_collection_works(
    start_url: str,
    cookie_json: str = "cookie.json",
    known_codes: Optional[set[str]] = None,
    fetch_config: FetchConfig | dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """从收藏维度详情页开始抓取作品列表。"""
    known_codes = known_codes or set()
    resolved_fetch_config = normalize_fetch_config(fetch_config)
    cookies = load_cookie_dict(cookie_json)
    delay_low, delay_high = parse_delay_range(resolved_fetch_config.delay_range)

    rows: list[dict[str, str]] = []
    page = 1
    url = start_url
    with create_fetcher(cookies, resolved_fetch_config) as fetcher:
        LOGGER.info("开始抓取收藏维度作品：%s", start_url)
        while url:
            ensure_not_cancelled()
            LOGGER.info("抓取第 %d 页: %s", page, url)
            result = fetcher.fetch(
                url,
                expected_selector="div.movie-list",
                stage="collection_works",
            )
            log_fetch_diagnostics(resolved_fetch_config.mode, result)
            if result.blocked:
                raise RuntimeError(
                    f"检测到疑似拦截页（status={result.status_code}, title={result.title}, reason={result.blocked_reason}）"
                )

            works = parse_works(result.html)
            LOGGER.info("[page %d] 解析到作品 %d 条", page, len(works))
            hit_known = False
            for item in works:
                if item["code"] in known_codes:
                    hit_known = True
                    break
                rows.append(item)
            if hit_known:
                LOGGER.info("遇到已收录作品，基于新→旧排序提前停止翻页。")
                break

            next_url = find_next_url(result.html)
            if next_url and next_url != url:
                url = next_url
                page += 1
                sleep_with_cancel(random.uniform(delay_low, delay_high))
            else:
                url = None

    LOGGER.info("抓取收藏维度作品完成，共 %d 条。", len(rows))
    return rows


def run_collection_works(
    *,
    scope: str,
    db_path: str = "userdata/actors.db",
    cookie_json: str = "cookie.json",
    collection_name: Optional[Sequence[str] | str] = None,
    fetch_config: FetchConfig | dict[str, Any] | None = None,
) -> dict[str, dict[str, int]]:
    """批量抓取某个收藏维度下各收藏项的作品。"""
    with Storage(db_path) as store:
        collections = store.iter_collections(scope)
        if not collections:
            LOGGER.warning("数据库中未找到收藏维度数据，请先执行收藏抓取。")
            return {}

        collection_filters: list[str] = []
        if collection_name is not None:
            if isinstance(collection_name, str):
                collection_filters = [
                    value.strip()
                    for value in collection_name.split(",")
                    if value.strip()
                ]
            else:
                collection_filters = [
                    str(value).strip()
                    for value in collection_name
                    if str(value).strip()
                ]

        if collection_filters:
            filtered = [(name, href)
                        for name, href in collections
                        if name in collection_filters]
            if not filtered:
                LOGGER.warning("未找到指定收藏项：%s", ", ".join(collection_filters))
                return {}
            collections = filtered

        existing_works = store.get_all_collection_works(scope)
        summary: dict[str, dict[str, int]] = {}
        for name, href in collections:
            ensure_not_cancelled()
            known_codes = {row["code"] for row in existing_works.get(name, [])}
            LOGGER.info("开始处理收藏项：scope=%s name=%s", scope, name)
            works = crawl_collection_works(
                start_url=href,
                cookie_json=cookie_json,
                known_codes=known_codes,
                fetch_config=fetch_config,
            )
            saved = store.save_collection_works(scope, name, href, works)
            LOGGER.info(
                "收藏维度作品已写入数据库 %s（scope=%s，更新 %d 条，抓取 %d 条）。",
                db_path,
                scope,
                saved,
                len(works),
            )
            summary[name] = {"count": len(works)}

        return summary
