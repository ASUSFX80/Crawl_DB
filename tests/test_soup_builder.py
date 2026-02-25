import unittest
from unittest import mock

from bs4 import FeatureNotFound

import app.core.utils as utils


class SoupBuilderTests(unittest.TestCase):

    def test_build_soup_falls_back_to_html_parser_when_lxml_missing(
        self
    ) -> None:
        fallback_soup = object()
        original_flag = utils._soup_fallback_warned
        utils._soup_fallback_warned = False
        with mock.patch(
            "app.core.utils.BeautifulSoup",
            side_effect=[FeatureNotFound("lxml missing"), fallback_soup],
        ):
            with self.assertLogs("crawljav", level="WARNING") as captured:
                result = utils.build_soup("<html></html>")

        utils._soup_fallback_warned = original_flag
        self.assertIs(result, fallback_soup)
        self.assertTrue(any("lxml 不可用" in line for line in captured.output))


if __name__ == "__main__":
    unittest.main()
