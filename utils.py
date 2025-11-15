import csv
import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Set, Tuple, List
from urllib.parse import urljoin, urlparse, urlunparse, urlencode, parse_qsl
from bs4 import BeautifulSoup
import httpx


def setup_daily_file_logger(
    log_dir: str = "logs",
    *,
    date: Optional[datetime.date] = None,
    logger: Optional[logging.Logger] = None,
) -> Path:
    """
    为给定 logger 添加每日轮换的日志文件处理器，返回日志文件路径。
    """
    target_date = date or datetime.date.today()
    log_directory = Path(log_dir)
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / f"{target_date.isoformat()}.log"

    target_logger = logger or logging.getLogger()
    resolved_log_path = log_path.resolve()

    for handler in target_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            try:
                handler_path = Path(handler.baseFilename).resolve()
            except Exception:  # pragma: no cover - 安全兜底
                continue
            if handler_path == resolved_log_path:
                return log_path

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(formatter)
    target_logger.addHandler(file_handler)
    return log_path


from config import BASE_URL, LOGGER  # noqa: E402


# 解析cookie部分
def parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    """
    将 `a=b; c=d` 这种整串 Cookie 字符串解析成 dict。
    """
    pairs = (p.split("=", 1) for p in cookie_str.split(";") if "=" in p)
    return {k.strip(): v.strip() for k, v in pairs}


def load_cookie_dict(cookie_json_path: str = "cookie.json") -> Dict[str, Any]:
    """
    加载并归一化 cookie.json：
    1. {"cookie": "..."} -> 解析为 dict。
    2. 已经是 dict -> 原样返回。
    3. 其他情况 -> 返回空 dict。
    """
    with open(cookie_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "cookie" in data and isinstance(data["cookie"], str):
        return parse_cookie_string(data["cookie"])

    if isinstance(data, dict):
        return data

    return {}


def fetch_html(client: httpx.Client, url: str) -> str:
    r = client.get(url)
    # with open("debug.html", "w", encoding="utf-8") as f:
    #     f.write(r.text)
    return r.text


def find_next_url(html: str):
    soup = BeautifulSoup(html, "lxml")
    # “下一頁”按钮
    a = soup.find("a", string=lambda s: s and "下一頁" in s)
    return urljoin(BASE_URL, a["href"]) if a and a.has_attr("href") else None


# 写入actors.csv
def write_actors_csv(rows: Iterable[Mapping[str, Any]], csv_path: str) -> None:
    """
    将演员数据写入 CSV 文件，列为 actor_name 与 href；若目录不存在则自动创建。
    若文件存在，则追加内容并仅在文件为空时写入表头；已存在的行会跳过。
    """
    target = Path(csv_path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)

    existing_entries: Set[Tuple[str, str]] = set()
    batch_seen: Set[Tuple[str, str]] = set()
    file_exists = target.exists()
    file_empty = True
    if file_exists:
        file_empty = target.stat().st_size == 0
        if not file_empty:
            with target.open("r", encoding="utf-8-sig", newline="") as fp:
                reader = csv.reader(fp)
                next(reader, None)  # 丢弃表头
                for row in reader:
                    if len(row) >= 2:
                        existing_entries.add((row[0], row[1]))

    rows_to_write: List[Tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw_name = row.get("actor_name") or row.get("name") or row.get("strong") or ""
        name = raw_name.strip() if isinstance(raw_name, str) else str(raw_name).strip()
        href_val = row.get("href") or ""
        href = href_val.strip() if isinstance(href_val, str) else str(href_val).strip()
        if not name:
            continue
        entry = (name, href)
        if entry in existing_entries or entry in batch_seen:
            continue
        batch_seen.add(entry)
        rows_to_write.append(entry)

    if not rows_to_write:
        return

    with target.open("a", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        if file_empty:
            writer.writerow(["actor_name", "href"])
            file_empty = False
        writer.writerows(rows_to_write)
        existing_entries.update(batch_seen)


def sanitize_filename(value: str, default: str = "file") -> str:
    """
    将任意字符串转换为适合文件名的形式。
    """
    safe = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in value)
    safe = safe.strip().strip("_")
    return safe or default


def load_actor_urls(csv_path: str) -> List[Tuple[str, str]]:
    """
    从 CSV 中载入演员名称与链接，兼容 actor_name/name 与 href/url 字段。
    """
    actors: List[Tuple[str, str]] = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                name = (row.get("actor_name") or row.get("name") or "").strip()
                href = (row.get("href") or row.get("url") or "").strip()
                if name and href:
                    actors.append((name, href))
    except FileNotFoundError:
        LOGGER.error("未找到演员列表文件：%s", csv_path)
    return actors


def build_actor_url(
    base_url: str, href: str, tags: Sequence[str], sort_type: Optional[str]
) -> str:
    """
    根据标签/排序参数组合演员作品页 URL。
    """
    base = urljoin(base_url, href)
    parsed = urlparse(base)
    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key == "t" and tags:
            continue
        if key == "sort_type" and sort_type is not None:
            continue
        query_items.append((key, value))

    if tags:
        query_items.append(("t", ",".join(tags)))
    if sort_type is not None:
        query_items.append(("sort_type", sort_type))

    query = urlencode(query_items, doseq=True)
    return urlunparse(parsed._replace(query=query))


def write_magnets_csv(
    actor_name: str,
    code: str,
    magnets: Iterable[Mapping[str, Any]],
    out_root: str = "userdata/magnets",
) -> Path:
    actor_dir = Path(out_root) / sanitize_filename(str(actor_name), default="actor")
    actor_dir.mkdir(parents=True, exist_ok=True)
    file_path = actor_dir / f"{sanitize_filename(str(code), default='video')}.csv"

    existing_rows: List[Tuple[str, str, str]] = []
    existing_keys: Set[str] = set()
    if file_path.exists():
        with file_path.open("r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                magnet = (row.get("magnet") or row.get("href") or "").strip()
                if not magnet:
                    continue
                tags = (row.get("tags") or row.get("tag") or "").strip()
                size = (row.get("size") or "").strip()
                if magnet not in existing_keys:
                    existing_keys.add(magnet)
                    existing_rows.append((magnet, tags, size))

    new_rows: List[Tuple[str, str, str]] = []
    for item in magnets or []:
        if isinstance(item, Mapping):
            magnet = (item.get("href") or "").strip()
            if not magnet or magnet in existing_keys:
                continue
            tags_value = item.get("tags", "")
            if isinstance(tags_value, (list, tuple, set)):
                tags_str = ", ".join(str(t) for t in tags_value if t is not None)
            else:
                tags_str = str(tags_value) if tags_value is not None else ""
            size_str = (item.get("size") or "").strip()
            existing_keys.add(magnet)
            new_rows.append((magnet, tags_str, size_str))
        else:
            magnet = str(item).strip()
            if not magnet or magnet in existing_keys:
                continue
            existing_keys.add(magnet)
            new_rows.append((magnet, "", ""))

    if not existing_rows and not new_rows:
        return file_path

    with file_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["magnet", "tags", "size"])
        for magnet, tags_str, size_str in existing_rows + new_rows:
            writer.writerow([magnet, tags_str, size_str])
    return file_path
