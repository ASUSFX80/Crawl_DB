import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import app.collection.actors.collect_actors as gca
import app.core.config as config
from app.core.utils import CancelledError, set_cancel_checker


class CollectActorsParseTests(unittest.TestCase):

    def test_parse_actors_css_main_path(self) -> None:
        html = """
        <html><body>
          <section>
            <div id="actors">
              <div class="box actor-box">
                <a href="/actors/abc"><strong>Actor A</strong></a>
              </div>
              <div class="box actor-box">
                <a href="/actors/xyz"><strong>Actor B</strong></a>
              </div>
            </div>
          </section>
        </body></html>
        """

        items = gca.parse_actors(html)

        self.assertEqual(
            items,
            [
                {
                    "href": "https://javdb.com/actors/abc",
                    "strong": "Actor A"
                },
                {
                    "href": "https://javdb.com/actors/xyz",
                    "strong": "Actor B"
                },
            ],
        )

    def test_parse_actors_falls_back_to_anchor_text_when_no_strong(
        self
    ) -> None:
        html = """
        <html><body>
          <section>
            <div id="actors">
              <div class="box actor-box">
                <a href="/actors/no-strong">No Strong Name</a>
              </div>
            </div>
          </section>
        </body></html>
        """

        items = gca.parse_actors(html)

        self.assertEqual(
            items,
            [{
                "href": "https://javdb.com/actors/no-strong",
                "strong": "No Strong Name"
            }],
        )

    def test_parse_actors_logs_warning_when_section_missing(self) -> None:
        html = "<html><body><div>Access denied</div></body></html>"

        with self.assertLogs("crawljav", level="WARNING") as captured:
            items = gca.parse_actors(html)

        self.assertEqual(items, [])
        self.assertTrue(
            any("页面里没有 <section>" in message for message in captured.output)
        )

    def test_parse_actors_returns_empty_when_no_actor_boxes(self) -> None:
        html = """
        <html><body>
          <section>
            <div id="actors"></div>
          </section>
        </body></html>
        """

        items = gca.parse_actors(html)

        self.assertEqual(items, [])


class CollectActorsCrawlTests(unittest.TestCase):

    def test_crawl_all_pages_uses_runtime_base_url_for_collection_entry(
        self
    ) -> None:
        html = """
        <html><body>
          <section>
            <div id="actors">
              <div class="box actor-box">
                <a href="/actors/abc"><strong>Actor A</strong></a>
              </div>
            </div>
          </section>
        </body></html>
        """
        fake_fetcher = mock.Mock()
        fake_fetcher.fetch.return_value = mock.Mock(
            html=html,
            blocked=False,
            blocked_reason=None,
            status_code=200,
            final_url="https://mirror-javdb.com/users/collection_actors",
            title="JavDB",
            requested_url="https://mirror-javdb.com/users/collection_actors",
        )
        previous_base_url = config.BASE_URL
        config.BASE_URL = "https://mirror-javdb.com"
        try:
            with mock.patch(
                "app.collection.actors.collect_actors.load_cookie_dict",
                return_value={
                    "over18": "1",
                    "cf_clearance": "x",
                    "_jdb_session": "y"
                },
            ), mock.patch(
                "app.collection.actors.collect_actors.create_fetcher",
                return_value=nullcontext(fake_fetcher),
            ), mock.patch(
                "app.collection.actors.collect_actors.find_next_url",
                return_value=None,
            ):
                gca.crawl_all_pages("cookie.json")
        finally:
            config.BASE_URL = previous_base_url

        fake_fetcher.fetch.assert_called_once()
        self.assertEqual(
            fake_fetcher.fetch.call_args.args[0],
            "https://mirror-javdb.com/users/collection_actors",
        )

    def test_crawl_all_pages_respects_cancel_checker(self) -> None:
        html = """
        <html><body>
          <section>
            <div id="actors">
              <div class="box actor-box">
                <a href="/actors/abc"><strong>Actor A</strong></a>
              </div>
            </div>
          </section>
        </body></html>
        """
        fake_fetcher = mock.Mock()
        fake_fetcher.fetch.return_value = mock.Mock(
            html=html,
            blocked=False,
            blocked_reason=None,
            status_code=200,
            final_url="https://javdb.com/users/collection_actors",
            title="JavDB",
            requested_url="https://javdb.com/users/collection_actors",
        )

        with mock.patch(
            "app.collection.actors.collect_actors.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.collect_actors.create_fetcher",
            return_value=nullcontext(fake_fetcher),
        ):
            set_cancel_checker(lambda: True)
            try:
                with self.assertRaises(CancelledError):
                    gca.crawl_all_pages("cookie.json")
            finally:
                set_cancel_checker(None)

        fake_fetcher.fetch.assert_not_called()

    def test_crawl_all_pages_dedupes_by_href(self) -> None:
        page_one = """
        <html><body>
          <section>
            <div id="actors">
              <div class="box actor-box">
                <a href="/actors/abc"><strong>Actor A</strong></a>
              </div>
              <div class="box actor-box">
                <a href="/actors/xyz"><strong>Actor B</strong></a>
              </div>
            </div>
          </section>
        </body></html>
        """
        page_two = """
        <html><body>
          <section>
            <div id="actors">
              <div class="box actor-box">
                <a href="/actors/xyz"><strong>Actor B</strong></a>
              </div>
              <div class="box actor-box">
                <a href="/actors/new"><strong>Actor C</strong></a>
              </div>
            </div>
          </section>
        </body></html>
        """

        with mock.patch(
            "app.collection.actors.collect_actors.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.collect_actors.create_fetcher",
            return_value=nullcontext(
                mock.Mock(
                    fetch=mock.Mock(
                        side_effect=[
                            mock.Mock(
                                html=page_one,
                                blocked=False,
                                blocked_reason=None,
                                status_code=200,
                                final_url=
                                "https://javdb.com/users/collection_actors",
                                title="JavDB",
                                requested_url=
                                "https://javdb.com/users/collection_actors",
                            ),
                            mock.Mock(
                                html=page_two,
                                blocked=False,
                                blocked_reason=None,
                                status_code=200,
                                final_url=
                                "https://javdb.com/users/collection_actors?page=2",
                                title="JavDB",
                                requested_url=
                                "https://javdb.com/users/collection_actors?page=2",
                            ),
                        ]
                    )
                )
            ),
        ), mock.patch(
            "app.collection.actors.collect_actors.find_next_url",
            side_effect=["https://example.com/next", None],
        ), mock.patch(
            "app.collection.actors.collect_actors.sleep_with_cancel",
            return_value=None,
        ):
            items = gca.crawl_all_pages("cookie.json")

        self.assertEqual(
            items,
            [
                {
                    "href": "https://javdb.com/actors/abc",
                    "strong": "Actor A"
                },
                {
                    "href": "https://javdb.com/actors/xyz",
                    "strong": "Actor B"
                },
                {
                    "href": "https://javdb.com/actors/new",
                    "strong": "Actor C"
                },
            ],
        )

    def test_crawl_all_pages_stops_on_interstitial(self) -> None:
        interstitial = "<html><body><div>Access denied</div></body></html>"

        with mock.patch(
            "app.collection.actors.collect_actors.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.collect_actors.create_fetcher",
            return_value=nullcontext(
                mock.Mock(
                    fetch=mock.Mock(
                        side_effect=[
                            mock.Mock(
                                html=interstitial,
                                blocked=False,
                                blocked_reason=None,
                                status_code=200,
                                final_url=
                                "https://javdb.com/users/collection_actors",
                                title="JavDB",
                                requested_url=
                                "https://javdb.com/users/collection_actors",
                            )
                        ]
                    )
                )
            ),
        ), mock.patch(
            "app.collection.actors.collect_actors.find_next_url",
        ) as find_next_url, mock.patch(
            "app.collection.actors.collect_actors.sleep_with_cancel",
            return_value=None,
        ):
            items = gca.crawl_all_pages("cookie.json")

        self.assertEqual(items, [])
        find_next_url.assert_not_called()

    def test_crawl_all_pages_can_save_and_compare_response_html(self) -> None:
        runtime_html = "<html><body><section><div id='actors'></div></section></body></html>"
        baseline_html = "<html><body><section>baseline</section></body></html>"

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dump_path = temp_path / "runtime.html"
            compare_path = temp_path / "baseline.html"
            compare_path.write_text(baseline_html, encoding="utf-8")

            with self.assertLogs(
                "crawljav", level="INFO"
            ) as captured, mock.patch(
                "app.collection.actors.collect_actors.load_cookie_dict",
                return_value={
                    "over18": "1",
                    "cf_clearance": "x",
                    "_jdb_session": "y"
                },
            ), mock.patch(
                "app.collection.actors.collect_actors.create_fetcher",
                return_value=nullcontext(
                    mock.Mock(
                        fetch=mock.Mock(
                            side_effect=[
                                mock.Mock(
                                    html=runtime_html,
                                    blocked=False,
                                    blocked_reason=None,
                                    status_code=200,
                                    final_url=
                                    "https://javdb.com/users/collection_actors",
                                    title="JavDB",
                                    requested_url=
                                    "https://javdb.com/users/collection_actors",
                                )
                            ]
                        )
                    )
                ),
            ), mock.patch(
                "app.collection.actors.collect_actors._build_soup",
                return_value=object(),
            ), mock.patch(
                "app.collection.actors.collect_actors._log_interstitial_hint",
                return_value=None,
            ), mock.patch(
                "app.collection.actors.collect_actors._parse_actors_from_soup",
                return_value=[],
            ), mock.patch(
                "app.collection.actors.collect_actors._is_interstitial_page",
                return_value=False,
            ), mock.patch(
                "app.collection.actors.collect_actors.find_next_url",
                side_effect=[None],
            ), mock.patch(
                "app.collection.actors.collect_actors.sleep_with_cancel",
                return_value=None,
            ):
                items = gca.crawl_all_pages(
                    "cookie.json",
                    response_dump_path=str(dump_path),
                    compare_with_path=str(compare_path),
                )

            self.assertEqual(items, [])
            self.assertEqual(
                dump_path.read_text(encoding="utf-8"), runtime_html
            )
            self.assertTrue(
                any("响应页面已保存" in message for message in captured.output),
                msg=f"未记录保存日志: {captured.output}",
            )
            self.assertTrue(
                any("对比基准页面结果" in message for message in captured.output),
                msg=f"未记录对比日志: {captured.output}",
            )

    def test_crawl_all_pages_browser_mode_parses_actors(self) -> None:
        html = """
        <html><body>
          <section>
            <div id="actors">
              <div class="box actor-box">
                <a href="/actors/abc"><strong>Actor A</strong></a>
              </div>
            </div>
          </section>
        </body></html>
        """
        fake_result = mock.Mock(
            html=html,
            blocked=False,
            blocked_reason=None,
            status_code=200,
            final_url="https://javdb.com/users/collection_actors",
            title="JavDB",
        )
        fake_fetcher = mock.Mock()
        fake_fetcher.fetch.return_value = fake_result

        with mock.patch(
            "app.collection.actors.collect_actors.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.collect_actors.create_fetcher",
            return_value=nullcontext(fake_fetcher),
        ), mock.patch(
            "app.collection.actors.collect_actors.find_next_url",
            return_value=None,
        ):
            items = gca.crawl_all_pages(
                "cookie.json",
                fetch_config={"mode": "browser"},
            )

        self.assertEqual(
            items, [{
                "href": "https://javdb.com/actors/abc",
                "strong": "Actor A"
            }]
        )

    def test_crawl_all_pages_uses_runtime_base_url_for_actor_href(self) -> None:
        html = """
        <html><body>
          <section>
            <div id="actors">
              <div class="box actor-box">
                <a href="/actors/abc"><strong>Actor A</strong></a>
              </div>
            </div>
          </section>
        </body></html>
        """
        fake_result = mock.Mock(
            html=html,
            blocked=False,
            blocked_reason=None,
            status_code=200,
            final_url="https://mirror-javdb.com/users/collection_actors",
            title="JavDB",
        )
        fake_fetcher = mock.Mock()
        fake_fetcher.fetch.return_value = fake_result
        previous_base_url = config.BASE_URL
        config.BASE_URL = "https://mirror-javdb.com"
        try:
            with mock.patch(
                "app.collection.actors.collect_actors.load_cookie_dict",
                return_value={
                    "over18": "1",
                    "cf_clearance": "x",
                    "_jdb_session": "y"
                },
            ), mock.patch(
                "app.collection.actors.collect_actors.create_fetcher",
                return_value=nullcontext(fake_fetcher),
            ), mock.patch(
                "app.collection.actors.collect_actors.find_next_url",
                return_value=None,
            ):
                items = gca.crawl_all_pages(
                    "cookie.json",
                    fetch_config={"mode": "browser"},
                )
        finally:
            config.BASE_URL = previous_base_url

        self.assertEqual(
            items,
            [{
                "href": "https://mirror-javdb.com/actors/abc",
                "strong": "Actor A"
            }],
        )

    def test_crawl_all_pages_browser_mode_raises_on_blocked_result(
        self
    ) -> None:
        fake_result = mock.Mock(
            html="<html><title>Attention Required! | Cloudflare</title></html>",
            blocked=True,
            blocked_reason="cloudflare",
            status_code=403,
            final_url="https://javdb.com/users/collection_actors",
            title="Attention Required! | Cloudflare",
        )
        fake_fetcher = mock.Mock()
        fake_fetcher.fetch.return_value = fake_result

        with mock.patch(
            "app.collection.actors.collect_actors.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.collect_actors.create_fetcher",
            return_value=nullcontext(fake_fetcher),
        ):
            with self.assertRaises(RuntimeError):
                gca.crawl_all_pages(
                    "cookie.json",
                    fetch_config={"mode": "browser"},
                )

    def test_crawl_all_pages_browser_mode_requires_cookie(self) -> None:
        with mock.patch(
            "app.collection.actors.collect_actors.load_cookie_dict",
            side_effect=SystemExit("Cookie 缺少关键字段或为空，退出。"),
        ), mock.patch(
            "app.collection.actors.collect_actors.create_fetcher",
            side_effect=AssertionError("Cookie 无效时不应进入 create_fetcher"),
        ) as create_fetcher_mock:
            with self.assertRaises(SystemExit):
                gca.crawl_all_pages(
                    "cookie.json",
                    fetch_config={"mode": "browser"},
                )

        create_fetcher_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
