import datetime
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup, FeatureNotFound

PLAYWRIGHT_COOKIE_ITEMS_KEY = "__playwright_cookie_items__"


class CancelledError(RuntimeError):
    pass


_cancel_checker = None
_soup_fallback_warned = False


def set_cancel_checker(checker) -> None:
    global _cancel_checker
    _cancel_checker = checker


def _check_cancel() -> None:
    if _cancel_checker and _cancel_checker():
        raise CancelledError("操作已取消")


def ensure_not_cancelled() -> None:
    """对外暴露取消检查，供长循环任务在关键节点调用。"""
    _check_cancel()


def sleep_with_cancel(seconds: float, *, step_seconds: float = 0.1) -> None:
    """
    可响应取消的 sleep：将长等待拆分为短间隔并在间隔间检查取消信号。
    """
    if seconds <= 0:
        _check_cancel()
        return

    step = max(0.01, step_seconds)
    deadline = time.monotonic() + seconds
    while True:
        _check_cancel()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(step, remaining))


def _get_logger():
    from app.core.config import LOGGER

    return LOGGER


def _get_base_url() -> str:
    from app.core.config import BASE_URL

    return BASE_URL


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
    try:
        log_directory.mkdir(parents=True, exist_ok=True)
    except OSError as primary_error:
        fallback_dir = Path.home() / ".crawljav" / "logs"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        logging.getLogger(__name__).warning(
            "日志目录不可写，已回退到用户目录: %s (原因: %s)",
            fallback_dir,
            primary_error,
        )
        log_directory = fallback_dir
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
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
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
    3. 文件缺失或格式异常 -> 友好提示并返回空 dict。
    """
    path = Path(cookie_json_path)
    if not path.exists():
        raise SystemExit(f"未找到 Cookie 文件：{cookie_json_path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"读取 Cookie 文件失败：{cookie_json_path}（{exc}）")

    if isinstance(data, dict
                 ) and "cookie" in data and isinstance(data["cookie"], str):
        cookies = parse_cookie_string(data["cookie"])
    elif (
        isinstance(data, dict) and "cookies" in data
        and isinstance(data["cookies"], list)
    ):
        cookie_items = [
            item for item in data["cookies"] if isinstance(item, dict)
        ]
        cookies = _cookie_items_to_name_value_dict(cookie_items)
        cookies[PLAYWRIGHT_COOKIE_ITEMS_KEY] = cookie_items
    elif isinstance(data, list):
        cookie_items = [item for item in data if isinstance(item, dict)]
        if len(cookie_items) != len(data):
            raise SystemExit(
                f"Cookie 文件格式无效，期望 cookies 为对象数组：{cookie_json_path}"
            )
        cookies = _cookie_items_to_name_value_dict(cookie_items)
        cookies[PLAYWRIGHT_COOKIE_ITEMS_KEY] = cookie_items
    elif isinstance(data, dict):
        cookies = data
    else:
        raise SystemExit(f"Cookie 文件格式无效，期望 JSON 对象：{cookie_json_path}")

    log_cookie_staleness(cookie_json_path)
    if not is_cookie_valid(cookies):
        raise SystemExit("Cookie 缺少关键字段或为空，退出。")
    return cookies


def _cookie_items_to_name_value_dict(
    cookie_items: Sequence[Dict[str, Any]]
) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for item in cookie_items:
        name = str(item.get("name", "")).strip()
        value = item.get("value")
        if not name or value is None:
            continue
        cookies[name] = str(value)
    return cookies


def log_cookie_staleness(cookie_json_path: str, warn_days: int = 3) -> None:
    """
    简单检查 cookie 文件的修改时间，超过 warn_days 天则提示可能过期。
    仅作为提醒，无法替代站点验证。
    """
    path = Path(cookie_json_path)
    if not path.exists():
        return
    try:
        age_days = (
            datetime.datetime.now() -
            datetime.datetime.fromtimestamp(path.stat().st_mtime)
        ).days
    except OSError:
        return
    if age_days >= warn_days:
        _get_logger().warning(
            "Cookie 文件已超过 %d 天未更新，可能已过期：%s", warn_days, cookie_json_path
        )


def is_cookie_valid(cookies: Dict[str, Any]) -> bool:
    """
    粗判 Cookie 是否“看起来可用”：
    - 至少包含 cf_clearance/_jdb_session/over18（或等价字段）
    - 值非空
    实际有效性仍需请求验证。
    """
    required = ("cf_clearance", "_jdb_session", "over18")
    missing = [k for k in required if not cookies.get(k)]
    if missing:
        _get_logger().warning("❌Cookie 无效!")
        return False
    return True


def fetch_html(client: httpx.Client, url: str) -> str:
    _check_cancel()
    r = client.get(url)
    # with open("debug.html", "w", encoding="utf-8") as f:
    #     f.write(r.text)
    return r.text


def build_soup(html: str) -> BeautifulSoup:
    """
    构建 HTML 解析树：优先 lxml，不可用时回退 html.parser。
    """
    global _soup_fallback_warned
    try:
        return BeautifulSoup(html, "lxml")
    except FeatureNotFound:
        if not _soup_fallback_warned:
            _get_logger().warning("lxml 不可用，已回退到 html.parser。")
            _soup_fallback_warned = True
        return BeautifulSoup(html, "html.parser")


def find_next_url(html: str):
    soup = build_soup(html)
    # “下一頁”按钮
    a = soup.find("a", string=lambda s: s and "下一頁" in s)
    base_url = _get_base_url()
    return urljoin(base_url, a["href"]) if a and a.has_attr("href") else None


# --- 抓取过程记录工具 -------------------------------------------------


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _get_logger().warning("解析历史文件失败，将重置：%s", path)
        return dict(default)


def record_history(
    event: str,
    payload: Optional[Dict[str, Any]] = None,
    history_path: str = "userdata/history.jsonl",
) -> None:
    """
    追加一条抓取历史记录，便于后续查看“上次爬到哪”。
    建议在每个阶段（演员列表、作品列表等）结束后调用一次。
    """
    path = Path(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "event": event,
    }
    if payload:
        entry.update(payload)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_recent_history(
    event: Optional[str] = None,
    limit: int = 5,
    history_path: str = "userdata/history.jsonl"
) -> list[Dict[str, Any]]:
    """
    读取最近的历史记录，可按 event 过滤。
    """
    path = Path(history_path)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    if event:
        records = [r for r in records if r.get("event") == event]
    return records[-limit:]


def save_checkpoint(
    name: str,
    cursor: Dict[str, Any],
    ckpt_path: str = "userdata/checkpoints.json"
) -> None:
    """
    保存分阶段的“断点”信息，例如：
      save_checkpoint("actor_works", {"actor": actor_name, "index": i})
    便于下次启动时知道上次处理到谁/第几条。
    """
    path = Path(ckpt_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_json(path, default={})
    data[name] = {
        "cursor": cursor,
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_checkpoint(
    name: str,
    ckpt_path: str = "userdata/checkpoints.json"
) -> Optional[Dict[str, Any]]:
    """
    读取指定阶段的断点信息；找不到则返回 None。
    """
    path = Path(ckpt_path)
    data = _read_json(path, default={})
    entry = data.get(name)
    if not entry:
        return None
    return entry.get("cursor")


def clear_checkpoint(
    name: str, ckpt_path: str = "userdata/checkpoints.json"
) -> None:
    """
    清除某个阶段的断点，便于重新全量抓取。
    """
    path = Path(ckpt_path)
    if not path.exists():
        return
    data = _read_json(path, default={})
    if name in data:
        data.pop(name, None)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def sanitize_filename(value: str, default: str = "file") -> str:
    """
    将任意字符串转换为适合文件名的形式。
    """
    safe = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in value)
    safe = safe.strip().strip("_")
    return safe or default


def build_actor_url(base_url: str, href: str, tags: Sequence[str]) -> str:
    """
    根据标签/排序参数组合演员作品页 URL。
    """
    base = urljoin(base_url, href)
    parsed = urlparse(base)
    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key == "t" and tags:
            continue
        query_items.append((key, value))

    if tags:
        query_items.append(("t", ",".join(tags)))

    query = urlencode(query_items, doseq=True)
    return urlunparse(parsed._replace(query=query))
