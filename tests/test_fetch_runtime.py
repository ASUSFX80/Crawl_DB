import argparse
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


class FetchRuntimeTests(unittest.TestCase):

    def test_to_playwright_cookies_uses_runtime_base_url_domain(self) -> None:
        import app.core.config as cfg
        import app.core.fetch_runtime as fr

        previous_base_url = cfg.BASE_URL
        cfg.BASE_URL = "https://mirror-javdb.com"
        try:
            cookies = fr._to_playwright_cookies({"_jdb_session": "x"})
        finally:
            cfg.BASE_URL = previous_base_url
        self.assertEqual(cookies[0]["domain"], "mirror-javdb.com")

    def test_normalize_playwright_cookies_preserves_list_attributes(
        self
    ) -> None:
        import app.core.fetch_runtime as fr

        cookies = fr._normalize_playwright_cookies(
            [{
                "name": "_jdb_session",
                "value": "abc",
                "domain": ".javdb.com",
                "path": "/users",
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
                "expires": 1893456000,
            }],
            default_host="javdb.com",
        )

        self.assertEqual(len(cookies), 1)
        item = cookies[0]
        self.assertEqual(item["name"], "_jdb_session")
        self.assertEqual(item["value"], "abc")
        self.assertEqual(item["domain"], ".javdb.com")
        self.assertEqual(item["path"], "/users")
        self.assertTrue(item["httpOnly"])
        self.assertTrue(item["secure"])
        self.assertEqual(item["sameSite"], "Lax")
        self.assertEqual(item["expires"], 1893456000)

    def test_normalize_playwright_cookies_host_prefix_omits_domain(
        self
    ) -> None:
        import app.core.fetch_runtime as fr

        cookies = fr._normalize_playwright_cookies(
            [{
                "name": "__Host-auth",
                "value": "abc",
                "domain": ".javdb.com",
                "path": "/",
            }],
            default_host="javdb.com",
        )

        self.assertEqual(len(cookies), 1)
        self.assertNotIn("domain", cookies[0])
        self.assertEqual(cookies[0]["path"], "/")

    def test_fetch_config_from_args_defaults_to_browser(self) -> None:
        import app.core.fetch_runtime as fr

        parser = argparse.ArgumentParser()
        fr.add_fetch_mode_arguments(parser)
        args = parser.parse_args([])

        config = fr.fetch_config_from_args(args)
        self.assertEqual(config.mode, "browser")

    def test_fetch_config_from_args_supports_httpx_and_browser(self) -> None:
        import app.core.fetch_runtime as fr

        parser = argparse.ArgumentParser()
        fr.add_fetch_mode_arguments(parser)
        args = parser.parse_args(["--fetch-mode", "httpx"])
        config = fr.fetch_config_from_args(args)
        self.assertEqual(config.mode, "httpx")

        args = parser.parse_args(["--fetch-mode", "browser"])
        config = fr.fetch_config_from_args(args)
        self.assertEqual(config.mode, "browser")

    def test_fetch_config_from_args_rejects_smart(self) -> None:
        import app.core.fetch_runtime as fr

        parser = argparse.ArgumentParser()
        fr.add_fetch_mode_arguments(parser)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--fetch-mode", "smart"])

    def test_normalize_fetch_config_falls_back_to_browser_for_smart(
        self
    ) -> None:
        import app.core.fetch_runtime as fr

        config = fr.normalize_fetch_config({"mode": "smart"})
        self.assertEqual(config.mode, "browser")

    def test_is_blocked_page_matches_status_title_or_body(self) -> None:
        import app.core.fetch_runtime as fr

        self.assertTrue(fr.is_blocked_page("<html></html>", "ok", 403)[0])
        self.assertTrue(
            fr.is_blocked_page(
                "<html></html>", "Attention Required! | Cloudflare", 200
            )[0]
        )
        self.assertTrue(
            fr.is_blocked_page("Sorry, you have been blocked", "ok", 200)[0]
        )
        self.assertFalse(
            fr.is_blocked_page("<html><body>ok</body></html>", "ok", 200)[0]
        )

    def test_httpx_page_fetcher_returns_fetch_result(self) -> None:
        import app.core.fetch_runtime as fr

        class _FakeClient:

            def get(self, url: str):
                return SimpleNamespace(
                    text="<html><title>ok</title></html>",
                    status_code=200,
                    url="https://javdb.com/users/collection_actors",
                )

        fetcher = fr.HttpxPageFetcher(client=_FakeClient())
        result = fetcher.fetch("https://javdb.com/users/collection_actors")

        self.assertEqual(
            result.requested_url, "https://javdb.com/users/collection_actors"
        )
        self.assertEqual(
            result.final_url, "https://javdb.com/users/collection_actors"
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.title, "ok")
        self.assertFalse(result.blocked)

    def test_playwright_page_fetcher_waits_for_selector_when_blocked(
        self
    ) -> None:
        import app.core.fetch_runtime as fr

        class _FakeResponse:

            def __init__(self, status: int):
                self.status = status

        class _FakePage:

            def __init__(self):
                self._blocked = True
                self.current_url = ""
                self.waited_selector = None

            def goto(self, url: str, wait_until: str, timeout: int):
                self.current_url = url
                status = 403 if self._blocked else 200
                return _FakeResponse(status)

            def title(self):
                return "Attention Required! | Cloudflare" if self._blocked else "JavDB"

            def content(self):
                if self._blocked:
                    return "<html><body>Sorry, you have been blocked</body></html>"
                return "<html><body><div id='actors'></div></body></html>"

            @property
            def url(self):
                return self.current_url

            def wait_for_selector(self, selector: str, timeout: int):
                self.waited_selector = selector
                self._blocked = False

            def screenshot(self, path: str, full_page: bool):
                return None

        class _FakeContext:

            def __init__(self, page: _FakePage):
                self.pages = [page]

            def add_cookies(self, cookies):
                return None

            def new_page(self):
                return self.pages[0]

            def close(self):
                return None

        class _FakePlaywrightCM:

            def __init__(self, context: _FakeContext):
                self._context = context

            def __enter__(self):

                class _Chromium:

                    def __init__(self, context: _FakeContext):
                        self._context = context

                    def launch_persistent_context(self, **kwargs):
                        return self._context

                return SimpleNamespace(chromium=_Chromium(self._context))

            def __exit__(self, exc_type, exc, tb):
                return False

        page = _FakePage()
        context = _FakeContext(page)

        with mock.patch(
            "app.core.fetch_runtime.sync_playwright",
            return_value=_FakePlaywrightCM(context)
        ):
            with fr.create_fetcher(
                cookies={"_jdb_session": "x"},
                config=fr.FetchConfig(
                    mode="browser",
                    browser_user_data_dir="userdata/browser_profile/javdb"
                ),
            ) as fetcher:
                result = fetcher.fetch(
                    "https://javdb.com/users/collection_actors",
                    expected_selector="div#actors",
                    stage="collect_actors",
                )

        self.assertFalse(result.blocked)
        self.assertEqual(page.waited_selector, "div#actors")

    def test_create_fetcher_falls_back_to_system_browser_channel_when_default_missing(
        self
    ) -> None:
        import app.core.fetch_runtime as fr

        class _FakeContext:

            def __init__(self):
                self.pages = []

            def add_cookies(self, cookies):
                return None

            def new_page(self):
                return SimpleNamespace()

            def close(self):
                return None

        class _Chromium:

            def __init__(self):
                self.calls = []
                self._context = _FakeContext()

            def launch_persistent_context(self, **kwargs):
                self.calls.append(kwargs.copy())
                if kwargs["channel"] == "msedge":
                    return self._context
                raise RuntimeError("channel launch failed")

        class _PWCM:

            def __init__(self, chromium):
                self._chromium = chromium

            def __enter__(self):
                return SimpleNamespace(chromium=self._chromium)

            def __exit__(self, exc_type, exc, tb):
                return False

        chromium = _Chromium()
        with (
            mock.patch(
                "app.core.fetch_runtime.sync_playwright",
                return_value=_PWCM(chromium)
            ),
            mock.patch(
                "app.core.fetch_runtime._default_browser_channels",
                return_value=("msedge",)
            ),
        ):
            with fr.create_fetcher(
                cookies={},
                config=fr.FetchConfig(
                    mode="browser",
                    browser_user_data_dir="userdata/browser_profile/javdb"
                ),
            ):
                pass

        self.assertEqual(len(chromium.calls), 1)
        self.assertEqual(chromium.calls[0].get("channel"), "msedge")

    def test_launch_persistent_context_only_tries_channels_without_builtin_fallback(
        self
    ) -> None:
        import app.core.fetch_runtime as fr

        class _FakeChromium:

            def __init__(self):
                self.calls = []

            def launch_persistent_context(self, **kwargs):
                self.calls.append(kwargs.copy())
                raise RuntimeError("channel launch failed")

        chromium = _FakeChromium()
        with mock.patch.object(
            fr,
            "_default_browser_channels",
            return_value=("chrome", "msedge"),
        ):
            with self.assertRaises(RuntimeError):
                fr._launch_persistent_context_with_fallback(
                    chromium,
                    user_data_dir=Path("userdata/browser_profile/javdb"),
                    headless=True,
                    preferred_channel=None,
                )

        self.assertEqual(len(chromium.calls), 2)
        self.assertEqual(chromium.calls[0].get("channel"), "chrome")
        self.assertEqual(chromium.calls[1].get("channel"), "msedge")
        self.assertTrue(all("channel" in call for call in chromium.calls))

    def test_create_fetcher_sets_playwright_browsers_path_for_frozen_runtime(
        self
    ) -> None:
        import app.core.fetch_runtime as fr

        class _FakeContext:

            def __init__(self):
                self.pages = []

            def add_cookies(self, cookies):
                return None

            def new_page(self):
                return SimpleNamespace()

            def close(self):
                return None

        class _Chromium:

            def launch_persistent_context(self, **kwargs):
                return _FakeContext()

        class _PWCM:

            def __enter__(self):
                return SimpleNamespace(chromium=_Chromium())

            def __exit__(self, exc_type, exc, tb):
                return False

        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(fr, "sync_playwright", return_value=_PWCM()),
            mock.patch.object(fr.sys, "frozen", True, create=True),
        ):
            with fr.create_fetcher(
                cookies={},
                config=fr.FetchConfig(
                    mode="browser",
                    browser_user_data_dir="userdata/browser_profile/javdb"
                ),
            ):
                pass
            self.assertEqual(fr.os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), "0")

    def test_create_fetcher_does_not_require_frozen_sidecar_browsers_path(
        self
    ) -> None:
        import app.core.fetch_runtime as fr

        class _FakeContext:

            def __init__(self):
                self.pages = []

            def add_cookies(self, cookies):
                return None

            def new_page(self):
                return SimpleNamespace()

            def close(self):
                return None

        class _Chromium:

            def launch_persistent_context(self, **kwargs):
                return _FakeContext()

        class _PWCM:

            def __enter__(self):
                return SimpleNamespace(chromium=_Chromium())

            def __exit__(self, exc_type, exc, tb):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            app_exe = (
                Path(tmp) / "crawljav.app" / "Contents" / "MacOS" / "crawljav"
            )
            app_exe.parent.mkdir(parents=True, exist_ok=True)

            with (
                mock.patch.dict("os.environ", {}, clear=True),
                mock.patch.object(fr, "sync_playwright", return_value=_PWCM()),
                mock.patch.object(fr.sys, "frozen", True, create=True),
                mock.patch.object(fr.sys, "executable", str(app_exe)),
            ):
                with fr.create_fetcher(
                    cookies={},
                    config=fr.FetchConfig(
                        mode="browser",
                        browser_user_data_dir="userdata/browser_profile/javdb"
                    ),
                ):
                    pass
                self.assertEqual(
                    fr.os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), "0"
                )

    def test_create_fetcher_browser_uses_cookie_item_attributes(self) -> None:
        import app.core.fetch_runtime as fr

        class _FakeContext:

            def __init__(self):
                self.pages = [SimpleNamespace()]
                self.added_cookies = []

            def add_cookies(self, cookies):
                self.added_cookies.extend(cookies)

            def new_page(self):
                return self.pages[0]

            def close(self):
                return None

        class _Chromium:

            def __init__(self, context):
                self._context = context

            def launch_persistent_context(self, **kwargs):
                del kwargs
                return self._context

        class _PWCM:

            def __init__(self, context):
                self._context = context

            def __enter__(self):
                return SimpleNamespace(chromium=_Chromium(self._context))

            def __exit__(self, exc_type, exc, tb):
                del exc_type, exc, tb
                return False

        context = _FakeContext()
        with mock.patch.object(
            fr, "sync_playwright", return_value=_PWCM(context)
        ):
            with fr.create_fetcher(
                cookies={
                    "__playwright_cookie_items__": [{
                        "name": "_jdb_session",
                        "value": "token",
                        "domain": ".javdb.com",
                        "path": "/users",
                        "httpOnly": True,
                    }]
                },
                config=fr.FetchConfig(mode="browser"),
            ):
                pass

        self.assertEqual(len(context.added_cookies), 1)
        cookie = context.added_cookies[0]
        self.assertEqual(cookie["domain"], ".javdb.com")
        self.assertEqual(cookie["path"], "/users")
        self.assertTrue(cookie["httpOnly"])


if __name__ == "__main__":
    unittest.main()
