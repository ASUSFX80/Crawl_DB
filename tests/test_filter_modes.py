import unittest

import app.collection.actors.actor_magnets as gm


class FilterModesTests(unittest.TestCase):

    def test_normalize_filters_supports_cn_comma_and_dedupe(self) -> None:
        values = gm._normalize_filters("ABF-001, ABS-002，  ABF-001")
        self.assertEqual(values, ["ABF-001", "ABS-002"])

    def test_filter_works_by_code_keywords_contains_ignore_case(self) -> None:
        works = [
            {
                "code": "ABF-001",
                "title": "t1",
                "href": "h1"
            },
            {
                "code": "FC2-ABF-123",
                "title": "t2",
                "href": "h2"
            },
            {
                "code": "XYZ-999",
                "title": "t3",
                "href": "h3"
            },
        ]
        result = gm._filter_works_by_code_keywords(works, ["abf"])
        self.assertEqual([item["code"] for item in result],
                         ["ABF-001", "FC2-ABF-123"])

    def test_filter_works_by_series_prefixes_startswith_ignore_case(
        self
    ) -> None:
        works = [
            {
                "code": "ABF-001",
                "title": "t1",
                "href": "h1"
            },
            {
                "code": "XABF-001",
                "title": "t2",
                "href": "h2"
            },
            {
                "code": "abf-777",
                "title": "t3",
                "href": "h3"
            },
        ]
        result = gm._filter_works_by_series_prefixes(works, ["ABF"])
        self.assertEqual([item["code"] for item in result],
                         ["ABF-001", "abf-777"])

    def test_filter_priority_actor_then_code_then_series(self) -> None:
        all_works = {
            "A": [{
                "code": "ABF-001",
                "title": "t1",
                "href": "h1"
            }],
            "B": [{
                "code": "ABS-001",
                "title": "t2",
                "href": "h2"
            }],
        }
        filtered_actor = gm._apply_work_filters(
            all_works,
            actor_filters=["A"],
            code_keywords=["ABS"],
            series_prefixes=["ABS"],
        )
        self.assertEqual(list(filtered_actor.keys()), ["A"])

        filtered_code = gm._apply_work_filters(
            all_works,
            actor_filters=[],
            code_keywords=["ABS"],
            series_prefixes=["ABF"],
        )
        self.assertEqual(list(filtered_code.keys()), ["B"])

        filtered_series = gm._apply_work_filters(
            all_works,
            actor_filters=[],
            code_keywords=[],
            series_prefixes=["ABF"],
        )
        self.assertEqual(list(filtered_series.keys()), ["A"])


if __name__ == "__main__":
    unittest.main()
