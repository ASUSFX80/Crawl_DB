import argparse
import random
from typing import Any, Optional, Sequence

from collect_scopes import normalize_collect_scope
from config import LOGGER
from fetch_runtime import (
    FetchConfig,
    add_fetch_mode_arguments,
    create_fetcher,
    fetch_config_from_args,
    log_fetch_diagnostics,
    normalize_fetch_config,
)
from get_actor_works import parse_works
from storage import Storage
from utils import (
    clear_checkpoint,
    ensure_not_cancelled,
    find_next_url,
    load_checkpoint,
    load_cookie_dict,
    record_history,
    save_checkpoint,
    sleep_with_cancel,
)


def crawl_collection_works(
    start_url: str,
    *,
    cookie_json: str = "cookie.json",
    fetch_config: FetchConfig | dict[str, Any] | None = None,
) -> list[dict[str, str]]:
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

    rows: list[dict[str, str]] = []
    url = start_url
    page = 1
    with create_fetcher(cookies, resolved_fetch_config) as fetcher:
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
            rows.extend(works)
            next_url = find_next_url(result.html)
            if next_url and next_url != url:
                url = next_url
                page += 1
                sleep_with_cancel(random.uniform(0.8, 1.6))
            else:
                url = None
    return rows


def _normalize_filters(value: Optional[Sequence[str] | str]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def run_collection_works(
    *,
    db_path: str = "userdata/actors.db",
    cookie_json: str = "cookie.json",
    collect_scope: str = "series",
    collection_name: Optional[Sequence[str] | str] = None,
    fetch_config: FetchConfig | dict[str, Any] | None = None,
) -> dict[str, dict[str, int]]:
    scope = normalize_collect_scope(collect_scope)
    if scope == "actor":
        raise ValueError("actor 维度请使用 get_actor_works.py")
    filters = _normalize_filters(collection_name)
    checkpoint_name = f"collection_works:{scope}"
    summary: dict[str, dict[str, int]] = {}

    with Storage(db_path) as store:
        collections = store.iter_collections(scope)
        if filters:
            wanted = set(filters)
            collections = [(name, href) for name, href in collections if name in wanted]
            if not collections:
                LOGGER.warning("未匹配到收藏对象：%s", ",".join(filters))
                return {}

        ckpt = load_checkpoint(checkpoint_name) or {}
        start_index = int(ckpt.get("index", 0) or 0)
        for index, (name, href) in enumerate(collections[start_index:], start=start_index):
            ensure_not_cancelled()
            LOGGER.info("开始抓取收藏对象：%s（scope=%s）", name, scope)
            works = crawl_collection_works(
                href,
                cookie_json=cookie_json,
                fetch_config=fetch_config,
            )
            saved = store.save_collection_works(scope, name, href, works)
            LOGGER.info(
                "收藏作品已写入数据库 %s（scope=%s，name=%s，更新 %d 条）。",
                db_path,
                scope,
                name,
                saved,
            )
            summary[name] = {"count": len(works)}
            save_checkpoint(checkpoint_name, {"name": name, "index": index + 1})

    clear_checkpoint(checkpoint_name)
    record_history(
        checkpoint_name,
        {"collections": len(summary), "works_total": sum(v["count"] for v in summary.values())},
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抓取非演员收藏维度作品并写入 SQLite")
    add_fetch_mode_arguments(parser)
    parser.add_argument("--cookie", default="cookie.json", help="Cookie JSON 路径，默认 cookie.json")
    parser.add_argument("--db", dest="db_path", default="userdata/actors.db", help="SQLite 数据库路径")
    parser.add_argument(
        "--collect-scope",
        choices=["series", "maker", "director", "code"],
        default="series",
        help="收藏维度（非 actor）",
    )
    parser.add_argument(
        "--collection-name",
        default=None,
        help="仅抓取指定收藏对象名称，可逗号分隔多个。",
    )
    args = parser.parse_args()

    run_collection_works(
        db_path=args.db_path,
        cookie_json=args.cookie,
        collect_scope=args.collect_scope,
        collection_name=args.collection_name,
        fetch_config=fetch_config_from_args(args),
    )
