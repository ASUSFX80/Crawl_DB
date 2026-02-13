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
from get_works_magnet import (
    _apply_work_filters,
    _normalize_filters,
    parse_magnets,
)
from storage import Storage
from utils import (
    clear_checkpoint,
    ensure_not_cancelled,
    load_checkpoint,
    load_cookie_dict,
    record_history,
    save_checkpoint,
    sleep_with_cancel,
)


def run_collection_magnets(
    *,
    db_path: str = "userdata/actors.db",
    cookie_json: str = "cookie.json",
    collect_scope: str = "series",
    collection_name: Optional[Sequence[str] | str] = None,
    code_keywords: Optional[Sequence[str] | str] = None,
    series_prefixes: Optional[Sequence[str] | str] = None,
    fetch_config: FetchConfig | dict[str, Any] | None = None,
) -> dict[str, dict[str, int]]:
    scope = normalize_collect_scope(collect_scope)
    if scope == "actor":
        raise ValueError("actor 维度请使用 get_works_magnet.py")

    resolved_fetch_config = normalize_fetch_config(fetch_config)
    cookies: dict[str, Any] = {}
    if resolved_fetch_config.mode == "httpx":
        cookies = load_cookie_dict(cookie_json)
        if not cookies:
            LOGGER.error("未能从 cookie.json 解析到有效 Cookie。")
            return {}
    else:
        try:
            cookies = load_cookie_dict(cookie_json)
        except SystemExit as exc:
            LOGGER.warning("浏览器模式未加载 Cookie，将优先使用持久化会话：%s", exc)
            cookies = {}

    actor_filters = _normalize_filters(collection_name)
    code_filters = _normalize_filters(code_keywords)
    series_filters = _normalize_filters(series_prefixes)
    checkpoint_name = f"collection_magnets:{scope}"

    with Storage(db_path) as store:
        all_works = store.get_all_collection_works(scope)
        filtered_works = _apply_work_filters(
            all_works,
            actor_filters=actor_filters,
            code_keywords=code_filters,
            series_prefixes=series_filters,
        )
        if not filtered_works:
            LOGGER.warning("未找到可抓取的收藏作品（scope=%s）。", scope)
            return {}

        ckpt = load_checkpoint(checkpoint_name) or {}
        resume_actor = ckpt.get("name")
        resume_index = int(ckpt.get("index", 0) or 0)

        summary: dict[str, dict[str, int]] = {}
        with create_fetcher(cookies, resolved_fetch_config) as fetcher:
            actor_items = sorted(filtered_works.items(), key=lambda kv: kv[0].lower())
            resume_mode = bool(resume_actor)
            for name, works in actor_items:
                ensure_not_cancelled()
                if resume_mode and name != resume_actor:
                    continue
                resume_mode = False
                collection_href = store.get_collection_href(scope, name) or ""
                start_index = resume_index if name == resume_actor else 0
                magnet_counts: list[int] = []
                for i, work in enumerate(works[start_index:], start=start_index):
                    ensure_not_cancelled()
                    code = work["code"]
                    href = work["href"]
                    LOGGER.info("[%d/%d] %s -> %s", i + 1, len(works), code, href)
                    result = fetcher.fetch(
                        href,
                        expected_selector="#magnets-content",
                        stage="collection_magnets",
                    )
                    log_fetch_diagnostics(resolved_fetch_config.mode, result)
                    if result.blocked:
                        raise RuntimeError(
                            f"检测到疑似拦截页（status={result.status_code}, title={result.title}, reason={result.blocked_reason}）"
                        )
                    magnets = parse_magnets(result.html)
                    saved = store.save_collection_magnets(
                        scope=scope,
                        collection_name=name,
                        collection_href=collection_href,
                        code=code,
                        magnets=magnets,
                        title=work.get("title"),
                        href=href,
                    )
                    magnet_counts.append(saved)
                    save_checkpoint(checkpoint_name, {"name": name, "index": i + 1})
                    sleep_with_cancel(random.uniform(0.8, 1.6))
                summary[name] = {"works": len(works), "magnets": sum(magnet_counts)}

    clear_checkpoint(checkpoint_name)
    record_history(
        checkpoint_name,
        {
            "collections": len(summary),
            "works": sum(v["works"] for v in summary.values()),
            "magnets": sum(v["magnets"] for v in summary.values()),
        },
    )
    LOGGER.info("收藏维度磁链抓取完成（scope=%s）。", scope)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抓取非演员收藏维度磁链并写入 SQLite")
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
    parser.add_argument(
        "--code-keywords",
        default=None,
        help="番号关键词（contains），逗号分隔。",
    )
    parser.add_argument(
        "--series-prefixes",
        default=None,
        help="番号前缀（startswith），逗号分隔。",
    )
    args = parser.parse_args()

    run_collection_magnets(
        db_path=args.db_path,
        cookie_json=args.cookie,
        collect_scope=args.collect_scope,
        collection_name=args.collection_name,
        code_keywords=args.code_keywords,
        series_prefixes=args.series_prefixes,
        fetch_config=fetch_config_from_args(args),
    )
