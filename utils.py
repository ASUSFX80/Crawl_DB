import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from urllib.parse import urljoin, urlparse, urlunparse, urlencode, parse_qsl
from bs4 import BeautifulSoup
import httpx
from config import BASE_URL, LOGGER 

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


def sanitize_filename(value: str, default: str = "file") -> str:
    """
    将任意字符串转换为适合文件名的形式。
    """
    safe = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in value)
    safe = safe.strip().strip("_")
    return safe or default


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
