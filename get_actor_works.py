# get_actor_works.py
import argparse
import time
import random
from typing import Sequence, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from config import BASE_URL, build_client, LOGGER
from utils import (
    load_cookie_dict,
    build_actor_url,
    find_next_url,
    fetch_html,
)
from storage import Storage


def parse_works(html: str):
    """
    解析单个演员作品页（可包含筛选参数）中的作品卡片。
    你给的目标路径：
      body > section > div > div.movie-list.h.cols-4.vcols-8 > div(卡片) > a
      番号：a > div.video-title > strong
      标题：a > div.video-title (全部文本)
    """
    soup = BeautifulSoup(html, "lxml")
    movie_grid = soup.select_one(
        "body > section > div > div.movie-list.h.cols-4.vcols-8"
    )
    if not movie_grid:
        # 兜底：类名顺序改变或有其它包裹层
        movie_grid = soup.select_one(
            "div.movie-list.h.cols-4.vcols-8"
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
        href = urljoin(BASE_URL, a["href"])
        strong = a.select_one("div.video-title > strong")
        code = strong.get_text(strip=True) if strong else ""
        title_node = a.select_one("div.video-title")
        title = title_node.get_text(" ", strip=True) if title_node else code
        if code:
            items.append({"code": code, "title": title, "href": href})
    return items


def crawl_actor_works(start_url: str, cookie_json: str = "cookie.json"):
    """
    从单个演员的作品页（可带筛选参数）开始抓取，保留筛选并自动翻页，返回完整作品列表。
    """
    cookies = load_cookie_dict(cookie_json)
    if not cookies:
        LOGGER.error("未能从 cookie.json 解析到有效 Cookie。")
        return []

    for must in ("over18", "cf_clearance", "_jdb_session"):
        if must not in cookies:
            LOGGER.warning("Cookie 缺少 %s，可能会遇到拦截。", must)

    rows, page, url = [], 1, start_url
    with build_client(cookies) as client:
        LOGGER.info("开始抓取演员作品：%s", start_url)
        while url:
            LOGGER.info("抓取第 %d 页: %s", page, url)
            html = fetch_html(client, url)
            works = parse_works(html)
            LOGGER.info("[page %d] 解析到作品 %d 条", page, len(works))
            if works:
                rows.extend(works)

            nxt = find_next_url(html)
            if nxt and nxt != url:
                url = nxt
                page += 1
                time.sleep(random.uniform(0.8, 1.6))
            else:
                url = None
    LOGGER.info("抓取演员作品完成，共 %d 条。", len(rows))
    return rows


def run_actor_works(
    db_path: str = "userdata/actors.db",
    tags: Optional[Sequence[str] | str] = None,
    sort_type: Optional[str] = None,
    cookie_json: str = "cookie.json",
):
    """
    批量读取演员列表，抓取作品并写入指定的 SQLite 数据库文件。
    """
    with Storage(db_path) as store:
        actors = store.iter_actor_urls()
        if not actors:
            LOGGER.warning("数据库中未找到演员数据，请先执行演员抓取。")
            return {}

        if isinstance(tags, str):
            tags_list = [t.strip() for t in tags.split(",") if t.strip()]
        elif tags:
            tags_list = [str(t).strip() for t in tags if t and str(t).strip()]
        else:
            tags_list = []

        selected_sort = (
            sort_type if sort_type is not None else ("0" if tags_list else None)
        )
        summary = {}

        for actor_name, href in actors:
            start_url = build_actor_url(BASE_URL, href, tags_list, selected_sort)
            LOGGER.info("开始处理演员：%s", actor_name)
            if tags_list:
                LOGGER.info("使用标签过滤：%s", ",".join(tags_list))
            if selected_sort is not None:
                LOGGER.info("使用 sort_type：%s", selected_sort)

            works = crawl_actor_works(start_url=start_url, cookie_json=cookie_json)
            saved = store.save_actor_works(actor_name, href, works)
            LOGGER.info(
                "作品列表已写入数据库 %s（新增/更新 %d 条，抓取 %d 条）。",
                db_path,
                saved,
                len(works),
            )
            summary[actor_name] = {"count": len(works)}

        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抓取演员作品并写入 SQLite 数据库")
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
        "--sort-type", help="作品排序方式，对应 sort_type 参数，例如 0", default=None
    )
    parser.add_argument(
        "--cookie", default="cookie.json", help="Cookie JSON 路径，默认 cookie.json"
    )
    args = parser.parse_args()

    run_actor_works(
        db_path=args.db_path,
        tags=args.tags,
        sort_type=args.sort_type,
        cookie_json=args.cookie,
    )
