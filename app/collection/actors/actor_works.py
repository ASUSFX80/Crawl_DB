# get_actor_works.py
import argparse
import random
from typing import Any, Optional, Sequence
from urllib.parse import urljoin

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
from app.core.utils import (
    build_actor_url,
    build_soup,
    clear_checkpoint,
    ensure_not_cancelled,
    find_next_url,
    load_checkpoint,
    load_cookie_dict,
    record_history,
    save_checkpoint,
    sleep_with_cancel,
)
from app.core.storage import Storage


def _base_url() -> str:
    return app_config.BASE_URL


def parse_works(html: str):
    """
    解析单个演员作品页（可包含筛选参数）中的作品卡片。
    你给的目标路径：
      body > section > div > div.movie-list.h.cols-4.vcols-8 > div(卡片) > a
      番号：a > div.video-title > strong
      标题：a > div.video-title (全部文本)
    """
    soup = build_soup(html)
    movie_grid = soup.select_one(
        "body > section > div > div.movie-list.h.cols-4.vcols-8"
    )
    if not movie_grid:
        # 兜底：类名顺序改变或有其它包裹层
        movie_grid = soup.select_one("div.movie-list.h.cols-4.vcols-8"
                                    ) or soup.select_one("div.movie-list")
    items = []
    if not movie_grid:
        LOGGER.warning("未找到作品列表容器 div.movie-list")
        return items

    cards = movie_grid.select(":scope > div")
    if not cards:
        cards = movie_grid.find_all("div", recursive=False)

    for card in cards:
        a = card.select_one("a[href]")
        if not a:
            continue
        href = urljoin(_base_url(), a["href"])
        strong = a.select_one("div.video-title > strong")
        code = strong.get_text(strip=True) if strong else ""
        title_node = a.select_one("div.video-title")
        title = title_node.get_text(" ", strip=True) if title_node else code
        if code:
            items.append({"code": code, "title": title, "href": href})
    return items


def crawl_actor_works(
    start_url: str,
    cookie_json: str = "cookie.json",
    known_codes: Optional[set[str]] = None,
    fetch_config: FetchConfig | dict[str, Any] | None = None,
):
    """
    从单个演员的作品页（可带筛选参数）开始抓取，保留筛选并自动翻页，返回完整作品列表。
    """
    known_codes = known_codes or set()
    resolved_fetch_config = normalize_fetch_config(fetch_config)
    cookies = load_cookie_dict(cookie_json)

    rows, page, url = [], 1, start_url
    with create_fetcher(cookies, resolved_fetch_config) as fetcher:
        LOGGER.info("开始抓取演员作品：%s", start_url)
        while url:
            ensure_not_cancelled()
            LOGGER.info("抓取第 %d 页: %s", page, url)
            result = fetcher.fetch(
                url,
                expected_selector="div.movie-list",
                stage="actor_works",
            )
            log_fetch_diagnostics(resolved_fetch_config.mode, result)
            html = result.html
            if result.blocked:
                raise RuntimeError(
                    f"检测到疑似拦截页（status={result.status_code}, title={result.title}, reason={result.blocked_reason}）"
                )
            works = parse_works(html)
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

            nxt = find_next_url(html)
            if nxt and nxt != url:
                url = nxt
                page += 1
                sleep_with_cancel(random.uniform(0.8, 1.6))
            else:
                url = None
    LOGGER.info("抓取演员作品完成，共 %d 条。", len(rows))
    return rows


def run_actor_works(
    db_path: str = "userdata/actors.db",
    tags: Optional[Sequence[str] | str] = None,
    cookie_json: str = "cookie.json",
    actor_name: Optional[Sequence[str] | str] = None,
    fetch_config: FetchConfig | dict[str, Any] | None = None,
):
    """
    批量读取演员列表，抓取作品并写入指定的 SQLite 数据库文件。
    """
    with Storage(db_path) as store:
        actors = store.iter_actor_urls()
        if not actors:
            LOGGER.warning("数据库中未找到演员数据，请先执行演员抓取。")
            return {}

        actor_filters: list[str] = []
        if actor_name is not None:
            if isinstance(actor_name, str):
                actor_filters = [
                    n.strip() for n in actor_name.split(",") if n.strip()
                ]
            else:
                actor_filters = [
                    str(n).strip() for n in actor_name if str(n).strip()
                ]

        if actor_filters:
            filtered = [
                (name, href) for name, href in actors if name in actor_filters
            ]
            missing = [
                name for name in actor_filters if name not in dict(actors)
            ]
            if not filtered:
                LOGGER.warning("未找到指定演员：%s", ", ".join(actor_filters))
                return {}
            if missing:
                LOGGER.warning("部分演员未找到，将跳过：%s", ", ".join(missing))
            actors = filtered
            LOGGER.info("仅抓取指定演员：%s", ", ".join(actor_filters))

        if isinstance(tags, str):
            tags_list = [t.strip() for t in tags.split(",") if t.strip()]
        elif tags:
            tags_list = [str(t).strip() for t in tags if t and str(t).strip()]
        else:
            tags_list = []

        summary = {}
        ckpt = load_checkpoint("actor_works") or {}
        # 针对指定演员抓取不复用旧断点，避免跨演员的 index 混淆
        if actor_filters:
            start_index = 0
        else:
            start_index = int(ckpt.get("index", 0) or 0)
            if start_index:
                LOGGER.info(
                    "检测到断点，将从第 %d 个演员继续（上次处理：%s）。",
                    start_index + 1,
                    ckpt.get("actor", ""),
                )

        for i, (actor_name,
                href) in enumerate(actors[start_index:], start=start_index):
            ensure_not_cancelled()
            existing_codes = {
                w["code"] for w in store.get_actor_works(actor_name)
            }
            start_url = build_actor_url(_base_url(), href, tags_list)
            LOGGER.info("开始处理演员：%s", actor_name)
            if tags_list:
                LOGGER.info("使用标签过滤：%s", ",".join(tags_list))

            works = crawl_actor_works(
                start_url=start_url,
                cookie_json=cookie_json,
                known_codes=existing_codes,
                fetch_config=fetch_config,
            )
            saved = store.save_actor_works(actor_name, href, works)
            LOGGER.info(
                "作品列表已写入数据库 %s（新增/更新 %d 条，抓取 %d 条）。",
                db_path,
                saved,
                len(works),
            )
            summary[actor_name] = {"count": len(works)}
            save_checkpoint(
                "actor_works", {
                    "actor": actor_name,
                    "index": i + 1
                }
            )

        clear_checkpoint("actor_works")
        record_history(
            "actor_works",
            {
                "actors": len(summary),
                "works_total": sum(item["count"] for item in summary.values()),
            },
        )

        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抓取演员作品并写入 SQLite 数据库")
    add_fetch_mode_arguments(parser)
    parser.add_argument(
        "--db",
        dest="db_path",
        default="userdata/actors.db",
        help="SQLite 数据库文件路径，默认 userdata/actors.db",
    )
    parser.add_argument(
        "--tags", help="用于筛选的标签代码，逗号分隔，例如 s 或 s,d", default=None
    )
    parser.add_argument(
        "--cookie", default="cookie.json", help="Cookie JSON 路径，默认 cookie.json"
    )
    parser.add_argument(
        "--actor-name",
        "--actor_name",
        dest="actor_name",
        help="仅抓取指定演员，可逗号分隔多名，不填则抓取全部（推荐 --actor-name）。",
        default=None,
    )
    args = parser.parse_args()

    run_actor_works(
        db_path=args.db_path,
        tags=args.tags,
        cookie_json=args.cookie,
        actor_name=args.actor_name,
        fetch_config=fetch_config_from_args(args),
    )
