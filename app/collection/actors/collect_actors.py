import argparse
import hashlib
import random
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

import app.core.config as app_config
from app.core.config import LOGGER
from app.core.fetch_runtime import (
    FetchConfig,
    add_fetch_mode_arguments,
    create_fetcher,
    fetch_config_from_args,
    log_fetch_diagnostics,
    normalize_fetch_config,
)
from app.core.storage import Storage
from app.core.utils import (
    build_soup,
    ensure_not_cancelled,
    find_next_url,
    load_cookie_dict,
    sleep_with_cancel,
)

_ACTOR_COLLECTION_SELECTOR = "div#actors div.box.actor-box"


def _base_url() -> str:
    return app_config.BASE_URL


def _actor_collection_url() -> str:
    return f"{_base_url()}/users/collection_actors"


def _build_soup(html: str) -> BeautifulSoup:
    """构建 BeautifulSoup 解析树。"""
    return build_soup(html)


def _is_interstitial_page(soup: BeautifulSoup) -> bool:
    """判断是否疑似拦截页。"""
    return soup.find("section") is None


def _log_interstitial_hint(soup: BeautifulSoup) -> None:
    """对疑似拦截页输出提示日志。"""
    if _is_interstitial_page(soup):
        LOGGER.warning(
            "解析提示：页面里没有 <section>，很可能是 Cloudflare/登录拦截页或 Cookie 失效。"
        )


def _extract_actor_boxes(soup: BeautifulSoup) -> list[Tag]:
    """提取演员卡片节点列表。"""
    return soup.select("div#actors div.box.actor-box")


def _parse_actor_box(box: Tag) -> Optional[dict[str, str]]:
    """解析单个演员卡片为结构化数据。"""
    anchor = box.select_one("a[href]")
    if not anchor:
        return None
    href_raw = anchor.get("href") or ""
    href = urljoin(_base_url(), href_raw) if href_raw else ""
    strong = box.select_one("strong")
    name = strong.get_text(strip=True) if strong else anchor.get_text(strip=True)
    if not href or not name:
        return None
    return {"href": href, "strong": name}


def _parse_actors_from_soup(soup: BeautifulSoup) -> list[dict[str, str]]:
    """从 soup 中解析演员信息。"""
    boxes = _extract_actor_boxes(soup)
    items: list[dict[str, str]] = []
    for box in boxes:
        record = _parse_actor_box(box)
        if record:
            items.append(record)
    return items


def _save_response_dump(html: str, response_dump_path: Optional[str]) -> None:
    """将当次响应页面保存到本地文件。"""
    if not response_dump_path:
        return
    path = Path(response_dump_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    LOGGER.info("响应页面已保存：%s", path)


def _compare_with_baseline(html: str, compare_with_path: Optional[str]) -> None:
    """将当次响应与基准页面做文本级对比并输出摘要。"""
    if not compare_with_path:
        return
    path = Path(compare_with_path)
    if not path.exists():
        LOGGER.warning("对比基准页面不存在：%s", path)
        return
    baseline = path.read_text(encoding="utf-8")
    runtime_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()[:12]
    baseline_hash = hashlib.sha256(baseline.encode("utf-8")).hexdigest()[:12]
    same = html == baseline
    LOGGER.info(
        "对比基准页面结果：%s（当前长度=%d，基准长度=%d，当前sha256=%s，基准sha256=%s）",
        "一致" if same else "不一致",
        len(html),
        len(baseline),
        runtime_hash,
        baseline_hash,
    )


def parse_actors(html: str) -> list[dict[str, str]]:
    """解析收藏演员页面，返回演员信息列表。"""
    soup = _build_soup(html)
    _log_interstitial_hint(soup)
    return _parse_actors_from_soup(soup)


def crawl_all_pages(
    cookie_json: str = "cookie.json",
    response_dump_path: Optional[str] = None,
    compare_with_path: Optional[str] = None,
    collect_scope: str = "actor",
    fetch_config: FetchConfig | dict[str, Any] | None = None,
):
    del collect_scope
    resolved_fetch_config = normalize_fetch_config(fetch_config)

    cookies: dict[str, Any] = {}
    if resolved_fetch_config.mode == "httpx":
        cookies = load_cookie_dict(cookie_json)
        if not cookies:
            LOGGER.error("未能从 cookie.json 解析到有效 Cookie。")
            return []
    else:
        try:
            cookies = load_cookie_dict(cookie_json)
        except SystemExit as exc:
            LOGGER.warning("浏览器模式未加载 Cookie，将优先使用持久化会话：%s", exc)
            cookies = {}

    if resolved_fetch_config.mode == "httpx" or cookies:
        for must in ("over18", "cf_clearance", "_jdb_session"):
            if must not in cookies:
                LOGGER.warning("Cookie 里没有 %s，可能会被拦截。", must)

    items: list[dict[str, str]] = []
    seen_hrefs: set[str] = set()
    with create_fetcher(cookies, resolved_fetch_config) as fetcher:
        url = _actor_collection_url()
        page = 1
        LOGGER.info("开始抓取收藏演员列表")
        while url:
            ensure_not_cancelled()
            LOGGER.info("抓取第 %d 页: %s", page, url)
            result = fetcher.fetch(
                url,
                expected_selector=_ACTOR_COLLECTION_SELECTOR,
                stage="collect_actors",
            )
            log_fetch_diagnostics(resolved_fetch_config.mode, result)
            html = result.html
            if page == 1:
                _save_response_dump(html, response_dump_path)
                _compare_with_baseline(html, compare_with_path)
            if result.blocked:
                raise RuntimeError(
                    f"检测到疑似拦截页（status={result.status_code}, title={result.title}, reason={result.blocked_reason}）"
                )
            soup = _build_soup(html)
            _log_interstitial_hint(soup)
            actors = _parse_actors_from_soup(soup)

            new_items: list[dict[str, str]] = []
            for actor in actors:
                href = actor.get("href", "")
                if not href or href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                new_items.append(actor)

            LOGGER.info(
                "[page %d] 解析收藏演员 %d 条（新增 %d 条）",
                page,
                len(actors),
                len(new_items),
            )
            items.extend(new_items)

            if not actors and _is_interstitial_page(soup):
                LOGGER.warning("检测到疑似拦截页，停止翻页。")
                break

            next_url = find_next_url(html)
            if next_url and next_url != url:
                url = next_url
                page += 1
                sleep_with_cancel(random.uniform(0.8, 1.6))
            else:
                url = None
    LOGGER.info("爬取收藏演员完成，共 %d 条。", len(items))
    return items


def run_collect_actors(
    cookie_json: str = "cookie.json",
    db_path: str = "userdata/actors.db",
    response_dump_path: Optional[str] = None,
    compare_with_path: Optional[str] = None,
    collect_scope: str = "actor",
    fetch_config: FetchConfig | dict[str, Any] | None = None,
):
    """抓取收藏演员列表并写入 SQLite 数据库文件，返回抓取结果列表。"""
    del collect_scope
    data = crawl_all_pages(
        cookie_json,
        response_dump_path=response_dump_path,
        compare_with_path=compare_with_path,
        fetch_config=fetch_config,
    )
    LOGGER.info("收藏演员抓取结果：%d 条。", len(data))
    if data:
        with Storage(db_path) as store:
            saved = store.save_actors(data)
        LOGGER.info("收藏演员已写入数据库 %s（更新 %d 条）。", db_path, saved)
    else:
        LOGGER.warning("未抓取到演员数据，未写入文件。")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抓取收藏演员列表并写入 SQLite 数据库")
    add_fetch_mode_arguments(parser)
    parser.add_argument(
        "--cookie", default="cookie.json", help="Cookie JSON 路径，默认 cookie.json"
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default="userdata/actors.db",
        help="SQLite 数据库文件路径，默认 userdata/actors.db。",
    )
    parser.add_argument(
        "--response-dump-path",
        default=None,
        help="可选：将第 1 页响应 HTML 保存到指定路径（如 debug/collection_actors_runtime.html）。",
    )
    parser.add_argument(
        "--compare-with-path",
        default=None,
        help="可选：与指定基准 HTML 做文本对比（如 debug/collection_actors.html）。",
    )
    args = parser.parse_args()

    run_collect_actors(
        cookie_json=args.cookie,
        db_path=args.db_path,
        response_dump_path=args.response_dump_path,
        compare_with_path=args.compare_with_path,
        fetch_config=fetch_config_from_args(args),
    )
