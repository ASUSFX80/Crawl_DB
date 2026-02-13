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
from typing import Any, Iterator, Literal, Mapping, Protocol, cast
from urllib.parse import urlparse

from config import BASE_URL, LOGGER, build_client
from utils import build_soup, ensure_not_cancelled

try:  # pragma: no cover - 运行环境兜底
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - 无 playwright 依赖时兜底
    PlaywrightTimeoutError = RuntimeError
    sync_playwright = None

FetchMode = Literal["httpx", "browser"]


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
        help="抓取模式：browser（默认，Playwright 持久化会话）或 httpx。",
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
            getattr(args, "browser_user_data_dir", "userdata/browser_profile/javdb")
        ),
        browser_headless=bool(getattr(args, "browser_headless", False)),
        browser_timeout_seconds=int(getattr(args, "browser_timeout_seconds", 30)),
        challenge_timeout_seconds=int(getattr(args, "challenge_timeout_seconds", 180)),
    )


def normalize_fetch_config(fetch_config: FetchConfig | Mapping[str, Any] | None) -> FetchConfig:
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
            fetch_config.get("browser_user_data_dir", "userdata/browser_profile/javdb")
        ),
        browser_headless=bool(fetch_config.get("browser_headless", False)),
        browser_timeout_seconds=int(fetch_config.get("browser_timeout_seconds", 30)),
        challenge_timeout_seconds=int(fetch_config.get("challenge_timeout_seconds", 180)),
        browser_channel=(
            str(fetch_config["browser_channel"]) if fetch_config.get("browser_channel") else None
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


def _to_playwright_cookies(cookies: Mapping[str, Any]) -> list[dict[str, Any]]:
    host = urlparse(BASE_URL).hostname or "javdb.com"
    output: list[dict[str, Any]] = []
    for key, value in cookies.items():
        if value is None:
            continue
        output.append(
            {
                "name": str(key),
                "value": str(value),
                "domain": host,
                "path": "/",
                "secure": True,
                "httpOnly": False,
            }
        )
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
    channels = [preferred_channel] if preferred_channel else [None, *_default_browser_channels()]
    last_error: Exception | None = None

    for channel in channels:
        launch_kwargs = dict(base_kwargs)
        if channel:
            launch_kwargs["channel"] = channel
        try:
            return chromium.launch_persistent_context(**launch_kwargs)
        except Exception as exc:
            last_error = exc
            if channel is None and not _is_missing_browser_error(exc):
                raise
            if channel:
                LOGGER.warning("浏览器通道 %s 启动失败，将尝试其他通道：%s", channel, exc)
            continue

    raise RuntimeError(
        "未找到可用浏览器。请安装 Chrome/Edge，或手动执行 `playwright install chromium` 后重试。"
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
    cookies: Mapping[str, Any] | None,
    config: FetchConfig | Mapping[str, Any] | None = None,
) -> Iterator[PageFetcher]:
    resolved = normalize_fetch_config(config)
    cookie_dict = dict(cookies or {})

    if resolved.mode == "httpx":
        with build_client(cookie_dict) as client:
            yield HttpxPageFetcher(client)
        return

    if sync_playwright is None:
        raise RuntimeError(
            "浏览器模式依赖 playwright，请先安装依赖并执行: uv run playwright install chromium"
        )

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
            if cookie_dict:
                try:
                    context.add_cookies(_to_playwright_cookies(cookie_dict))
                except Exception as exc:
                    LOGGER.warning("浏览器模式注入 Cookie 失败，将继续使用现有 profile：%s", exc)
            page = context.pages[0] if getattr(context, "pages", None) else context.new_page()
            yield PlaywrightPageFetcher(context=context, page=page, config=resolved)
        finally:
            context.close()


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
