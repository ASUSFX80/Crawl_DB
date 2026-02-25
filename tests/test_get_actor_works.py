import unittest
from contextlib import nullcontext
from unittest import mock

import app.collection.actors.actor_works as gaw
import app.core.config as config
from app.core.utils import CancelledError, set_cancel_checker


class ActorWorksBrowserTests(unittest.TestCase):

    def test_parse_works_uses_runtime_base_url_for_href(self) -> None:
        html = """
        <html><body>
          <section>
            <div>
              <div class=\"movie-list h cols-4 vcols-8\">
                <div>
                  <a href=\"/v/abc\">
                    <div class=\"video-title\"><strong>ABF-001</strong> Title</div>
                  </a>
                </div>
              </div>
            </div>
          </section>
        </body></html>
        """
        previous_base_url = config.BASE_URL
        config.BASE_URL = "https://mirror-javdb.com"
        try:
            rows = gaw.parse_works(html)
        finally:
            config.BASE_URL = previous_base_url
        self.assertEqual(rows[0]["href"], "https://mirror-javdb.com/v/abc")

    def test_crawl_actor_works_respects_cancel_checker(self) -> None:
        html = """
        <html><body>
          <section>
            <div>
              <div class="movie-list">
                <div>
                  <a href="/v/abc">
                    <div class="video-title"><strong>ABF-001</strong> Title</div>
                  </a>
                </div>
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
            final_url="https://javdb.com/actors/abc",
            title="JavDB",
        )
        fake_fetcher = mock.Mock()
        fake_fetcher.fetch.return_value = fake_result

        with mock.patch(
            "app.collection.actors.actor_works.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.actor_works.create_fetcher",
            return_value=nullcontext(fake_fetcher),
        ):
            set_cancel_checker(lambda: True)
            try:
                with self.assertRaises(CancelledError):
                    gaw.crawl_actor_works(
                        start_url="https://javdb.com/actors/abc",
                        cookie_json="cookie.json",
                        fetch_config={"mode": "browser"},
                    )
            finally:
                set_cancel_checker(None)

        fake_fetcher.fetch.assert_not_called()

    def test_crawl_actor_works_browser_mode_parses_works(self) -> None:
        html = """
        <html><body>
          <section>
            <div>
              <div class=\"movie-list h cols-4 vcols-8\">
                <div>
                  <a href=\"/v/abc\">
                    <div class=\"video-title\"><strong>ABF-001</strong> Title</div>
                  </a>
                </div>
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
            final_url="https://javdb.com/v/abc",
            title="JavDB",
        )
        fake_fetcher = mock.Mock()
        fake_fetcher.fetch.return_value = fake_result

        with mock.patch(
            "app.collection.actors.actor_works.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.actor_works.create_fetcher",
            return_value=nullcontext(fake_fetcher),
        ):
            rows = gaw.crawl_actor_works(
                start_url="https://javdb.com/actors/abc",
                cookie_json="cookie.json",
                fetch_config={"mode": "browser"},
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "ABF-001")

    def test_crawl_actor_works_raises_on_blocked_result(self) -> None:
        fake_result = mock.Mock(
            html="<html><title>Attention Required! | Cloudflare</title></html>",
            blocked=True,
            blocked_reason="cloudflare",
            status_code=403,
            final_url="https://javdb.com/actors/abc",
            title="Attention Required! | Cloudflare",
        )
        fake_fetcher = mock.Mock()
        fake_fetcher.fetch.return_value = fake_result

        with mock.patch(
            "app.collection.actors.actor_works.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.actor_works.create_fetcher",
            return_value=nullcontext(fake_fetcher),
        ):
            with self.assertRaises(RuntimeError):
                gaw.crawl_actor_works(
                    start_url="https://javdb.com/actors/abc",
                    cookie_json="cookie.json",
                    fetch_config={"mode": "browser"},
                )

    def test_crawl_actor_works_browser_mode_requires_cookie(self) -> None:
        with mock.patch(
            "app.collection.actors.actor_works.load_cookie_dict",
            side_effect=SystemExit("Cookie 缺少关键字段或为空，退出。"),
        ), mock.patch(
            "app.collection.actors.actor_works.create_fetcher",
            side_effect=AssertionError("Cookie 无效时不应进入 create_fetcher"),
        ) as create_fetcher_mock:
            with self.assertRaises(SystemExit):
                gaw.crawl_actor_works(
                    start_url="https://javdb.com/actors/abc",
                    cookie_json="cookie.json",
                    fetch_config={"mode": "browser"},
                )

        create_fetcher_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
