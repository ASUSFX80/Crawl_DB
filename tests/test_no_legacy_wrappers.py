from pathlib import Path
import unittest


class NoLegacyWrappersTests(unittest.TestCase):

    def test_root_legacy_wrapper_files_removed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        legacy_files = [
            "collect_scopes.py",
            "config.py",
            "fetch_runtime.py",
            "get_actor_works.py",
            "get_collect_actors.py",
            "get_collect_scope_magnets.py",
            "get_collect_scope_works.py",
            "get_works_magnet.py",
            "gui_config.py",
            "gui_data_view.py",
            "mdcx_magnets.py",
            "storage.py",
            "utils.py",
        ]
        for filename in legacy_files:
            with self.subTest(file=filename):
                self.assertFalse((root / filename).exists())


if __name__ == "__main__":
    unittest.main()
