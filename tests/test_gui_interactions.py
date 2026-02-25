import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtGui, QtTest, QtWidgets

import gui


class GuiInteractionTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([]
                                                                             )

    def setUp(self) -> None:
        self._cwd = os.getcwd()
        self._patches = ExitStack()
        for method in (
            "_load_flow_settings",
            "_migrate_legacy_config_once",
            "_load_defaults",
            "_ensure_default_db",
            "_refresh_history",
            "_load_data",
        ):
            self._patches.enter_context(
                mock.patch.object(
                    gui.MainWindow, method, autospec=True, return_value=None
                )
            )
        self.window = gui.MainWindow()
        self.window.hide()

        self.actor_name = "Alice"
        self.rows = [
            {
                "actor": self.actor_name,
                "code": "ABF-001",
                "title": "Title A",
                "href": "https://javdb.com/v/abf001",
                "has_magnets": True,
                "is_uncensored": False,
                "has_subtitle": False,
            },
            {
                "actor": self.actor_name,
                "code": "ABS-002",
                "title": "Title B",
                "href": "https://javdb.com/v/abs002",
                "has_magnets": True,
                "is_uncensored": False,
                "has_subtitle": False,
            },
        ]
        self.window.actor_list.clear()
        self.window.actor_list.addItem(self.actor_name)
        self.window.actor_list.setCurrentRow(0)
        self.window._current_actor_rows = list(self.rows)
        self.window._magnets_cache = {
            self.actor_name: {
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
        }
        self.window._populate_works_table([{
            "code": row["code"],
            "title": row["title"],
            "href": row["href"]
        } for row in self.rows])
        self._select_rows([0, 1])

    def tearDown(self) -> None:
        self.window.close()
        self._patches.close()
        QtWidgets.QApplication.processEvents()
        os.chdir(self._cwd)

    def _select_rows(self, rows: list[int]) -> None:
        model = self.window.works_table.selectionModel()
        model.clearSelection()
        for row in rows:
            index = self.window.works_table.model().index(row, 0)
            model.select(
                index,
                QtCore.QItemSelectionModel.Select |
                QtCore.QItemSelectionModel.Rows,
            )
        QtWidgets.QApplication.processEvents()

    def _press_copy(self, widget: QtWidgets.QWidget) -> None:
        widget.setFocus(QtCore.Qt.ShortcutFocusReason)
        QtWidgets.QApplication.processEvents()
        QtTest.QTest.keySequence(widget, QtGui.QKeySequence.Copy)
        QtWidgets.QApplication.processEvents()

    def test_copy_selected_works_code_updates_clipboard(self) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.clear()
        with mock.patch("gui.QtWidgets.QMessageBox.information") as info:
            self.window._copy_selected_works("code")
        self.assertEqual(clipboard.text(), "ABF-001\nABS-002")
        info.assert_called_once()

    def test_copy_selected_works_magnet_deduped_and_non_empty(self) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.clear()
        with mock.patch("gui.QtWidgets.QMessageBox.information") as info:
            self.window._copy_selected_works("magnet")
        self.assertEqual(
            clipboard.text(),
            "magnet:?xt=urn:btih:111\nmagnet:?xt=urn:btih:222",
        )
        info.assert_called_once()

    def test_export_selected_magnets_multi_selection_writes_expected_file(
        self
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "batch_magnets.txt"
            with (
                mock.patch(
                    "gui.QtWidgets.QFileDialog.getSaveFileName",
                    return_value=(str(output), "Text Files (*.txt)"),
                ),
                mock.patch("gui.QtWidgets.QMessageBox.information") as info,
            ):
                self.window._export_selected_magnets()

            self.assertTrue(output.exists())
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "\n".join([
                    "# ABF-001 | Title A",
                    "magnet:?xt=urn:btih:111",
                    "",
                    "# ABS-002 | Title B",
                    "magnet:?xt=urn:btih:222",
                ]),
            )
            info.assert_called_once()

    def test_export_selected_magnets_no_selection_shows_prompt_and_no_file(
        self
    ) -> None:
        self._select_rows([])
        with (
            mock.patch("gui.QtWidgets.QFileDialog.getSaveFileName") as chooser,
            mock.patch("gui.QtWidgets.QMessageBox.information") as info,
        ):
            self.window._export_selected_magnets()

        chooser.assert_not_called()
        self.assertTrue(info.called)
        self.assertIn("请先选择作品。", str(info.call_args))

    def test_export_selected_magnets_no_magnets_shows_prompt_without_dialog(
        self
    ) -> None:
        self.window._magnets_cache = {
            self.actor_name: {
                "ABF-001": [],
                "ABS-002": []
            }
        }
        self._select_rows([0, 1])
        with (
            mock.patch("gui.QtWidgets.QFileDialog.getSaveFileName") as chooser,
            mock.patch("gui.QtWidgets.QMessageBox.information") as info,
        ):
            self.window._export_selected_magnets()

        chooser.assert_not_called()
        self.assertTrue(info.called)
        self.assertIn("所选作品无可导出磁链。", str(info.call_args))

    def test_export_selected_magnets_single_selection_keeps_legacy_format(
        self
    ) -> None:
        self._select_rows([0])
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ABF-001.txt"
            with (
                mock.patch(
                    "gui.QtWidgets.QFileDialog.getSaveFileName",
                    return_value=(str(output), "Text Files (*.txt)"),
                ),
                mock.patch("gui.QtWidgets.QMessageBox.information"),
            ):
                self.window._export_selected_magnets()

            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "magnet:?xt=urn:btih:111",
            )

    def test_collect_scope_combo_only_has_actor_option(self) -> None:
        self.assertEqual(self.window.collect_scope_combo.count(), 1)
        self.assertEqual(self.window.collect_scope_combo.itemData(0), "actor")
        self.assertEqual(self.window.collect_scope_combo.findData("series"), -1)

    def test_dashboard_does_not_expose_runtime_browser_controls(self) -> None:
        self.assertFalse(hasattr(self.window, "cookie_input"))
        self.assertFalse(hasattr(self.window, "db_input"))
        self.assertFalse(hasattr(self.window, "output_input"))
        self.assertFalse(hasattr(self.window, "fetch_mode_combo"))
        self.assertFalse(hasattr(self.window, "browser_profile_input"))
        self.assertFalse(hasattr(self.window, "browser_timeout_spin"))
        self.assertFalse(hasattr(self.window, "challenge_timeout_spin"))
        self.assertFalse(hasattr(self.window, "browser_headless_cb"))

    def test_data_toolbar_moves_actions_to_next_row_and_widens_search_mode(
        self
    ) -> None:
        self.assertGreaterEqual(
            self.window.search_mode_combo.minimumWidth(), 130
        )
        self.assertTrue(hasattr(self.window, "toolbar_row_filters"))
        self.assertTrue(hasattr(self.window, "toolbar_row_actions"))

        def _widgets_in(layout: QtWidgets.QLayout) -> list[QtWidgets.QWidget]:
            widgets: list[QtWidgets.QWidget] = []
            for i in range(layout.count()):
                item = layout.itemAt(i)
                widget = item.widget()
                if widget is not None:
                    widgets.append(widget)
            return widgets

        filter_widgets = _widgets_in(self.window.toolbar_row_filters)
        action_widgets = _widgets_in(self.window.toolbar_row_actions)

        self.assertIn(self.window.subtitle_filter_combo, filter_widgets)
        self.assertNotIn(self.window.refresh_data_btn, filter_widgets)

        self.assertIn(self.window.refresh_data_btn, action_widgets)
        self.assertIn(self.window.open_link_btn, action_widgets)
        self.assertIn(self.window.export_btn, action_widgets)
        self.assertIn(self.window.works_edit_cb, action_widgets)
        self.assertIn(self.window.save_works_btn, action_widgets)
        self.assertIn(self.window.result_count_label, action_widgets)

    def test_data_toolbar_filter_combo_widths_are_sufficient(self) -> None:
        self.assertGreaterEqual(
            self.window.actor_sort_combo.minimumWidth(), 170
        )
        self.assertGreaterEqual(
            self.window.works_sort_combo.minimumWidth(), 140
        )
        self.assertGreaterEqual(
            self.window.magnet_filter_combo.minimumWidth(), 170
        )
        self.assertGreaterEqual(
            self.window.code_filter_combo.minimumWidth(), 220
        )
        self.assertGreaterEqual(
            self.window.subtitle_filter_combo.minimumWidth(), 170
        )

        def _widgets_in(layout: QtWidgets.QLayout) -> list[QtWidgets.QWidget]:
            widgets: list[QtWidgets.QWidget] = []
            for i in range(layout.count()):
                item = layout.itemAt(i)
                widget = item.widget()
                if widget is not None:
                    widgets.append(widget)
            return widgets

        filter_widgets = _widgets_in(self.window.toolbar_row_filters)
        action_widgets = _widgets_in(self.window.toolbar_row_actions)
        self.assertNotIn(self.window.refresh_data_btn, filter_widgets)
        self.assertIn(self.window.refresh_data_btn, action_widgets)

    def test_works_and_magnets_tables_use_cell_selection_and_no_context_menu(
        self
    ) -> None:
        self.assertEqual(
            self.window.works_table.selectionBehavior(),
            QtWidgets.QAbstractItemView.SelectItems,
        )
        self.assertEqual(
            self.window.magnets_table.selectionBehavior(),
            QtWidgets.QAbstractItemView.SelectItems,
        )
        self.assertEqual(
            self.window.works_table.selectionMode(),
            QtWidgets.QAbstractItemView.ExtendedSelection,
        )
        self.assertEqual(
            self.window.magnets_table.selectionMode(),
            QtWidgets.QAbstractItemView.ExtendedSelection,
        )
        self.assertEqual(
            self.window.works_table.contextMenuPolicy(),
            QtCore.Qt.NoContextMenu,
        )
        self.assertTrue(self.window.works_table.hasMouseTracking())
        self.assertTrue(self.window.magnets_table.hasMouseTracking())

    def test_works_and_magnets_tables_selected_style_is_high_contrast(
        self
    ) -> None:
        for table in (self.window.works_table, self.window.magnets_table):
            with self.subTest(
                table=table.objectName() or table.__class__.__name__
            ):
                style = table.styleSheet()
                self.assertIn("QTableWidget::item:selected", style)
                self.assertIn("#1D4ED8", style)
                self.assertIn("#1E40AF", style)
                self.assertIn("#FFFFFF", style)

    def test_copy_shortcut_copies_selected_cells_for_works_and_magnets(
        self
    ) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.clear()

        self.window.works_table.clearSelection()
        self.window.works_table.setCurrentCell(0, 1)
        self._press_copy(self.window.works_table)
        self.assertEqual(clipboard.text(), "Title A")

        self.window._populate_magnets_table([{
            "magnet": "magnet:?xt=urn:btih:111",
            "tags": "HD",
            "size": "1.2GB"
        }])
        self.window.magnets_table.clearSelection()
        self.window.magnets_table.setCurrentCell(0, 0)
        self._press_copy(self.window.magnets_table)
        self.assertEqual(clipboard.text(), "magnet:?xt=urn:btih:111")

    def test_copy_shortcut_copies_selected_actor_name(self) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.clear()
        self.window.actor_list.setCurrentRow(0)
        self._press_copy(self.window.actor_list)
        self.assertEqual(clipboard.text(), self.actor_name)

    def test_copy_shortcut_skips_placeholder_actor_item(self) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText("original")
        self.window.actor_list.clear()
        self.window.actor_list.addItem("暂无演员数据。")
        self.window.actor_list.setCurrentRow(0)
        self._press_copy(self.window.actor_list)
        self.assertEqual(clipboard.text(), "original")

    def test_settings_page_has_browse_buttons_for_all_path_fields(self) -> None:
        self.assertTrue(hasattr(self.window, "default_cookie_btn"))
        self.assertTrue(hasattr(self.window, "default_db_btn"))
        self.assertTrue(hasattr(self.window, "default_output_btn"))
        self.assertTrue(hasattr(self.window, "config_file_combo"))
        self.assertTrue(hasattr(self.window, "config_switch_btn"))
        self.assertTrue(hasattr(self.window, "config_save_as_btn"))
        self.assertEqual(self.window.config_switch_btn.text(), "保存")

    def test_browser_timeout_row_contains_challenge_timeout_inline(
        self
    ) -> None:
        labels: list[str] = []
        browser_timeout_layout = None
        for row in range(self.window.settings_form.rowCount()):
            label_item = self.window.settings_form.itemAt(
                row, QtWidgets.QFormLayout.LabelRole
            )
            field_item = self.window.settings_form.itemAt(
                row, QtWidgets.QFormLayout.FieldRole
            )
            if not label_item or not field_item:
                continue
            label_widget = label_item.widget()
            if not label_widget:
                continue
            label_text = label_widget.text()
            labels.append(label_text)
            if label_text == "浏览器超时 (s)":
                browser_timeout_layout = field_item.layout()

        self.assertIn("浏览器超时 (s)", labels)
        self.assertNotIn("验证等待 (s)", labels)
        self.assertIsNotNone(browser_timeout_layout)
        assert browser_timeout_layout is not None

        row_widgets = []
        for i in range(browser_timeout_layout.count()):
            item = browser_timeout_layout.itemAt(i)
            widget = item.widget()
            if widget is not None:
                row_widgets.append(widget)

        self.assertIn(self.window.default_browser_timeout_spin, row_widgets)
        self.assertIn(self.window.default_challenge_timeout_spin, row_widgets)
        self.assertLessEqual(
            self.window.default_browser_timeout_spin.maximumWidth(), 150
        )
        self.assertLessEqual(
            self.window.default_challenge_timeout_spin.maximumWidth(), 150
        )

    def test_config_file_row_is_last_and_no_save_defaults_button(self) -> None:
        labels: list[str] = []
        config_row_layout = None
        for row in range(self.window.settings_form.rowCount()):
            label_item = self.window.settings_form.itemAt(
                row, QtWidgets.QFormLayout.LabelRole
            )
            field_item = self.window.settings_form.itemAt(
                row, QtWidgets.QFormLayout.FieldRole
            )
            if not label_item or not field_item:
                continue
            label_widget = label_item.widget()
            if not label_widget:
                continue
            label_text = label_widget.text()
            labels.append(label_text)
            if label_text == "配置文件":
                config_row_layout = field_item.layout()

        self.assertTrue(labels)
        self.assertEqual(labels[-1], "配置文件")
        self.assertIsNotNone(config_row_layout)
        assert config_row_layout is not None

        row_widgets = []
        for i in range(config_row_layout.count()):
            item = config_row_layout.itemAt(i)
            widget = item.widget()
            if widget is not None:
                row_widgets.append(widget)

        self.assertIn(self.window.config_file_combo, row_widgets)
        self.assertIn(self.window.config_switch_btn, row_widgets)
        self.assertIn(self.window.config_save_as_btn, row_widgets)
        self.assertFalse(hasattr(self.window, "save_defaults_btn"))

    def test_save_config_as_writes_named_ini_and_switches_active_file(
        self
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            self.window._runtime_root_path = runtime_root
            self.window._active_config_file = runtime_root / "config.ini"
            self.window._refresh_config_file_options()

            with (
                mock.patch(
                    "gui.QtWidgets.QInputDialog.getText",
                    return_value=("my_profile", True)
                ),
                mock.patch.object(
                    self.window, "_save_ini_config", return_value=None
                ) as save_ini,
                mock.patch("gui.QtWidgets.QMessageBox.information"),
            ):
                self.window._save_config_as()

            expected = (runtime_root / "my_profile.ini").resolve(strict=False)
            save_ini.assert_called_once()
            saved_path = Path(save_ini.call_args.kwargs.get("config_file")
                             ).resolve(strict=False)
            self.assertEqual(saved_path, expected)
            self.assertEqual(
                self.window._active_config_file.resolve(strict=False), expected
            )
            current_data = self.window.config_file_combo.currentData()
            self.assertIsNotNone(current_data)
            self.assertEqual(
                Path(str(current_data)).resolve(strict=False), expected
            )

    def test_switch_selected_config_file_loads_target_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            config_a = runtime_root / "config.ini"
            config_b = runtime_root / "alt.ini"
            config_a.write_text("[paths]\n", encoding="utf-8")
            config_b.write_text("[paths]\n", encoding="utf-8")

            self.window._runtime_root_path = runtime_root
            self.window._active_config_file = config_a
            self.window._refresh_config_file_options()

            expected_target = config_b.resolve(strict=False)
            target_index = -1
            for i in range(self.window.config_file_combo.count()):
                item_data = self.window.config_file_combo.itemData(i)
                if item_data and Path(
                    str(item_data)
                ).resolve(strict=False) == expected_target:
                    target_index = i
                    break
            self.assertNotEqual(target_index, -1)

            with (
                mock.patch.object(
                    self.window, "_load_defaults", return_value=None
                ) as load_defaults,
                mock.patch.object(
                    self.window, "_ensure_default_db", return_value=None
                ) as ensure_db,
                mock.patch.object(
                    self.window, "_refresh_history", return_value=None
                ) as refresh_history,
                mock.patch.object(self.window, "_load_data", return_value=None)
                as load_data,
            ):
                self.window.config_file_combo.setCurrentIndex(target_index)

            self.assertEqual(
                self.window._active_config_file.resolve(strict=False),
                expected_target,
            )
            load_defaults.assert_called_once()
            ensure_db.assert_called_once()
            refresh_history.assert_called_once()
            load_data.assert_called_once()

    def test_config_save_button_saves_current_profile(self) -> None:
        with (
            mock.patch.object(
                self.window, "_save_ini_config", return_value=None
            ) as save_ini,
            mock.patch.object(
                self.window, "_ensure_default_db", return_value=None
            ),
            mock.patch("gui.QtWidgets.QMessageBox.information"),
        ):
            self.window.config_switch_btn.click()

        save_ini.assert_called_once()

    def test_restore_active_config_file_falls_back_to_default_when_missing(
        self
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            settings = self.window._flow_settings()
            settings.setValue("config/active_ini", "my_profile.ini")

            self.window._runtime_root_path = runtime_root
            self.window._restore_active_config_file()

            self.assertEqual(
                self.window._active_config_file.resolve(strict=False),
                (runtime_root / "config.ini").resolve(strict=False),
            )

    def test_start_flow_uses_settings_page_fetch_mode(self) -> None:
        httpx_index = self.window.default_fetch_mode_combo.findData("httpx")
        self.assertNotEqual(httpx_index, -1)
        self.window.default_fetch_mode_combo.setCurrentIndex(httpx_index)

        with (
            mock.patch.object(
                self.window, "_save_ini_config", return_value=None
            ),
            mock.patch("gui.load_cookie_dict", return_value={"cookie": "ok"}),
            mock.patch("gui.is_cookie_valid", return_value=True),
            mock.patch.object(
                QtCore.QThread, "start", new=lambda _thread: None
            ),
        ):
            self.window._start_flow()

        self.assertIsNotNone(self.window._worker)
        assert self.window._worker is not None
        self.assertEqual(self.window._worker.fetch_config.mode, "httpx")

    def test_settings_fetch_mode_combo_does_not_contain_smart_option(
        self
    ) -> None:
        smart_index = self.window.default_fetch_mode_combo.findData("smart")
        self.assertEqual(smart_index, -1)

    def test_start_flow_blocks_when_base_domain_segment_invalid(self) -> None:
        self.window.base_domain_segment_input.setText("!!!")
        with (
            mock.patch.object(
                self.window, "_save_ini_config", return_value=None
            ),
            mock.patch("gui.QtWidgets.QMessageBox.warning") as warning,
        ):
            self.window._start_flow()
        warning.assert_called_once()
        self.assertIsNone(self.window._worker)

    def test_history_list_compact_in_settings_page(self) -> None:
        self.assertLessEqual(self.window.history_list.maximumWidth(), 480)

    def test_history_box_is_right_and_left_area_is_wider(self) -> None:
        settings_layout = self.window.pages.widget(2).layout()
        self.assertGreater(
            settings_layout.stretch(0), settings_layout.stretch(1)
        )
        self.assertGreaterEqual(self.window.history_box.minimumWidth(), 360)
        self.assertLessEqual(self.window.history_box.maximumWidth(), 540)

    def test_default_settings_form_uses_stretched_two_column_layout(
        self
    ) -> None:
        self.assertEqual(
            self.window.settings_form.fieldGrowthPolicy(),
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow,
        )
        for widget in (
            self.window.default_cookie,
            self.window.default_db,
            self.window.default_output,
            self.window.default_browser_profile,
        ):
            with self.subTest(
                widget=widget.objectName() or widget.__class__.__name__
            ):
                self.assertEqual(
                    widget.sizePolicy().horizontalPolicy(),
                    QtWidgets.QSizePolicy.Expanding,
                )

    def test_start_flow_browser_mode_uses_actor_scope_without_crash(
        self
    ) -> None:
        with (
            mock.patch.object(
                self.window, "_save_ini_config", return_value=None
            ),
            mock.patch("gui.load_cookie_dict", return_value={"cookie": "ok"}),
            mock.patch("gui.is_cookie_valid", return_value=True),
            mock.patch.object(
                QtCore.QThread, "start", new=lambda _thread: None
            ),
        ):
            self.window._start_flow()

        self.assertIsNotNone(self.window._worker)
        assert self.window._worker is not None
        self.assertEqual(self.window._worker.collect_scope, "actor")

    def test_start_flow_browser_mode_blocks_when_cookie_load_fails(
        self
    ) -> None:
        browser_index = self.window.default_fetch_mode_combo.findData("browser")
        self.assertNotEqual(browser_index, -1)
        self.window.default_fetch_mode_combo.setCurrentIndex(browser_index)
        self.window._worker = None

        with (
            mock.patch.object(
                self.window, "_save_ini_config", return_value=None
            ),
            mock.patch(
                "app.gui.main_window.load_cookie_dict",
                side_effect=SystemExit("Cookie 缺少关键字段或为空，退出。"),
            ),
            mock.patch("gui.QtWidgets.QMessageBox.warning") as warning,
            mock.patch.object(
                QtCore.QThread, "start", new=lambda _thread: None
            ),
        ):
            self.window._start_flow()

        warning.assert_called_once()
        self.assertIsNone(self.window._worker)

    def test_start_flow_browser_mode_blocks_when_cookie_invalid(self) -> None:
        browser_index = self.window.default_fetch_mode_combo.findData("browser")
        self.assertNotEqual(browser_index, -1)
        self.window.default_fetch_mode_combo.setCurrentIndex(browser_index)
        self.window._worker = None

        with (
            mock.patch.object(
                self.window, "_save_ini_config", return_value=None
            ),
            mock.patch(
                "app.gui.main_window.load_cookie_dict",
                return_value={"cookie": "ok"},
            ),
            mock.patch(
                "app.gui.main_window.is_cookie_valid", return_value=False
            ),
            mock.patch("gui.QtWidgets.QMessageBox.warning") as warning,
            mock.patch.object(
                QtCore.QThread, "start", new=lambda _thread: None
            ),
        ):
            self.window._start_flow()

        warning.assert_called_once()
        self.assertIsNone(self.window._worker)

    def test_start_flow_code_filter_does_not_show_confirmation_dialog(
        self
    ) -> None:
        code_index = self.window.filter_mode_combo.findData("code")
        self.assertNotEqual(code_index, -1)
        self.window.filter_mode_combo.setCurrentIndex(code_index)
        self.window.filter_values_input.setText("ABF")

        with (
            mock.patch.object(
                self.window, "_save_ini_config", return_value=None
            ),
            mock.patch("gui.load_cookie_dict", return_value={"cookie": "ok"}),
            mock.patch("gui.is_cookie_valid", return_value=True),
            mock.patch("gui.QtWidgets.QMessageBox.question") as ask,
            mock.patch.object(
                QtCore.QThread, "start", new=lambda _thread: None
            ),
        ):
            self.window._start_flow()

        ask.assert_not_called()
        self.assertIsNotNone(self.window._worker)

    def test_start_flow_series_filter_does_not_show_confirmation_dialog(
        self
    ) -> None:
        series_filter_index = self.window.filter_mode_combo.findData("series")
        self.assertNotEqual(series_filter_index, -1)
        self.window.filter_mode_combo.setCurrentIndex(series_filter_index)
        self.window.filter_values_input.setText("IP")

        with (
            mock.patch.object(
                self.window, "_save_ini_config", return_value=None
            ),
            mock.patch("gui.load_cookie_dict", return_value={"cookie": "ok"}),
            mock.patch("gui.is_cookie_valid", return_value=True),
            mock.patch("gui.QtWidgets.QMessageBox.question") as ask,
            mock.patch.object(
                QtCore.QThread, "start", new=lambda _thread: None
            ),
        ):
            self.window._start_flow()

        ask.assert_not_called()
        self.assertIsNotNone(self.window._worker)


if __name__ == "__main__":
    unittest.main()
