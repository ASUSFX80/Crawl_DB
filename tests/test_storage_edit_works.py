import tempfile
import unittest
from pathlib import Path

from app.core.storage import Storage


class StorageEditWorksTests(unittest.TestCase):

    def test_update_work_fields_updates_code_title_and_keeps_magnets(
        self
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "actors.db"
            with Storage(db_path) as store:
                store.save_actor_works(
                    "Alice",
                    "https://javdb.com/actors/a",
                    [{
                        "code": "ABF-001",
                        "title": "Old Title",
                        "href": "https://javdb.com/v/1",
                    }],
                )
                store.save_magnets(
                    "Alice",
                    "https://javdb.com/actors/a",
                    "ABF-001",
                    [{
                        "magnet": "magnet:?xt=urn:btih:111"
                    }],
                    title="Old Title",
                    href="https://javdb.com/v/1",
                )

                updated = store.update_work_fields(
                    actor_name="Alice",
                    old_code="ABF-001",
                    new_code="ABF-009",
                    new_title="New Title",
                )
                self.assertTrue(updated)

                works = store.get_actor_works("Alice")
                self.assertEqual(
                    works,
                    [{
                        "code": "ABF-009",
                        "title": "New Title",
                        "href": "https://javdb.com/v/1",
                    }],
                )

                magnets_grouped = store.get_magnets_grouped()
                self.assertIn("Alice", magnets_grouped)
                self.assertIn("ABF-009", magnets_grouped["Alice"])
                self.assertEqual(
                    magnets_grouped["Alice"]["ABF-009"][0]["magnet"],
                    "magnet:?xt=urn:btih:111",
                )

    def test_update_work_fields_raises_on_code_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "actors.db"
            with Storage(db_path) as store:
                store.save_actor_works(
                    "Alice",
                    "https://javdb.com/actors/a",
                    [
                        {
                            "code": "ABF-001",
                            "title": "T1",
                            "href": "https://javdb.com/v/1"
                        },
                        {
                            "code": "ABF-002",
                            "title": "T2",
                            "href": "https://javdb.com/v/2"
                        },
                    ],
                )

                with self.assertRaises(ValueError):
                    store.update_work_fields(
                        actor_name="Alice",
                        old_code="ABF-001",
                        new_code="ABF-002",
                        new_title="Renamed",
                    )

                works = store.get_actor_works("Alice")
                self.assertEqual([work["code"] for work in works],
                                 ["ABF-001", "ABF-002"])


if __name__ == "__main__":
    unittest.main()
