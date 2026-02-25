import unittest
from contextlib import nullcontext
from unittest import mock

import app.collection.actors.actor_magnets as gwm
from app.core.utils import CancelledError, set_cancel_checker


class WorksMagnetBrowserTests(unittest.TestCase):

    def test_run_magnet_jobs_respects_cancel_checker(self) -> None:
        fake_result = mock.Mock(
            html="<div id=\"magnets-content\"></div>",
            blocked=False,
            blocked_reason=None,
            status_code=200,
            final_url="https://javdb.com/v/abc",
            title="JavDB",
        )
        fake_fetcher = mock.Mock()
        fake_fetcher.fetch.return_value = fake_result

        fake_store = mock.Mock()
        fake_store.get_all_actor_works.return_value = {
            "Actor A": [{
                "code": "ABF-001",
                "href": "https://javdb.com/v/abc",
                "title": "T"
            }]
        }
        fake_store.get_actor_href.return_value = "https://javdb.com/actors/abc"
        fake_store.save_magnets.return_value = 1

        storage_cm = mock.Mock()
        storage_cm.__enter__ = mock.Mock(return_value=fake_store)
        storage_cm.__exit__ = mock.Mock(return_value=False)

        with mock.patch(
            "app.collection.actors.actor_magnets.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.actor_magnets.Storage",
            return_value=storage_cm,
        ), mock.patch(
            "app.collection.actors.actor_magnets.create_fetcher",
            return_value=nullcontext(fake_fetcher),
        ):
            set_cancel_checker(lambda: True)
            try:
                with self.assertRaises(CancelledError):
                    gwm.run_magnet_jobs(
                        out_root="userdata/magnets",
                        cookie_json="cookie.json",
                        db_path="userdata/actors.db",
                        fetch_config={"mode": "browser"},
                    )
            finally:
                set_cancel_checker(None)

        fake_fetcher.fetch.assert_not_called()

    def test_run_magnet_jobs_browser_mode_fetches_and_saves(self) -> None:
        html = """
        <div id=\"magnets-content\">
          <div>
            <div class=\"magnet-name column is-four-fifths\">
              <a href=\"magnet:?xt=urn:btih:123\"><span class=\"meta\">1.2 GB</span></a>
            </div>
          </div>
        </div>
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

        fake_store = mock.Mock()
        fake_store.get_all_actor_works.return_value = {
            "Actor A": [{
                "code": "ABF-001",
                "href": "https://javdb.com/v/abc",
                "title": "T"
            }]
        }
        fake_store.get_actor_href.return_value = "https://javdb.com/actors/abc"
        fake_store.save_magnets.return_value = 1

        storage_cm = mock.Mock()
        storage_cm.__enter__ = mock.Mock(return_value=fake_store)
        storage_cm.__exit__ = mock.Mock(return_value=False)

        with mock.patch(
            "app.collection.actors.actor_magnets.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.actor_magnets.Storage",
            return_value=storage_cm,
        ), mock.patch(
            "app.collection.actors.actor_magnets.create_fetcher",
            return_value=nullcontext(fake_fetcher),
        ), mock.patch(
            "app.collection.actors.actor_magnets.sleep_with_cancel",
            return_value=None,
        ):
            summary = gwm.run_magnet_jobs(
                out_root="userdata/magnets",
                cookie_json="cookie.json",
                db_path="userdata/actors.db",
                fetch_config={"mode": "browser"},
            )

        self.assertIn("Actor A", summary)
        fake_store.save_magnets.assert_called()

    def test_run_magnet_jobs_raises_on_blocked_result(self) -> None:
        fake_result = mock.Mock(
            html="<html><title>Attention Required! | Cloudflare</title></html>",
            blocked=True,
            blocked_reason="cloudflare",
            status_code=403,
            final_url="https://javdb.com/v/abc",
            title="Attention Required! | Cloudflare",
        )
        fake_fetcher = mock.Mock()
        fake_fetcher.fetch.return_value = fake_result

        fake_store = mock.Mock()
        fake_store.get_all_actor_works.return_value = {
            "Actor A": [{
                "code": "ABF-001",
                "href": "https://javdb.com/v/abc",
                "title": "T"
            }]
        }
        fake_store.get_actor_href.return_value = "https://javdb.com/actors/abc"

        storage_cm = mock.Mock()
        storage_cm.__enter__ = mock.Mock(return_value=fake_store)
        storage_cm.__exit__ = mock.Mock(return_value=False)

        with mock.patch(
            "app.collection.actors.actor_magnets.load_cookie_dict",
            return_value={
                "over18": "1",
                "cf_clearance": "x",
                "_jdb_session": "y"
            },
        ), mock.patch(
            "app.collection.actors.actor_magnets.Storage",
            return_value=storage_cm,
        ), mock.patch(
            "app.collection.actors.actor_magnets.create_fetcher",
            return_value=nullcontext(fake_fetcher),
        ), mock.patch(
            "app.collection.actors.actor_magnets.sleep_with_cancel",
            return_value=None,
        ):
            with self.assertRaises(RuntimeError):
                gwm.run_magnet_jobs(
                    out_root="userdata/magnets",
                    cookie_json="cookie.json",
                    db_path="userdata/actors.db",
                    fetch_config={"mode": "browser"},
                )

    def test_run_magnet_jobs_browser_mode_requires_cookie(self) -> None:
        with mock.patch(
            "app.collection.actors.actor_magnets.load_cookie_dict",
            side_effect=SystemExit("Cookie 缺少关键字段或为空，退出。"),
        ), mock.patch(
            "app.collection.actors.actor_magnets.create_fetcher",
            side_effect=AssertionError("Cookie 无效时不应进入 create_fetcher"),
        ) as create_fetcher_mock:
            with self.assertRaises(SystemExit):
                gwm.run_magnet_jobs(
                    out_root="userdata/magnets",
                    cookie_json="cookie.json",
                    db_path="userdata/actors.db",
                    fetch_config={"mode": "browser"},
                )

        create_fetcher_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
