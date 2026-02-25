import importlib
import unittest


class PackageLayoutTests(unittest.TestCase):

    def test_new_gui_only_package_layout_is_importable(self) -> None:
        modules = [
            "app.core.config",
            "app.core.fetch_runtime",
            "app.core.storage",
            "app.core.utils",
            "app.collection",
            "app.collection.actors",
            "app.collection.actors.collect_actors",
            "app.collection.actors.actor_works",
            "app.collection.actors.actor_magnets",
            "app.collection.actors.pipeline",
            "app.gui.gui_config",
            "app.gui.data_view",
            "app.gui.main_window",
            "app.exporters.mdcx_magnets",
        ]
        for module_name in modules:
            with self.subTest(module=module_name):
                importlib.import_module(module_name)


if __name__ == "__main__":
    unittest.main()
