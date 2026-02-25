# get_works_magnet.py
import argparse
import random
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import LOGGER
from app.core.fetch_runtime import (
    FetchConfig,
    add_fetch_mode_arguments,
    create_fetcher,
    fetch_config_from_args,
    log_fetch_diagnostics,
    normalize_fetch_config,
)
from app.core.utils import build_soup
from app.core.utils import (
    clear_checkpoint,
    ensure_not_cancelled,
    load_checkpoint,
    load_cookie_dict,
    record_history,
    save_checkpoint,
    sleep_with_cancel,
)
from app.core.storage import Storage


def parse_magnets(html: str) -> List[Dict[str, Any]]:
    """
    解析 #magnets-content 下各条目：
      选择器：#magnets-content > div > div.magnet-name.column.is-four-fifths a[href]
      标签信息位于同一个 a 标签内的 div/span 结构。
    """
    soup = build_soup(html)
    magnets: List[Dict[str, Any]] = []
    root = soup.select_one("#magnets-content")
    if not root:
        LOGGER.warning("未找到 #magnets-content（可能被拦截或页面结构变更）")
        return magnets
    entries = root.select(":scope > div")
    if not entries:
        entries = root.find_all("div", recursive=False)

    for entry in entries:
        anchor = entry.select_one(
            "div.magnet-name.column.is-four-fifths a[href^='magnet:']"
        )
        if not anchor:
            anchor = entry.select_one("a[href^='magnet:']")
        if not anchor:
            continue
        href = anchor.get("href", "").strip()
        if not href.startswith("magnet:"):
            continue

        tag_nodes = anchor.select("div span")
        tag_values = []
        for span in tag_nodes:
            classes = span.get("class") or []
            if any(cls in ("name", "meta") for cls in classes):
                continue
            text = span.get_text(strip=True)
            if text:
                tag_values.append(text)
        size_node = anchor.select_one("span.meta")
        size_value = size_node.get_text(strip=True) if size_node else ""
        magnets.append({
            "href": href,
            "tags": tag_values,
            "size": size_value,
        })

    if not magnets:
        for a in root.select("a[href^='magnet:']"):
            href = a.get("href", "").strip()
            if href:
                magnets.append({
                    "href": href,
                    "tags": [],
                    "size": "",
                })

    seen = set()
    deduped: List[Dict[str, Any]] = []
    for item in magnets:
        key = item["href"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def crawl_magnets_for_row(fetcher, code: str, href: str, *, fetch_mode: str):
    result = fetcher.fetch(
        href,
        expected_selector="#magnets-content",
        stage="magnets",
    )
    log_fetch_diagnostics(fetch_mode, result)
    if result.blocked:
        raise RuntimeError(
            f"检测到疑似拦截页（status={result.status_code}, title={result.title}, reason={result.blocked_reason}）"
        )
    html = result.html
    magnets = parse_magnets(html)
    return magnets


def _normalize_filters(value: Optional[Sequence[str] | str]) -> list[str]:
    if value is None:
        return []

    raw_items: list[str] = []
    if isinstance(value, str):
        raw_items = value.replace("，", ",").split(",")
    else:
        for item in value:
            raw_items.extend(str(item).replace("，", ",").split(","))

    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _filter_works_by_code_keywords(
    works: list[dict[str, Any]], keywords: Sequence[str]
) -> list[dict[str, Any]]:
    if not keywords:
        return works
    keyword_set = [keyword.upper() for keyword in keywords if keyword]
    if not keyword_set:
        return works
    filtered: list[dict[str, Any]] = []
    for work in works:
        code = str(work.get("code", "")).upper()
        if any(keyword in code for keyword in keyword_set):
            filtered.append(work)
    return filtered


def _filter_works_by_series_prefixes(
    works: list[dict[str, Any]], prefixes: Sequence[str]
) -> list[dict[str, Any]]:
    if not prefixes:
        return works
    prefix_set = [prefix.upper() for prefix in prefixes if prefix]
    if not prefix_set:
        return works
    filtered: list[dict[str, Any]] = []
    for work in works:
        code = str(work.get("code", "")).upper()
        if any(code.startswith(prefix) for prefix in prefix_set):
            filtered.append(work)
    return filtered


def _apply_work_filters(
    all_works: dict[str, list[dict[str, Any]]],
    *,
    actor_filters: list[str],
    code_keywords: list[str],
    series_prefixes: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if actor_filters:
        return {
            name: all_works[name]
            for name in actor_filters
            if name in all_works and all_works[name]
        }
    if code_keywords:
        filtered: dict[str, list[dict[str, Any]]] = {}
        for actor, works in all_works.items():
            matched = _filter_works_by_code_keywords(works, code_keywords)
            if matched:
                filtered[actor] = matched
        return filtered
    if series_prefixes:
        filtered = {}
        for actor, works in all_works.items():
            matched = _filter_works_by_series_prefixes(works, series_prefixes)
            if matched:
                filtered[actor] = matched
        return filtered
    return all_works


def run_magnet_jobs(
    out_root: str = "userdata/magnets",
    cookie_json: str = "cookie.json",
    db_path: str = "userdata/actors.db",
    actor_name: Optional[Sequence[str] | str] = None,
    code_keywords: Optional[Sequence[str] | str] = None,
    series_prefixes: Optional[Sequence[str] | str] = None,
    fetch_config: FetchConfig | dict[str, Any] | None = None,
):
    """
    遍历数据库中的作品，抓取磁链并存入 SQLite 数据库文件。
    """
    resolved_fetch_config = normalize_fetch_config(fetch_config)
    cookies = load_cookie_dict(cookie_json)

    if out_root != "userdata/magnets":
        LOGGER.debug("out_root 参数仅用于 TXT 导出，与数据库写入无关：%s", out_root)

    with Storage(db_path) as store:
        all_works = store.get_all_actor_works()
        if not all_works:
            LOGGER.warning("数据库中未找到作品数据，请先执行作品抓取。")
            return {}

        actor_filters = _normalize_filters(actor_name)
        code_filters = _normalize_filters(code_keywords)
        series_filters = _normalize_filters(series_prefixes)
        has_scope_filter = bool(actor_filters or code_filters or series_filters)

        filtered_works = _apply_work_filters(
            all_works,
            actor_filters=actor_filters,
            code_keywords=code_filters,
            series_prefixes=series_filters,
        )

        if actor_filters:
            missing = [name for name in actor_filters if name not in all_works]
            if not filtered_works:
                LOGGER.warning("未找到指定演员：%s", ", ".join(actor_filters))
                return {}
            if missing:
                LOGGER.warning("部分演员未找到，将跳过：%s", ", ".join(missing))
            LOGGER.info("仅抓取指定演员：%s", ", ".join(filtered_works.keys()))
        elif code_filters:
            if not filtered_works:
                LOGGER.warning("未匹配到任何番号关键词：%s", ", ".join(code_filters))
                return {}
            LOGGER.info("启用番号筛选（contains）：%s", ", ".join(code_filters))
        elif series_filters:
            if not filtered_works:
                LOGGER.warning("未匹配到任何系列前缀：%s", ", ".join(series_filters))
                return {}
            LOGGER.info("启用系列筛选（prefix）：%s", ", ".join(series_filters))

        all_works = filtered_works

        if has_scope_filter:
            resume_actor = None
            resume_index = 0
        else:
            ckpt = load_checkpoint("magnets") or {}
            resume_actor = ckpt.get("actor")
            resume_index = int(ckpt.get("index", 0) or 0)
            if resume_actor:
                LOGGER.info(
                    "检测到断点，将从演员 %s 的第 %d 条作品继续。",
                    resume_actor,
                    resume_index + 1,
                )

        summary = {}
        with create_fetcher(cookies, resolved_fetch_config) as fetcher:
            actor_items = sorted(
                all_works.items(), key=lambda kv: kv[0].lower()
            )
            resume_mode = bool(resume_actor)
            for actor_name, works in actor_items:
                ensure_not_cancelled()
                if resume_mode and actor_name != resume_actor:
                    continue
                resume_mode = False
                actor_href = store.get_actor_href(actor_name) or ""
                LOGGER.info("开始抓取演员：%s", actor_name)
                magnet_counts = []
                start_index = resume_index if actor_name == resume_actor else 0
                for i, work in enumerate(
                    works[start_index:], start=start_index
                ):
                    ensure_not_cancelled()
                    code, href = work["code"], work["href"]
                    LOGGER.info(
                        "[%d/%d] %s -> %s", i + 1, len(works), code, href
                    )
                    try:
                        magnets = crawl_magnets_for_row(
                            fetcher,
                            code,
                            href,
                            fetch_mode=resolved_fetch_config.mode,
                        )
                        if not magnets:
                            LOGGER.warning("%s 未解析到磁力。", code)
                        saved = store.save_magnets(
                            actor_name,
                            actor_href,
                            code,
                            magnets,
                            title=work.get("title"),
                            href=href,
                        )
                        LOGGER.info(
                            "磁链已写入数据库 %s（更新 %d 条，抓取 %d 条）。",
                            db_path,
                            saved,
                            len(magnets),
                        )
                        magnet_counts.append(saved)
                        sleep_with_cancel(random.uniform(0.8, 1.6))
                    except RuntimeError:
                        raise
                    except Exception as e:
                        LOGGER.exception("%s 抓取失败：%s", code, e)
                    save_checkpoint(
                        "magnets", {
                            "actor": actor_name,
                            "index": i + 1
                        }
                    )
                summary[actor_name] = {
                    "works": len(works),
                    "magnets": sum(magnet_counts),
                }
        clear_checkpoint("magnets")
        record_history(
            "magnets",
            {
                "actors": len(summary),
                "works": sum(item["works"] for item in summary.values()),
                "magnets": sum(item["magnets"] for item in summary.values()),
            },
        )
    LOGGER.info("抓取磁链完成。")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="根据数据库中的作品抓取磁链并写入 SQLite 数据库")
    add_fetch_mode_arguments(parser)
    parser.add_argument(
        "--output-dir",
        default="userdata/magnets",
        help="TXT 导出目录（默认：userdata/magnets）",
    )
    parser.add_argument(
        "--cookie", default="cookie.json", help="Cookie JSON 路径，默认 cookie.json"
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default="userdata/actors.db",
        help="SQLite 数据库文件路径，默认 userdata/actors.db",
    )
    parser.add_argument(
        "--actor-name",
        "--actor_name",
        dest="actor_name",
        help="只抓取指定演员，可用逗号分隔多个（默认抓取全部，推荐 --actor-name）。",
        default=None,
    )
    args = parser.parse_args()

    run_magnet_jobs(
        out_root=args.output_dir,
        cookie_json=args.cookie,
        db_path=args.db_path,
        actor_name=args.actor_name,
        fetch_config=fetch_config_from_args(args),
    )
