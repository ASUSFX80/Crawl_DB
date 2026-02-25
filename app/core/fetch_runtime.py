from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping, Protocol, Sequence, cast
from urllib.parse import urlparse

import app.core.config as app_config
from app.core.config import LOGGER, build_client
from app.core.utils import build_soup, ensure_not_cancelled

try:  # pragma: no cover - 运行环境兜底
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - 无 playwright 依赖时兜底
    PlaywrightTimeoutError = RuntimeError
    sync_playwright = None

FetchMode = Literal["httpx", "browser"]
PLAYWRIGHT_COOKIE_ITEMS_KEY = "__playwright_cookie_items__"


@dataclass
class FetchConfig:
    mode: FetchMode = "browser"
    browser_user_data_dir: str = "userdata/browser_profile/javdb"
    browser_headless: bool = False
    browser_timeout_seconds: int = 30
    challenge_timeout_seconds: int = 180
    browser_channel: str | None = None


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int | None
    title: str
    html: str
    blocked: bool
    blocked_reason: str | None


class PageFetcher(Protocol):

    def fetch(
        self,
        url: str,
        expected_selector: str | None = None,
        stage: str | None = None,
    ) -> FetchResult:
        ...


def add_fetch_mode_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fetch-mode",
        choices=["httpx", "browser"],
        default="browser",
        help=(
            "抓取模式：browser（默认，Playwright 持久化会话）或 httpx。"
        ),
    )
    parser.add_argument(
        "--browser-user-data-dir",
        default="userdata/browser_profile/javdb",
        help="浏览器模式下的持久化会话目录。",
    )
    parser.add_argument(
        "--browser-headless",
        action="store_true",
        help="浏览器模式使用无头运行（默认关闭）。",
    )
    parser.add_argument(
        "--browser-timeout-seconds",
        type=int,
        default=30,
        help="浏览器单次页面加载超时时间（秒）。",
    )
    parser.add_argument(
        "--challenge-timeout-seconds",
        type=int,
        default=180,
        help="浏览器模式等待人工完成验证/登录的超时时间（秒）。",
    )


def fetch_config_from_args(args: argparse.Namespace) -> FetchConfig:
    return FetchConfig(
        mode=cast(FetchMode, getattr(args, "fetch_mode", "browser")),
        browser_user_data_dir=str(
            getattr(
                args, "browser_user_data_dir", "userdata/browser_profile/javdb"
            )
        ),
        browser_headless=bool(getattr(args, "browser_headless", False)),
        browser_timeout_seconds=int(
            getattr(args, "browser_timeout_seconds", 30)
        ),
        challenge_timeout_seconds=int(
            getattr(args, "challenge_timeout_seconds", 180)
        ),
    )


def normalize_fetch_config(
    fetch_config: FetchConfig | Mapping[str, Any] | None
) -> FetchConfig:
    if fetch_config is None:
        return FetchConfig()
    if isinstance(fetch_config, FetchConfig):
        return fetch_config

    mode = str(fetch_config.get("mode", "browser"))
    if mode not in ("httpx", "browser"):
        mode = "browser"
    return FetchConfig(
        mode=cast(FetchMode, mode),
        browser_user_data_dir=str(
            fetch_config.get(
                "browser_user_data_dir", "userdata/browser_profile/javdb"
            )
        ),
        browser_headless=bool(fetch_config.get("browser_headless", False)),
        browser_timeout_seconds=int(
            fetch_config.get("browser_timeout_seconds", 30)
        ),
        challenge_timeout_seconds=int(
            fetch_config.get("challenge_timeout_seconds", 180)
        ),
        browser_channel=(
            str(fetch_config["browser_channel"])
            if fetch_config.get("browser_channel") else None
        ),
    )


def is_blocked_page(
    html: str,
    title: str,
    status_code: int | None,
) -> tuple[bool, str | None]:
    if status_code == 403:
        return True, "status_403"

    title_lower = title.lower()
    if "cloudflare" in title_lower or "attention required" in title_lower:
        return True, "title_cloudflare"

    body_lower = html.lower()
    patterns = (
        "cf-wrapper",
        "sorry, you have been blocked",
        "cloudflare ray id",
    )
    for marker in patterns:
        if marker in body_lower:
            return True, f"html:{marker}"

    return False, None


def _parse_title(html: str) -> str:
    soup = build_soup(html)
    node = soup.find("title")
    return node.get_text(strip=True) if node else ""


def _extract_status_code(response: Any) -> int | None:
    if response is None:
        return None
    status = getattr(response, "status", None)
    if callable(status):
        try:
            status = status()
        except Exception:  # pragma: no cover - 安全兜底
            status = None
    if status is None:
        status = getattr(response, "status_code", None)
    try:
        return int(status) if status is not None else None
    except Exception:  # pragma: no cover - 安全兜底
        return None


def _extract_final_url(response: Any, fallback_url: str) -> str:
    if response is not None:
        response_url = getattr(response, "url", None)
        if response_url is not None:
            return str(response_url)
    return fallback_url


class HttpxPageFetcher:

    def __init__(self, client: Any):
        self._client = client

    def fetch(
        self,
        url: str,
        expected_selector: str | None = None,
        stage: str | None = None,
    ) -> FetchResult:
        del expected_selector, stage
        ensure_not_cancelled()
        response = self._client.get(url)
        ensure_not_cancelled()
        html = response.text
        status_code = _extract_status_code(response)
        final_url = _extract_final_url(response, url)
        title = _parse_title(html)
        blocked, reason = is_blocked_page(html, title, status_code)
        return FetchResult(
            requested_url=url,
            final_url=final_url,
            status_code=status_code,
            title=title,
            html=html,
            blocked=blocked,
            blocked_reason=reason,
        )


class PlaywrightPageFetcher:

    def __init__(self, *, context: Any, page: Any, config: FetchConfig):
        self._context = context
        self._page = page
        self._config = config

    def _capture_result(self, requested_url: str, response: Any) -> FetchResult:
        html = self._page.content()
        title = self._page.title()
        final_url = str(getattr(self._page, "url", requested_url))
        status_code = _extract_status_code(response)
        blocked, reason = is_blocked_page(html, title, status_code)
        return FetchResult(
            requested_url=requested_url,
            final_url=final_url,
            status_code=status_code,
            title=title,
            html=html,
            blocked=blocked,
            blocked_reason=reason,
        )

    def _dump_debug(self, *, stage: str | None, result: FetchResult) -> None:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        stage_name = stage or "fetch"
        debug_dir = Path("debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        html_path = debug_dir / f"{stage_name}_{stamp}.html"
        html_path.write_text(result.html, encoding="utf-8")
        try:
            image_path = debug_dir / f"{stage_name}_{stamp}.png"
            self._page.screenshot(path=str(image_path), full_page=True)
        except Exception:
            pass

    def fetch(
        self,
        url: str,
        expected_selector: str | None = None,
        stage: str | None = None,
    ) -> FetchResult:
        ensure_not_cancelled()
        response = self._page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self._config.browser_timeout_seconds * 1000,
        )
        ensure_not_cancelled()
        result = self._capture_result(url, response)

        if result.blocked and expected_selector:
            LOGGER.warning(
                "浏览器模式检测到疑似拦截，请在浏览器中完成验证/登录（等待最多 %ss）。",
                self._config.challenge_timeout_seconds,
            )
            deadline = time.monotonic() + self._config.challenge_timeout_seconds
            try:
                while True:
                    ensure_not_cancelled()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise PlaywrightTimeoutError("challenge wait timeout")
                    self._page.wait_for_selector(
                        expected_selector,
                        timeout=max(200, min(1000, int(remaining * 1000))),
                    )
                    break
            except PlaywrightTimeoutError:
                self._dump_debug(stage=stage, result=result)
                return result
            except Exception:
                self._dump_debug(stage=stage, result=result)
                return result
            result = self._capture_result(url, response=None)

        if result.blocked:
            self._dump_debug(stage=stage, result=result)
        return result


def _normalize_cookie_item(
    item: Mapping[str, Any],
    *,
    default_host: str,
) -> dict[str, Any] | None:
    name = str(item.get("name", "")).strip()
    value = item.get("value")
    if not name or value is None:
        return None

    is_host_cookie = name.startswith("__Host-")
    output: dict[str, Any] = {
        "name": name,
        "value": str(value),
    }

    url = item.get("url")
    if url:
        output["url"] = str(url)

    domain = item.get("domain")
    if domain and not is_host_cookie:
        output["domain"] = str(domain)

    path = item.get("path")
    if path:
        output["path"] = str(path)
    elif is_host_cookie:
        output["path"] = "/"

    if "secure" in item and item.get("secure") is not None:
        output["secure"] = bool(item.get("secure"))
    elif is_host_cookie or name.startswith("__Secure-"):
        output["secure"] = True

    if "httpOnly" in item and item.get("httpOnly") is not None:
        output["httpOnly"] = bool(item.get("httpOnly"))

    same_site = item.get("sameSite")
    if same_site is not None:
        normalized_same_site = str(same_site).strip().lower()
        if normalized_same_site == "strict":
            output["sameSite"] = "Strict"
        elif normalized_same_site == "lax":
            output["sameSite"] = "Lax"
        elif normalized_same_site == "none":
            output["sameSite"] = "None"

    expires = item.get("expires")
    if expires is not None:
        try:
            output["expires"] = int(float(expires))
        except Exception:
            pass

    if is_host_cookie:
        output.pop("domain", None)
        output["path"] = "/"
        output["secure"] = True

    if "url" not in output and "domain" not in output and not is_host_cookie and default_host:
        output["domain"] = default_host
    if "url" not in output and "path" not in output:
        output["path"] = "/"
    return output


def _is_cookie_scalar_value(value: Any) -> bool:
    return not isinstance(value, (Mapping, list, tuple, set, frozenset))


def _normalize_playwright_cookies(
    cookies: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    default_host: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    dropped = 0
    index_by_name: dict[str, int] = {}

    def _append_item(item: Mapping[str, Any]) -> None:
        nonlocal dropped
        normalized = _normalize_cookie_item(item, default_host=default_host)
        if normalized is None:
            dropped += 1
            return
        output.append(normalized)
        index_by_name[normalized["name"]] = len(output) - 1

    if isinstance(cookies, Mapping):
        cookie_items = cookies.get(PLAYWRIGHT_COOKIE_ITEMS_KEY)
        if isinstance(cookie_items, Sequence) and not isinstance(
            cookie_items, (str, bytes, bytearray)
        ):
            for item in cookie_items:
                if isinstance(item, Mapping):
                    _append_item(item)
                else:
                    dropped += 1

        for key, value in cookies.items():
            if key == PLAYWRIGHT_COOKIE_ITEMS_KEY:
                continue
            if value is None or not _is_cookie_scalar_value(value):
                continue
            name = str(key).strip()
            if not name:
                dropped += 1
                continue
            normalized = _normalize_cookie_item(
                {"name": name, "value": value},
                default_host=default_host,
            )
            if normalized is None:
                dropped += 1
                continue
            existing = index_by_name.get(name)
            if existing is None:
                output.append(normalized)
                index_by_name[name] = len(output) - 1
            else:
                output[existing]["value"] = normalized["value"]
    else:
        for item in cookies:
            if isinstance(item, Mapping):
                _append_item(item)
            else:
                dropped += 1

    if dropped:
        LOGGER.warning("Cookie 归一化时丢弃了 %d 条无效记录。", dropped)
    return output


def _to_playwright_cookies(
    cookies: Mapping[str, Any] | Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    host = (urlparse(app_config.BASE_URL).hostname or "javdb.com").strip().lower()
    return _normalize_playwright_cookies(cookies, default_host=host)


def _coerce_cookie_store(
    cookies: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None
) -> dict[str, Any]:
    if cookies is None:
        return {}
    if isinstance(cookies, Mapping):
        return dict(cookies)
    cookie_items: list[dict[str, Any]] = []
    cookie_dict: dict[str, Any] = {}
    for item in cookies:
        if not isinstance(item, Mapping):
            continue
        cookie_items.append(dict(item))
        name = str(item.get("name", "")).strip()
        value = item.get("value")
        if name and value is not None:
            cookie_dict[name] = str(value)
    if cookie_items:
        cookie_dict[PLAYWRIGHT_COOKIE_ITEMS_KEY] = cookie_items
    return cookie_dict


def _extract_httpx_cookie_dict(cookie_store: Mapping[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in cookie_store.items():
        if key == PLAYWRIGHT_COOKIE_ITEMS_KEY:
            continue
        if value is None or not _is_cookie_scalar_value(value):
            continue
        name = str(key).strip()
        if not name:
            continue
        output[name] = str(value)
    return output


def _default_browser_channels() -> tuple[str, ...]:
    system = platform.system().lower()
    if system == "windows":
        return ("msedge", "chrome")
    if system == "darwin":
        return ("chrome", "msedge")
    return ("chrome",)


def _is_missing_browser_error(exc: Exception) -> bool:
    message = str(exc).lower()
    markers = (
        "executable doesn't exist",
        "please run the following command",
        "failed to launch browser",
    )
    return any(marker in message for marker in markers)


def _launch_persistent_context_with_fallback(
    chromium: Any,
    *,
    user_data_dir: Path,
    headless: bool,
    preferred_channel: str | None,
) -> Any:
    base_kwargs: dict[str, Any] = {
        "user_data_dir": str(user_data_dir),
        "headless": headless,
    }
    channels = [preferred_channel
               ] if preferred_channel else list(_default_browser_channels())
    last_error: Exception | None = None

    for channel in channels:
        launch_kwargs = dict(base_kwargs)
        launch_kwargs["channel"] = channel
        try:
            return chromium.launch_persistent_context(**launch_kwargs)
        except Exception as exc:
            last_error = exc
            LOGGER.warning("浏览器通道 %s 启动失败，将尝试其他通道：%s", channel, exc)
            continue

    raise RuntimeError(
        "未找到可用浏览器。请先在本机安装 Chrome 或 Edge 后重试。"
    ) from last_error


def _configure_playwright_runtime_environment() -> None:
    if not getattr(sys, "frozen", False):
        return
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return

    executable = Path(sys.executable).resolve()
    candidates = (
        executable.parent / "ms-playwright",
        executable.parent.parent / "Resources" / "ms-playwright",
    )
    for candidate in candidates:
        if candidate.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
            return
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"


@contextmanager
def create_fetcher(
    cookies: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    config: FetchConfig | Mapping[str, Any] | None = None,
) -> Iterator[PageFetcher]:
    resolved = normalize_fetch_config(config)
    cookie_store = _coerce_cookie_store(cookies)
    httpx_cookie_dict = _extract_httpx_cookie_dict(cookie_store)

    if resolved.mode == "httpx":
        with build_client(httpx_cookie_dict) as client:
            yield HttpxPageFetcher(client)
        return

    if resolved.mode == "browser" and sync_playwright is None:
        raise RuntimeError(
            "浏览器模式依赖 playwright，请先安装依赖并确保本机已安装 Chrome/Edge。"
        )

    if resolved.mode == "browser":
        _configure_playwright_runtime_environment()

        user_data_dir = Path(resolved.browser_user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as playwright:
            context = _launch_persistent_context_with_fallback(
                playwright.chromium,
                user_data_dir=user_data_dir,
                headless=resolved.browser_headless,
                preferred_channel=resolved.browser_channel,
            )
            try:
                if cookie_store:
                    try:
                        browser_cookies = _to_playwright_cookies(cookie_store)
                        if browser_cookies:
                            LOGGER.info("browser 模式注入 Cookie %d 条。", len(browser_cookies))
                            context.add_cookies(browser_cookies)
                        else:
                            LOGGER.warning("browser 模式没有可注入 Cookie，将仅依赖 profile。")
                    except Exception as exc:
                        LOGGER.warning(
                            "浏览器模式注入 Cookie 失败，将继续使用现有 profile：%s", exc
                        )
                page = context.pages[0] if getattr(context, "pages",
                                                   None) else context.new_page()
                yield PlaywrightPageFetcher(
                    context=context, page=page, config=resolved
                )
            finally:
                context.close()
        return


def log_fetch_diagnostics(mode: FetchMode, result: FetchResult) -> None:
    LOGGER.info(
        "[fetch] mode=%s requested=%s final=%s status=%s title=%s blocked=%s",
        mode,
        result.requested_url,
        result.final_url,
        result.status_code,
        result.title,
        result.blocked,
    )
