import datetime
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.utils import setup_daily_file_logger


class UtilsLoggingTests(unittest.TestCase):

    def test_setup_daily_file_logger_falls_back_when_log_dir_unwritable(
        self
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blocked = tmp_path / "blocked"
            blocked.write_text("not a dir", encoding="utf-8")

            logger = logging.getLogger("test_utils_logging_fallback")
            logger.setLevel(logging.INFO)
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

            today = datetime.date(2026, 2, 4)
            with patch("app.core.utils.Path.home", return_value=tmp_path):
                log_path = setup_daily_file_logger(
                    log_dir=str(blocked), date=today, logger=logger
                )

            expected = tmp_path / ".crawljav" / "logs" / "2026-02-04.log"
            self.assertEqual(log_path, expected)
            self.assertTrue(log_path.exists())


if __name__ == "__main__":
    unittest.main()
