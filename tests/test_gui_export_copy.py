import unittest

import app.gui.data_view as gdv


class GuiExportCopyTests(unittest.TestCase):

    def setUp(self) -> None:
        self.selected_rows = [
            {
                "actor": "Alice",
                "code": "ABF-001",
                "title": "Title A",
                "href": "h1",
                "has_magnets": True,
                "is_uncensored": False,
                "has_subtitle": False,
            },
            {
                "actor": "Alice",
                "code": "ABS-002",
                "title": "Title B",
                "href": "h2",
                "has_magnets": True,
                "is_uncensored": False,
                "has_subtitle": False,
            },
        ]
        self.actor_magnets = {
            "ABF-001": [
                {
                    "magnet": "magnet:?xt=urn:btih:111"
                },
                {
                    "magnet": ""
                },
                {
                    "magnet": "magnet:?xt=urn:btih:111"
                },
            ],
            "ABS-002": [{
                "magnet": "magnet:?xt=urn:btih:222"
            },],
        }

    def test_build_magnet_export_lines_groups_by_work_and_dedupes(self) -> None:
        lines = gdv.build_magnet_export_lines(
            self.selected_rows, self.actor_magnets
        )
        self.assertEqual(
            lines,
            [
                "# ABF-001 | Title A",
                "magnet:?xt=urn:btih:111",
                "",
                "# ABS-002 | Title B",
                "magnet:?xt=urn:btih:222",
            ],
        )

    def test_build_copy_text_for_code_title_and_magnet(self) -> None:
        self.assertEqual(
            gdv.build_copy_text("code", self.selected_rows, self.actor_magnets),
            "ABF-001\nABS-002",
        )
        self.assertEqual(
            gdv.build_copy_text(
                "title", self.selected_rows, self.actor_magnets
            ),
            "Title A\nTitle B",
        )
        self.assertEqual(
            gdv.build_copy_text(
                "magnet", self.selected_rows, self.actor_magnets
            ),
            "magnet:?xt=urn:btih:111\nmagnet:?xt=urn:btih:222",
        )

    def test_build_copy_text_returns_empty_for_no_selection(self) -> None:
        self.assertEqual(
            gdv.build_copy_text("code", [], self.actor_magnets), ""
        )
        self.assertEqual(
            gdv.build_copy_text("title", [], self.actor_magnets), ""
        )
        self.assertEqual(
            gdv.build_copy_text("magnet", [], self.actor_magnets), ""
        )


if __name__ == "__main__":
    unittest.main()
