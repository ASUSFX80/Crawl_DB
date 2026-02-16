import logging
import httpx

BASE_URL = "https://javdb.com"
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


def build_client(cookies: dict) -> httpx.Client:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": BASE_URL + "/",
    }
    return httpx.Client(
        headers=headers, cookies=cookies, follow_redirects=True, timeout=30
    )
