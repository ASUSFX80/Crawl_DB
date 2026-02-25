import json
import tempfile
import unittest
from pathlib import Path


class UtilsCookieTests(unittest.TestCase):

    def test_load_cookie_dict_supports_legacy_dict_format(self) -> None:
        from app.core.utils import load_cookie_dict

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookie.json"
            path.write_text(
                json.dumps({
                    "cf_clearance": "a",
                    "_jdb_session": "b",
                    "over18": "1",
                }),
                encoding="utf-8",
            )

            cookies = load_cookie_dict(str(path))

        self.assertEqual(cookies["cf_clearance"], "a")
        self.assertEqual(cookies["_jdb_session"], "b")
        self.assertEqual(cookies["over18"], "1")

    def test_load_cookie_dict_supports_cookie_items_format(self) -> None:
        from app.core.utils import load_cookie_dict

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookie.json"
            path.write_text(
                json.dumps({
                    "cookies": [{
                        "name": "cf_clearance",
                        "value": "a",
                        "domain": ".javdb.com",
                        "path": "/",
                    }, {
                        "name": "_jdb_session",
                        "value": "b",
                        "domain": ".javdb.com",
                        "path": "/",
                    }, {
                        "name": "over18",
                        "value": "1",
                        "domain": ".javdb.com",
                        "path": "/",
                    }]
                }),
                encoding="utf-8",
            )

            cookies = load_cookie_dict(str(path))

        self.assertEqual(cookies["cf_clearance"], "a")
        self.assertEqual(cookies["_jdb_session"], "b")
        self.assertEqual(cookies["over18"], "1")
        self.assertIn("__playwright_cookie_items__", cookies)
        self.assertEqual(len(cookies["__playwright_cookie_items__"]), 3)

    def test_load_cookie_dict_rejects_invalid_cookie_items_format(self) -> None:
        from app.core.utils import load_cookie_dict

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookie.json"
            path.write_text(
                json.dumps({"cookies": "invalid"}), encoding="utf-8"
            )

            with self.assertRaises(SystemExit):
                load_cookie_dict(str(path))


if __name__ == "__main__":
    unittest.main()
