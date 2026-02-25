import unittest

import app.gui.data_view as gdv


class GuiDataViewTests(unittest.TestCase):

    def setUp(self) -> None:
        self.works_cache = {
            "Alice": [
                {
                    "code": "ABF-001-C",
                    "title": "First Work",
                    "href": "h1"
                },
                {
                    "code": "FC2-U123",
                    "title": "Second Work",
                    "href": "h2"
                },
            ],
            "Bob": [{
                "code": "ABS-100",
                "title": "Another Title",
                "href": "h3"
            },],
        }
        self.magnets_cache = {
            "Alice": {
                "ABF-001-C": [{
                    "magnet": "m1"
                }]
            },
            "Bob": {
                "ABS-100": [{
                    "magnet": "m2"
                }]
            },
        }

    def test_search_rows_matches_code_contains_ignore_case(self) -> None:
        rows = gdv.build_rows(self.works_cache, self.magnets_cache)
        matched = gdv.search_rows(rows, mode="code", keyword="abf-001")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["code"], "ABF-001-C")

    def test_search_rows_matches_title_contains_ignore_case(self) -> None:
        rows = gdv.build_rows(self.works_cache, self.magnets_cache)
        matched = gdv.search_rows(rows, mode="title", keyword="another")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["actor"], "Bob")

    def test_filter_rows_applies_and_logic(self) -> None:
        rows = gdv.build_rows(self.works_cache, self.magnets_cache)
        matched = gdv.filter_rows(
            rows,
            magnet_state="with",
            code_state="coded",
            subtitle_state="subtitle",
        )
        self.assertEqual([row["code"] for row in matched], ["ABF-001-C"])

    def test_sort_actor_names_and_works(self) -> None:
        rows = gdv.build_rows(self.works_cache, self.magnets_cache)
        names = gdv.sort_actor_names(rows, desc=False)
        self.assertEqual(names, ["Alice", "Bob"])

        alice_rows = [row for row in rows if row["actor"] == "Alice"]
        code_desc = gdv.sort_actor_works(alice_rows, key="code", desc=True)
        self.assertEqual([row["code"] for row in code_desc],
                         ["FC2-U123", "ABF-001-C"])

        title_asc = gdv.sort_actor_works(alice_rows, key="title", desc=False)
        self.assertEqual([row["title"] for row in title_asc],
                         ["First Work", "Second Work"])

    def test_empty_inputs_return_empty_without_errors(self) -> None:
        rows = gdv.build_rows({}, {})
        self.assertEqual(rows, [])
        self.assertEqual(gdv.search_rows(rows, mode="actor", keyword="x"), [])
        self.assertEqual(
            gdv.filter_rows(
                rows,
                magnet_state="all",
                code_state="all",
                subtitle_state="all"
            ),
            [],
        )
        self.assertEqual(gdv.sort_actor_names(rows), [])
        self.assertEqual(gdv.sort_actor_works(rows, key="code"), [])


if __name__ == "__main__":
    unittest.main()
