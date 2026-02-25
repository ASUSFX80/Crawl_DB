import logging
import re
from urllib.parse import urlparse

import httpx

DEFAULT_BASE_DOMAIN_SEGMENT = "javdb"
BASE_URL = f"https://{DEFAULT_BASE_DOMAIN_SEGMENT}.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
LOGGER = logging.getLogger("crawljav")
from app.core.utils import setup_daily_file_logger  # noqa: E402

LOG_FILE_PATH = setup_daily_file_logger()


def normalize_base_domain_segment(raw_value: str | None) -> str:
    """宽松清洗用户输入，仅保留 // 与 .com 之间的中间段。"""
    value = (raw_value or "").strip().lower()
    if not value:
        return ""
    if "://" in value:
        value = value.split("://", 1)[1]
    if value.startswith("//"):
        value = value[2:]
    value = value.split("/", 1)[0]
    if value.endswith(".com"):
        value = value[:-len(".com")]
    return value.strip().strip(".")


def is_valid_base_domain_segment(raw_value: str | None) -> bool:
    """校验中间段是否可安全拼接为 https://{segment}.com。"""
    value = normalize_base_domain_segment(raw_value)
    if not value:
        return False
    if value.startswith(("-", ".")) or value.endswith(("-", ".")):
        return False
    if ".." in value:
        return False
    if not re.fullmatch(r"[a-z0-9.-]+", value):
        return False
    return True


def build_base_url(base_domain_segment: str | None) -> str:
    """根据中间段构建基础地址。"""
    segment = normalize_base_domain_segment(base_domain_segment)
    if not is_valid_base_domain_segment(segment):
        raise ValueError("站点域名无效")
    return f"https://{segment}.com"


def apply_base_domain_segment(base_domain_segment: str | None) -> str:
    """将中间段应用到全局 BASE_URL，并返回新值。"""
    global BASE_URL
    BASE_URL = build_base_url(base_domain_segment)
    return BASE_URL


def get_base_domain_segment() -> str:
    """从当前 BASE_URL 反推中间段。"""
    host = urlparse(BASE_URL).hostname or ""
    if host.endswith(".com"):
        return host[:-len(".com")]
    return host


def build_client(cookies: dict) -> httpx.Client:
    headers = {
        "User-Agent":
            UA,
        "Accept":
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":
            "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control":
            "no-cache",
        "Pragma":
            "no-cache",
        "Referer":
            BASE_URL + "/",
    }
    return httpx.Client(
        headers=headers, cookies=cookies, follow_redirects=True, timeout=30
    )
