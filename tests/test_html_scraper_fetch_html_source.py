import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT_DIR / "html-scraper" / "fetch_html_source.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "fetch_html_source", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HtmlScraperFetchSourceTests(unittest.TestCase):

    def test_cookie_invalid_falls_back_to_empty_cookie(self) -> None:
        module = load_module()
        with (
            mock.patch.object(
                module,
                "load_cookie_dict",
                side_effect=SystemExit("bad cookie")
            ),
            mock.patch.object(module.LOGGER, "warning") as warning_mock,
        ):
            cookies = module.load_cookies_for_browser("cookie.json")

        self.assertEqual(cookies, {})
        warning_mock.assert_called_once()

    def test_fetch_uses_browser_mode_config(self) -> None:
        module = load_module()

        class _FakeFetcher:

            def __init__(self, result):
                self._result = result

            def fetch(self, url: str, expected_selector=None, stage=None):
                del url, expected_selector, stage
                return self._result

        class _FakeFetcherContext:

            def __init__(self, fetcher):
                self._fetcher = fetcher

            def __enter__(self):
                return self._fetcher

            def __exit__(self, exc_type, exc, tb):
                del exc_type, exc, tb
                return False

        fake_result = SimpleNamespace(
            blocked=False,
            status_code=200,
            title="ok",
            blocked_reason=None,
            html="<html>ok</html>",
        )
        with mock.patch.object(
            module,
            "create_fetcher",
            return_value=_FakeFetcherContext(_FakeFetcher(fake_result))
        ) as create_fetcher_mock:
            html = module.fetch_html_via_browser(
                url="https://example.com",
                cookies={"k": "v"},
                expected_selector="div#ok",
                browser_user_data_dir="userdata/browser_profile/javdb",
                browser_headless=True,
                browser_timeout_seconds=12,
                challenge_timeout_seconds=34,
            )

        self.assertEqual(html, "<html>ok</html>")
        args, kwargs = create_fetcher_mock.call_args
        del kwargs
        self.assertEqual(args[0], {"k": "v"})
        fetch_config = args[1]
        self.assertEqual(fetch_config.mode, "browser")
        self.assertEqual(
            fetch_config.browser_user_data_dir, "userdata/browser_profile/javdb"
        )
        self.assertTrue(fetch_config.browser_headless)
        self.assertEqual(fetch_config.browser_timeout_seconds, 12)
        self.assertEqual(fetch_config.challenge_timeout_seconds, 34)

    def test_fetch_success_writes_html_to_output_file(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "nested" / "output.html"
            saved_path = module.save_html("<html>saved</html>", str(target))
            self.assertEqual(saved_path, target)
            self.assertTrue(target.exists())
            self.assertEqual(
                target.read_text(encoding="utf-8"), "<html>saved</html>"
            )

    def test_blocked_result_raises_runtime_error(self) -> None:
        module = load_module()

        class _FakeFetcher:

            def __init__(self, result):
                self._result = result

            def fetch(self, url: str, expected_selector=None, stage=None):
                del url, expected_selector, stage
                return self._result

        class _FakeFetcherContext:

            def __init__(self, fetcher):
                self._fetcher = fetcher

            def __enter__(self):
                return self._fetcher

            def __exit__(self, exc_type, exc, tb):
                del exc_type, exc, tb
                return False

        fake_result = SimpleNamespace(
            blocked=True,
            status_code=403,
            title="blocked",
            blocked_reason="status_403",
            html="<html>blocked</html>",
        )
        with mock.patch.object(
            module,
            "create_fetcher",
            return_value=_FakeFetcherContext(_FakeFetcher(fake_result))
        ):
            with self.assertRaisesRegex(RuntimeError, "status=403"):
                module.fetch_html_via_browser(
                    url="https://example.com",
                    cookies={},
                    expected_selector=None,
                    browser_user_data_dir="userdata/browser_profile/javdb",
                    browser_headless=False,
                    browser_timeout_seconds=30,
                    challenge_timeout_seconds=180,
                )

    def test_main_requires_url_argument(self) -> None:
        module = load_module()
        with self.assertRaises(SystemExit):
            module.main([])


if __name__ == "__main__":
    unittest.main()
