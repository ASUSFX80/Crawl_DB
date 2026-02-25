import importlib
import unittest


class CollectionActorsImportTests(unittest.TestCase):

    def test_new_actor_modules_are_importable(self) -> None:
        modules = [
            "app.collection.actors.collect_actors",
            "app.collection.actors.actor_works",
            "app.collection.actors.actor_magnets",
        ]
        for module_name in modules:
            with self.subTest(module=module_name):
                importlib.import_module(module_name)

    def test_old_collectors_package_removed(self) -> None:
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("app.collectors")


if __name__ == "__main__":
    unittest.main()
