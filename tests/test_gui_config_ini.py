import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.gui.gui_config as gui_config


class GuiConfigIniTests(unittest.TestCase):

    def test_to_storable_path_prefers_relative_for_runtime_root_children(
        self
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            db_path = runtime_root / "userdata" / "actors.db"
            result = gui_config.to_storable_path(db_path, runtime_root)
            self.assertEqual(result, str(Path("userdata") / "actors.db"))

    def test_resolve_stored_path_handles_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            result = gui_config.resolve_stored_path("cookie.json", runtime_root)
            self.assertEqual(
                result, (runtime_root / "cookie.json").resolve(strict=False)
            )

    def test_save_and_load_ini_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            config_file = runtime_root / "config.ini"
            gui_config.save_ini_config(
                config_file=config_file,
                runtime_root=runtime_root,
                cookie_path=runtime_root / "cookie.json",
                db_path=runtime_root / "userdata" / "actors.db",
                output_dir=runtime_root / "userdata" / "magnets",
                delay_range="0.8-1.6",
                fetch_mode="browser",
                collect_scope="series",
                browser_user_data_dir=runtime_root / "userdata" /
                "browser_profile" / "javdb",
                browser_headless=False,
                browser_timeout_seconds=45,
                challenge_timeout_seconds=240,
                migrated_from_legacy=True,
            )
            loaded = gui_config.load_ini_config(config_file, runtime_root)
            self.assertEqual(
                loaded["cookie"],
                (runtime_root / "cookie.json").resolve(strict=False)
            )
            self.assertEqual(
                loaded["db"],
                (runtime_root / "userdata" / "actors.db").resolve(strict=False),
            )
            self.assertEqual(
                loaded["output_dir"],
                (runtime_root / "userdata" / "magnets").resolve(strict=False),
            )
            self.assertEqual(loaded["delay_range"], "0.8-1.6")
            self.assertEqual(loaded["fetch_mode"], "browser")
            self.assertEqual(loaded["collect_scope"], "actor")
            self.assertEqual(
                loaded["browser_user_data_dir"],
                (runtime_root / "userdata" / "browser_profile" /
                 "javdb").resolve(strict=False),
            )
            self.assertFalse(loaded["browser_headless"])
            self.assertEqual(loaded["browser_timeout_seconds"], 45)
            self.assertEqual(loaded["challenge_timeout_seconds"], 240)
            self.assertTrue(loaded["migrated_from_legacy"])

    def test_migrate_legacy_config_uses_qsettings_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root = Path(tmp) / "legacy"
            legacy_root.mkdir(parents=True, exist_ok=True)
            (legacy_root / "cookie.json"
            ).write_text("{\"cookie\":\"over18=1\"}", encoding="utf-8")
            custom_db = legacy_root / "custom.db"
            custom_db.write_text("", encoding="utf-8")
            config_file = runtime_root / "config.ini"

            loaded = gui_config.migrate_legacy_config_once(
                config_file=config_file,
                runtime_root=runtime_root,
                qsettings_defaults={
                    "cookie": str(legacy_root / "cookie.json"),
                    "db": str(custom_db),
                    "output_dir": str(legacy_root / "userdata" / "magnets"),
                    "delay_range": "1.0-2.0",
                },
                legacy_root=legacy_root,
            )
            self.assertEqual(
                loaded["cookie"],
                (legacy_root / "cookie.json").resolve(strict=False)
            )
            self.assertEqual(loaded["db"], custom_db.resolve(strict=False))
            self.assertEqual(loaded["delay_range"], "1.0-2.0")
            self.assertTrue(config_file.exists())

    def test_load_ini_config_defaults_collect_scope_to_actor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            config_file = runtime_root / "config.ini"
            config_file.write_text(
                "\n".join([
                    "[paths]",
                    "cookie = cookie.json",
                    "db = userdata/actors.db",
                    "output_dir = userdata/magnets",
                    "",
                    "[fetch]",
                    "mode = httpx",
                    "collect_scope = unknown",
                ]),
                encoding="utf-8",
            )
            loaded = gui_config.load_ini_config(config_file, runtime_root)
            self.assertEqual(loaded["collect_scope"], "actor")

    def test_load_ini_config_defaults_fetch_mode_to_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            config_file = runtime_root / "config.ini"
            config_file.write_text(
                "\n".join([
                    "[paths]",
                    "cookie = cookie.json",
                    "db = userdata/actors.db",
                    "output_dir = userdata/magnets",
                ]),
                encoding="utf-8",
            )
            loaded = gui_config.load_ini_config(config_file, runtime_root)
            self.assertEqual(loaded["fetch_mode"], "browser")

    def test_load_ini_config_silently_fallbacks_smart_mode_to_browser(
        self
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            config_file = runtime_root / "config.ini"
            config_file.write_text(
                "\n".join([
                    "[paths]",
                    "cookie = cookie.json",
                    "db = userdata/actors.db",
                    "output_dir = userdata/magnets",
                    "",
                    "[fetch]",
                    "mode = smart",
                ]),
                encoding="utf-8",
            )
            loaded = gui_config.load_ini_config(config_file, runtime_root)
            self.assertEqual(loaded["fetch_mode"], "browser")

    def test_save_and_load_ini_config_roundtrip_base_domain_segment(
        self
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            config_file = runtime_root / "config.ini"
            gui_config.save_ini_config(
                config_file=config_file,
                runtime_root=runtime_root,
                cookie_path=runtime_root / "cookie.json",
                db_path=runtime_root / "userdata" / "actors.db",
                output_dir=runtime_root / "userdata" / "magnets",
                delay_range="0.8-1.6",
                base_domain_segment="mirror-javdb",
            )
            loaded = gui_config.load_ini_config(config_file, runtime_root)
            self.assertEqual(loaded["base_domain_segment"], "mirror-javdb")

    def test_load_ini_config_defaults_base_domain_segment_to_javdb(
        self
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            config_file = runtime_root / "config.ini"
            config_file.write_text(
                "\n".join([
                    "[paths]",
                    "cookie = cookie.json",
                    "db = userdata/actors.db",
                    "output_dir = userdata/magnets",
                ]),
                encoding="utf-8",
            )
            loaded = gui_config.load_ini_config(config_file, runtime_root)
            self.assertEqual(loaded["base_domain_segment"], "javdb")

    def test_select_runtime_root_frozen_prefers_home_crawljav_even_if_executable_dir_writable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            cwd = root / "cwd"
            app_dir = root / "Applications" / "crawljav.app" / "Contents" / "MacOS"
            exe = app_dir / "crawljav"
            home.mkdir(parents=True, exist_ok=True)
            cwd.mkdir(parents=True, exist_ok=True)
            app_dir.mkdir(parents=True, exist_ok=True)
            exe.write_text("", encoding="utf-8")

            with mock.patch.object(
                gui_config, "is_writable_dir", return_value=True
            ):
                runtime_root, fallback_used = gui_config.select_runtime_root(
                    frozen=True,
                    executable=str(exe),
                    cwd=cwd,
                    home=home,
                )

            self.assertEqual(runtime_root, (home / ".crawljav").resolve())
            self.assertFalse(fallback_used)

    def test_select_runtime_root_frozen_fallbacks_when_home_unwritable(
        self
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            cwd = root / "cwd"
            app_dir = root / "Applications" / "crawljav.app" / "Contents" / "MacOS"
            exe = app_dir / "crawljav"
            home.mkdir(parents=True, exist_ok=True)
            cwd.mkdir(parents=True, exist_ok=True)
            app_dir.mkdir(parents=True, exist_ok=True)
            exe.write_text("", encoding="utf-8")
            home_runtime = (home / ".crawljav").resolve()
            preferred = app_dir.resolve()

            def _fake_writable(path: Path) -> bool:
                resolved = path.resolve()
                if resolved == home_runtime:
                    return False
                if resolved == preferred:
                    return True
                return False

            with mock.patch.object(
                gui_config, "is_writable_dir", side_effect=_fake_writable
            ):
                runtime_root, fallback_used = gui_config.select_runtime_root(
                    frozen=True,
                    executable=str(exe),
                    cwd=cwd,
                    home=home,
                )

            self.assertEqual(runtime_root, preferred)
            self.assertTrue(fallback_used)

    def test_select_runtime_root_non_frozen_behavior_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            cwd = root / "cwd"
            app_dir = root / "app"
            exe = app_dir / "crawljav"
            home.mkdir(parents=True, exist_ok=True)
            cwd.mkdir(parents=True, exist_ok=True)
            app_dir.mkdir(parents=True, exist_ok=True)
            exe.write_text("", encoding="utf-8")

            with mock.patch.object(
                gui_config, "is_writable_dir", return_value=True
            ):
                runtime_root, fallback_used = gui_config.select_runtime_root(
                    frozen=False,
                    executable=str(exe),
                    cwd=cwd,
                    home=home,
                )

            self.assertEqual(runtime_root, cwd.resolve())
            self.assertFalse(fallback_used)


if __name__ == "__main__":
    unittest.main()
