from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from time import perf_counter

from PyQt5 import QtCore, QtGui, QtWidgets

import mdcx_magnets
from config import LOGGER
from get_actor_works import run_actor_works
from get_collect_actors import run_collect_actors
from get_works_magnet import run_magnet_jobs
from storage import Storage
from utils import (
    CancelledError,
    is_cookie_valid,
    load_cookie_dict,
    load_recent_history,
    parse_cookie_string,
    set_cancel_checker,
)


class LogEmitter(QtCore.QObject):
    message = QtCore.pyqtSignal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, emitter: LogEmitter) -> None:
        super().__init__()
        self.emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        try:
            self.emitter.message.emit(msg)
        except RuntimeError:
            pass


class FlowWorker(QtCore.QObject):
    started = QtCore.pyqtSignal()
    stage_changed = QtCore.pyqtSignal(str, int, int)
    finished = QtCore.pyqtSignal(float)
    canceled = QtCore.pyqtSignal(float)
    error = QtCore.pyqtSignal(str)

    def __init__(
        self,
        *,
        db_path: str,
        output_dir: str,
        cookie_path: str,
        tags: str,
        actor_filter: str,
        run_collect: bool,
        run_works: bool,
        run_magnets: bool,
        run_filter: bool,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.output_dir = output_dir
        self.cookie_path = cookie_path
        self.tags = tags
        self.actor_filter = actor_filter
        self.run_collect = run_collect
        self.run_works = run_works
        self.run_magnets = run_magnets
        self.run_filter = run_filter
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def _run_stage(self, index: int, total: int, label: str, func, *args, **kwargs) -> None:
        self.stage_changed.emit(label, index, total)
        func(*args, **kwargs)

    @QtCore.pyqtSlot()
    def run(self) -> None:
        self.started.emit()
        start = perf_counter()
        set_cancel_checker(
            lambda: self._cancel_requested
            or bool(QtCore.QThread.currentThread().isInterruptionRequested())
        )
        try:
            stages = []
            if self.run_collect:
                stages.append(("抓取收藏演员", run_collect_actors))
            if self.run_works:
                stages.append(("抓取作品列表", run_actor_works))
            if self.run_magnets:
                stages.append(("抓取磁链", run_magnet_jobs))
            if self.run_filter:
                stages.append(("磁链筛选", mdcx_magnets.run))

            total = len(stages) or 1
            for idx, (label, func) in enumerate(stages, start=1):
                if self._cancel_requested:
                    elapsed = perf_counter() - start
                    self.canceled.emit(elapsed)
                    return
                if func is run_collect_actors:
                    self._run_stage(
                        idx,
                        total,
                        label,
                        func,
                        cookie_json=self.cookie_path,
                        db_path=self.db_path,
                    )
                elif func is run_actor_works:
                    self._run_stage(
                        idx,
                        total,
                        label,
                        func,
                        db_path=self.db_path,
                        tags=self.tags,
                        cookie_json=self.cookie_path,
                        actor_name=self.actor_filter or None,
                    )
                elif func is run_magnet_jobs:
                    self._run_stage(
                        idx,
                        total,
                        label,
                        func,
                        out_root=self.output_dir,
                        cookie_json=self.cookie_path,
                        db_path=self.db_path,
                        actor_name=self.actor_filter or None,
                    )
                else:
                    self._run_stage(
                        idx,
                        total,
                        label,
                        func,
                        db_path=self.db_path,
                        output_root=self.output_dir,
                    )
        except CancelledError:
            elapsed = perf_counter() - start
            self.canceled.emit(elapsed)
            return
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        finally:
            set_cancel_checker(None)

        elapsed = perf_counter() - start
        self.finished.emit(elapsed)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("crawljav GUI")
        self.resize(920, 680)

        self._thread: QtCore.QThread | None = None
        self._worker: FlowWorker | None = None
        self._actors_cache: list[str] = []
        self._works_cache: dict[str, list[dict]] = {}
        self._magnets_cache: dict[str, dict[str, list[dict]]] = {}

        self._log_emitter = LogEmitter()
        self._log_handler = QtLogHandler(self._log_emitter)
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        LOGGER.addHandler(self._log_handler)

        self._build_ui()
        self._apply_styles()
        self._log_emitter.message.connect(self._append_log)
        self._load_flow_settings()
        self._load_defaults()

    def _build_ui(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        layout = QtWidgets.QHBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        self.nav_list = QtWidgets.QListWidget()
        self.nav_list.setObjectName("navList")
        self.nav_list.addItems(["控制台", "数据浏览", "设置"])
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        self.nav_list.setFixedWidth(180)
        layout.addWidget(self.nav_list)

        self.pages = QtWidgets.QStackedWidget()
        layout.addWidget(self.pages, stretch=1)

        dashboard_page = QtWidgets.QWidget()
        dashboard_layout = QtWidgets.QVBoxLayout(dashboard_page)
        dashboard_layout.setContentsMargins(0, 0, 0, 0)
        dashboard_layout.setSpacing(12)

        config_box = QtWidgets.QGroupBox("运行配置")
        config_layout = QtWidgets.QGridLayout(config_box)
        config_layout.setContentsMargins(12, 12, 12, 12)
        config_layout.setHorizontalSpacing(10)
        config_layout.setVerticalSpacing(8)

        self.cookie_input = QtWidgets.QLineEdit("cookie.json")
        self.db_input = QtWidgets.QLineEdit("userdata/actors.db")
        self.output_input = QtWidgets.QLineEdit("userdata/magnets")
        self.tags_input = QtWidgets.QLineEdit()
        self.actor_input = QtWidgets.QLineEdit()

        cookie_btn = QtWidgets.QPushButton("浏览")
        db_btn = QtWidgets.QPushButton("浏览")
        output_btn = QtWidgets.QPushButton("浏览")
        cookie_btn.setObjectName("ghostButton")
        db_btn.setObjectName("ghostButton")
        output_btn.setObjectName("ghostButton")

        cookie_btn.clicked.connect(self._pick_cookie)
        db_btn.clicked.connect(self._pick_db)
        output_btn.clicked.connect(self._pick_output)

        config_layout.addWidget(QtWidgets.QLabel("Cookie"), 0, 0)
        config_layout.addWidget(self.cookie_input, 0, 1)
        config_layout.addWidget(cookie_btn, 0, 2)

        config_layout.addWidget(QtWidgets.QLabel("数据库"), 1, 0)
        config_layout.addWidget(self.db_input, 1, 1)
        config_layout.addWidget(db_btn, 1, 2)

        config_layout.addWidget(QtWidgets.QLabel("输出目录"), 2, 0)
        config_layout.addWidget(self.output_input, 2, 1)
        config_layout.addWidget(output_btn, 2, 2)

        config_layout.addWidget(QtWidgets.QLabel("标签"), 3, 0)
        config_layout.addWidget(self.tags_input, 3, 1, 1, 2)

        config_layout.addWidget(QtWidgets.QLabel("演员筛选"), 4, 0)
        config_layout.addWidget(self.actor_input, 4, 1, 1, 2)

        dashboard_layout.addWidget(config_box)

        flow_box = QtWidgets.QGroupBox("流程")
        flow_layout = QtWidgets.QHBoxLayout(flow_box)
        flow_layout.setContentsMargins(12, 12, 12, 12)
        flow_layout.setSpacing(10)

        self.collect_cb = QtWidgets.QCheckBox("收藏演员")
        self.works_cb = QtWidgets.QCheckBox("作品列表")
        self.magnets_cb = QtWidgets.QCheckBox("磁链抓取")
        self.filter_cb = QtWidgets.QCheckBox("磁链筛选")
        for cb in (self.collect_cb, self.works_cb, self.magnets_cb, self.filter_cb):
            cb.stateChanged.connect(self._save_flow_settings)

        flow_layout.addWidget(self.collect_cb)
        flow_layout.addWidget(self.works_cb)
        flow_layout.addWidget(self.magnets_cb)
        flow_layout.addWidget(self.filter_cb)

        flow_layout.addStretch(1)
        self.start_btn = QtWidgets.QPushButton("开始")
        self.stop_btn = QtWidgets.QPushButton("停止")
        self.start_btn.setObjectName("primaryButton")
        self.stop_btn.setObjectName("dangerButton")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start_flow)
        self.stop_btn.clicked.connect(self._stop_flow)
        flow_layout.addWidget(self.start_btn)
        flow_layout.addWidget(self.stop_btn)

        dashboard_layout.addWidget(flow_box)

        status_box = QtWidgets.QGroupBox("状态")
        status_layout = QtWidgets.QVBoxLayout(status_box)
        status_layout.setContentsMargins(12, 12, 12, 12)
        status_layout.setSpacing(8)

        self.status_label = QtWidgets.QLabel("空闲")
        self.summary_label = QtWidgets.QLabel("最近运行: -")
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.summary_label)

        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        mono_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.log_view.setFont(mono_font)
        self.log_view.setMaximumBlockCount(800)
        status_layout.addWidget(self.log_view)

        dashboard_layout.addWidget(status_box, stretch=1)

        bottom = QtWidgets.QHBoxLayout()
        self.open_output_btn = QtWidgets.QPushButton("打开输出目录")
        self.open_db_btn = QtWidgets.QPushButton("打开数据库")
        self.open_output_btn.setObjectName("ghostButton")
        self.open_db_btn.setObjectName("ghostButton")
        self.open_output_btn.clicked.connect(self._open_output_dir)
        self.open_db_btn.clicked.connect(self._open_db_file)
        bottom.addWidget(self.open_output_btn)
        bottom.addWidget(self.open_db_btn)
        bottom.addStretch(1)
        dashboard_layout.addLayout(bottom)

        self.pages.addWidget(dashboard_page)

        data_page = QtWidgets.QWidget()
        data_outer = QtWidgets.QVBoxLayout(data_page)
        data_outer.setContentsMargins(0, 0, 0, 0)
        data_outer.setSpacing(8)

        data_toolbar = QtWidgets.QHBoxLayout()
        self.refresh_data_btn = QtWidgets.QPushButton("刷新")
        self.open_link_btn = QtWidgets.QPushButton("打开链接")
        self.export_btn = QtWidgets.QPushButton("导出选中")
        self.refresh_data_btn.setObjectName("ghostButton")
        self.open_link_btn.setObjectName("ghostButton")
        self.export_btn.setObjectName("ghostButton")
        self.refresh_data_btn.clicked.connect(self._load_data)
        self.open_link_btn.clicked.connect(self._open_selected_work_link)
        self.export_btn.clicked.connect(self._export_selected_magnets)
        data_toolbar.addWidget(self.refresh_data_btn)
        data_toolbar.addWidget(self.open_link_btn)
        data_toolbar.addWidget(self.export_btn)
        data_toolbar.addStretch(1)
        data_outer.addLayout(data_toolbar)

        data_layout = QtWidgets.QHBoxLayout()
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(12)

        actor_box = QtWidgets.QGroupBox("演员")
        actor_layout = QtWidgets.QVBoxLayout(actor_box)
        actor_layout.setContentsMargins(12, 12, 12, 12)
        actor_layout.setSpacing(8)
        self.actor_search = QtWidgets.QLineEdit()
        self.actor_search.setPlaceholderText("搜索演员")
        self.actor_search.textChanged.connect(self._filter_actors)
        self.actor_list = QtWidgets.QListWidget()
        self.actor_list.itemSelectionChanged.connect(self._on_actor_selected)
        actor_layout.addWidget(self.actor_search)
        actor_layout.addWidget(self.actor_list, stretch=1)

        works_box = QtWidgets.QGroupBox("作品")
        works_layout = QtWidgets.QVBoxLayout(works_box)
        works_layout.setContentsMargins(12, 12, 12, 12)
        works_layout.setSpacing(8)
        self.works_table = QtWidgets.QTableWidget(0, 3)
        self.works_table.setHorizontalHeaderLabels(["番号", "标题", "链接"])
        self.works_table.horizontalHeader().setStretchLastSection(True)
        self.works_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.works_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.works_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.works_table.itemSelectionChanged.connect(self._on_work_selected)
        works_layout.addWidget(self.works_table)

        magnets_box = QtWidgets.QGroupBox("磁链")
        magnets_layout = QtWidgets.QVBoxLayout(magnets_box)
        magnets_layout.setContentsMargins(12, 12, 12, 12)
        magnets_layout.setSpacing(8)
        self.magnets_table = QtWidgets.QTableWidget(0, 3)
        self.magnets_table.setHorizontalHeaderLabels(["Magnet", "标签", "大小"])
        self.magnets_table.horizontalHeader().setStretchLastSection(True)
        self.magnets_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.magnets_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.magnets_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        magnets_layout.addWidget(self.magnets_table)

        right_stack = QtWidgets.QVBoxLayout()
        right_stack.addWidget(works_box, stretch=2)
        right_stack.addWidget(magnets_box, stretch=1)

        data_layout.addWidget(actor_box, stretch=1)
        data_layout.addLayout(right_stack, stretch=3)
        data_outer.addLayout(data_layout, stretch=1)

        self.pages.addWidget(data_page)

        settings_page = QtWidgets.QWidget()
        settings_layout = QtWidgets.QHBoxLayout(settings_page)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(12)

        settings_box = QtWidgets.QGroupBox("默认设置")
        settings_form = QtWidgets.QFormLayout(settings_box)
        settings_form.setContentsMargins(12, 12, 12, 12)
        settings_form.setHorizontalSpacing(10)
        settings_form.setVerticalSpacing(8)
        self.default_cookie = QtWidgets.QLineEdit("cookie.json")
        self.default_db = QtWidgets.QLineEdit("userdata/actors.db")
        self.default_output = QtWidgets.QLineEdit("userdata/magnets")
        self.delay_range = QtWidgets.QLineEdit("0.8-1.6")
        settings_form.addRow("Cookie", self.default_cookie)
        settings_form.addRow("数据库", self.default_db)
        settings_form.addRow("输出目录", self.default_output)
        settings_form.addRow("延时范围 (s)", self.delay_range)
        self.save_defaults_btn = QtWidgets.QPushButton("保存默认设置")
        self.save_defaults_btn.setObjectName("ghostButton")
        self.save_defaults_btn.clicked.connect(self._save_defaults)
        settings_form.addRow("", self.save_defaults_btn)

        history_box = QtWidgets.QGroupBox("历史记录")
        history_layout = QtWidgets.QVBoxLayout(history_box)
        history_layout.setContentsMargins(12, 12, 12, 12)
        history_layout.setSpacing(8)
        self.history_list = QtWidgets.QListWidget()
        history_layout.addWidget(self.history_list)

        cookie_box = QtWidgets.QGroupBox("Cookie 校验")
        cookie_layout = QtWidgets.QVBoxLayout(cookie_box)
        cookie_layout.setContentsMargins(12, 12, 12, 12)
        cookie_layout.setSpacing(8)
        self.cookie_input_text = QtWidgets.QPlainTextEdit()
        self.cookie_input_text.setPlaceholderText("粘贴 cookie 字符串或 JSON")
        cookie_action = QtWidgets.QHBoxLayout()
        self.cookie_check_btn = QtWidgets.QPushButton("校验并保存")
        self.cookie_check_btn.setObjectName("primaryButton")
        self.cookie_check_btn.clicked.connect(self._validate_and_save_cookie)
        self.cookie_status = QtWidgets.QLabel("")
        cookie_action.addWidget(self.cookie_check_btn)
        cookie_action.addWidget(self.cookie_status, stretch=1)
        cookie_layout.addWidget(self.cookie_input_text)
        cookie_layout.addLayout(cookie_action)

        left_stack = QtWidgets.QVBoxLayout()
        left_stack.addWidget(settings_box)
        left_stack.addWidget(cookie_box, stretch=1)

        settings_layout.addLayout(left_stack, stretch=1)
        settings_layout.addWidget(history_box, stretch=2)

        self.pages.addWidget(settings_page)
        self._refresh_history()
        self._load_data()

    def _pick_cookie(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 cookie.json", str(Path.cwd()), "JSON Files (*.json)"
        )
        if path:
            self.cookie_input.setText(path)

    def _pick_db(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择数据库", str(Path.cwd()), "SQLite DB (*.db *.sqlite)"
        )
        if path:
            self.db_input.setText(path)

    def _pick_output(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择输出目录", str(Path.cwd())
        )
        if path:
            self.output_input.setText(path)

    def _open_output_dir(self) -> None:
        path = Path(self.output_input.text()).expanduser()
        if path.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _open_db_file(self) -> None:
        path = Path(self.db_input.text()).expanduser()
        if path.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def _on_nav_changed(self, index: int) -> None:
        self.pages.setCurrentIndex(index)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #F4F6F8;
                color: #1F2A37;
                font-size: 13px;
            }
            QLabel {
                background: transparent;
            }
            QCheckBox {
                background: transparent;
            }
            QGroupBox {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 10px;
                margin-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                top: 4px;
                padding: 0 6px;
                color: #1F2A37;
                font-weight: 600;
            }
            QLineEdit, QPlainTextEdit, QTableWidget, QListWidget {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                padding: 6px;
            }
            QPlainTextEdit {
                background: #F8FAFC;
            }
            QPushButton {
                background: #2D6CDF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:disabled {
                background: #CBD5F5;
                color: #5B6B8A;
            }
            QPushButton#ghostButton {
                background: #FFFFFF;
                color: #2D6CDF;
                border: 1px solid #D5DCE6;
            }
            QPushButton#dangerButton {
                background: #E4572E;
            }
            QListWidget#navList {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 10px;
                padding: 6px;
            }
            QListWidget#navList::item {
                padding: 10px 12px;
                margin: 4px 0;
                border-radius: 6px;
            }
            QListWidget#navList::item:selected {
                background: #2D6CDF;
                color: white;
            }
            """
        )

    def _flow_settings(self) -> QtCore.QSettings:
        return QtCore.QSettings("crawljav", "gui")

    def _save_flow_settings(self) -> None:
        settings = self._flow_settings()
        settings.setValue("flow/collect", self.collect_cb.isChecked())
        settings.setValue("flow/works", self.works_cb.isChecked())
        settings.setValue("flow/magnets", self.magnets_cb.isChecked())
        settings.setValue("flow/filter", self.filter_cb.isChecked())

    def _load_flow_settings(self) -> None:
        settings = self._flow_settings()
        self.collect_cb.setChecked(settings.value("flow/collect", True, type=bool))
        self.works_cb.setChecked(settings.value("flow/works", True, type=bool))
        self.magnets_cb.setChecked(settings.value("flow/magnets", True, type=bool))
        self.filter_cb.setChecked(settings.value("flow/filter", True, type=bool))

    def _load_defaults(self) -> None:
        settings = self._flow_settings()
        cookie = settings.value("defaults/cookie", "cookie.json")
        db_path = settings.value("defaults/db", "userdata/actors.db")
        output_dir = settings.value("defaults/output", "userdata/magnets")
        delay = settings.value("defaults/delay", "0.8-1.6")
        self.default_cookie.setText(str(cookie))
        self.default_db.setText(str(db_path))
        self.default_output.setText(str(output_dir))
        self.delay_range.setText(str(delay))
        self.cookie_input.setText(str(cookie))
        self.db_input.setText(str(db_path))
        self.output_input.setText(str(output_dir))

    def _save_defaults(self) -> None:
        settings = self._flow_settings()
        cookie = self.default_cookie.text().strip() or "cookie.json"
        db_path = self.default_db.text().strip() or "userdata/actors.db"
        output_dir = self.default_output.text().strip() or "userdata/magnets"
        delay = self.delay_range.text().strip() or "0.8-1.6"
        settings.setValue("defaults/cookie", cookie)
        settings.setValue("defaults/db", db_path)
        settings.setValue("defaults/output", output_dir)
        settings.setValue("defaults/delay", delay)
        self.cookie_input.setText(cookie)
        self.db_input.setText(db_path)
        self.output_input.setText(output_dir)
        QtWidgets.QMessageBox.information(self, "完成", "默认设置已保存。")

    def _start_flow(self) -> None:
        if self._is_thread_running():
            return

        cookie_path = self.cookie_input.text().strip()
        if not cookie_path:
            QtWidgets.QMessageBox.warning(self, "缺少参数", "需要填写 Cookie 路径。")
            return
        try:
            cookies = load_cookie_dict(cookie_path)
        except SystemExit as exc:
            QtWidgets.QMessageBox.warning(self, "Cookie 错误", str(exc))
            return
        if not is_cookie_valid(cookies):
            QtWidgets.QMessageBox.warning(self, "Cookie 错误", "Cookie 看起来无效。")
            return

        self.log_view.clear()
        self.status_label.setText("启动中...")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self._thread = QtCore.QThread(self)
        self._worker = FlowWorker(
            db_path=self.db_input.text().strip(),
            output_dir=self.output_input.text().strip(),
            cookie_path=cookie_path,
            tags=self.tags_input.text().strip(),
            actor_filter=self.actor_input.text().strip(),
            run_collect=self.collect_cb.isChecked(),
            run_works=self.works_cb.isChecked(),
            run_magnets=self.magnets_cb.isChecked(),
            run_filter=self.filter_cb.isChecked(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.stage_changed.connect(self._on_stage_changed)
        self._worker.finished.connect(self._on_finished)
        self._worker.canceled.connect(self._on_canceled)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.canceled.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _stop_flow(self) -> None:
        if not self._worker:
            return
        self._worker.request_cancel()
        if self._thread:
            self._thread.requestInterruption()
        self.status_label.setText("已请求停止...")

    def _on_stage_changed(self, label: str, index: int, total: int) -> None:
        self.status_label.setText(f"{label} ({index}/{total})")

    def _on_finished(self, elapsed: float) -> None:
        self.status_label.setText(f"完成，用时 {elapsed:.1f}s")
        self._sync_summary()
        self._refresh_history()
        self._load_data()
        self._reset_controls()

    def _on_canceled(self, elapsed: float) -> None:
        self.status_label.setText(f"已停止，用时 {elapsed:.1f}s")
        self._reset_controls()

    def _on_error(self, message: str) -> None:
        self.status_label.setText("失败")
        QtWidgets.QMessageBox.critical(self, "错误", message)
        self._reset_controls()

    def _reset_controls(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _is_thread_running(self) -> bool:
        if not self._thread:
            return False
        try:
            return self._thread.isRunning()
        except RuntimeError:
            self._thread = None
            self._worker = None
            return False

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None

    def _sync_summary(self) -> None:
        summaries = []
        for event in ("collect_actors", "actor_works", "magnets"):
            records = load_recent_history(event=event, limit=1)
            if not records:
                continue
            record = records[-1]
            if event == "collect_actors":
                summaries.append(f"actors={record.get('actors', '-')}")
            elif event == "actor_works":
                summaries.append(f"works={record.get('works_total', '-')}")
            elif event == "magnets":
                summaries.append(f"magnets={record.get('magnets', '-')}")
        if summaries:
            self.summary_label.setText("最近运行: " + ", ".join(summaries))
        else:
            self.summary_label.setText("最近运行: -")

    def _refresh_history(self) -> None:
        if not hasattr(self, "history_list"):
            return
        self.history_list.clear()
        records = load_recent_history(limit=10)
        if not records:
            self.history_list.addItem("暂无历史记录。")
            return
        for record in records:
            event = record.get("event", "event")
            ts = record.get("ts", "")
            parts = [event, ts]
            for key in ("actors", "works_total", "works", "magnets"):
                if key in record:
                    parts.append(f"{key}={record.get(key)}")
            self.history_list.addItem(" | ".join(parts))

    def _validate_and_save_cookie(self) -> None:
        raw = self.cookie_input_text.toPlainText().strip()
        if not raw:
            QtWidgets.QMessageBox.information(self, "提示", "请粘贴 Cookie 内容。")
            return
        cookie_path = Path("cookie.json")
        cookies = None
        payload: dict | None = None
        try:
            if raw.startswith("{"):
                data = json.loads(raw)
                if isinstance(data, dict):
                    if isinstance(data.get("cookie"), str):
                        cookies = parse_cookie_string(data["cookie"])
                        payload = {"cookie": data["cookie"]}
                    else:
                        cookies = data
                        payload = data
            else:
                cookies = parse_cookie_string(raw)
                payload = {"cookie": raw}
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "格式错误", f"解析失败: {exc}")
            return

        if not cookies:
            QtWidgets.QMessageBox.warning(self, "格式错误", "无法解析出 Cookie。")
            return
        if not is_cookie_valid(cookies):
            QtWidgets.QMessageBox.warning(self, "校验失败", "Cookie 缺少关键字段。")
            return
        if payload is None:
            payload = {"cookie": raw}
        cookie_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.cookie_status.setText("已保存到 cookie.json")
        self.cookie_input.setText(str(cookie_path))
        self.default_cookie.setText(str(cookie_path))
        QtWidgets.QMessageBox.information(self, "完成", "Cookie 校验通过并已保存。")

    def _load_data(self) -> None:
        db_path = self.db_input.text().strip()
        path = Path(db_path)
        self._actors_cache = []
        self._works_cache = {}
        self._magnets_cache = {}
        self.actor_list.clear()
        self.works_table.setRowCount(0)
        self.magnets_table.setRowCount(0)
        if not path.exists():
            return
        try:
            with Storage(path) as store:
                actors = store.iter_actor_urls()
                self._actors_cache = [name for name, _ in actors]
                self._works_cache = store.get_all_actor_works()
                self._magnets_cache = store.get_magnets_grouped()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("读取数据库失败: %s", exc)
            return
        self._populate_actor_list(self._actors_cache)

    def _populate_actor_list(self, names: list[str]) -> None:
        self.actor_list.clear()
        if not names:
            self.actor_list.addItem("暂无演员数据。")
            return
        for name in names:
            self.actor_list.addItem(name)

    def _filter_actors(self) -> None:
        keyword = self.actor_search.text().strip().lower()
        if not keyword:
            self._populate_actor_list(self._actors_cache)
            return
        filtered = [name for name in self._actors_cache if keyword in name.lower()]
        self._populate_actor_list(filtered)

    def _on_actor_selected(self) -> None:
        items = self.actor_list.selectedItems()
        if not items:
            return
        actor_name = items[0].text()
        if actor_name in ("暂无演员数据。",):
            return
        works = self._works_cache.get(actor_name, [])
        self._populate_works_table(works)
        self.magnets_table.setRowCount(0)

    def _populate_works_table(self, works: list[dict]) -> None:
        self.works_table.setRowCount(0)
        if not works:
            return
        self.works_table.setRowCount(len(works))
        for row, work in enumerate(works):
            code = str(work.get("code", ""))
            title = str(work.get("title", ""))
            href = str(work.get("href", ""))
            self.works_table.setItem(row, 0, QtWidgets.QTableWidgetItem(code))
            self.works_table.setItem(row, 1, QtWidgets.QTableWidgetItem(title))
            self.works_table.setItem(row, 2, QtWidgets.QTableWidgetItem(href))
        self.works_table.resizeColumnsToContents()

    def _on_work_selected(self) -> None:
        items = self.actor_list.selectedItems()
        if not items:
            return
        actor_name = items[0].text()
        if actor_name not in self._magnets_cache:
            self.magnets_table.setRowCount(0)
            return
        selected = self.works_table.selectedItems()
        if not selected:
            return
        row = self.works_table.currentRow()
        if row < 0:
            return
        code_item = self.works_table.item(row, 0)
        if not code_item:
            return
        code = code_item.text()
        magnets = self._magnets_cache.get(actor_name, {}).get(code, [])
        self._populate_magnets_table(magnets)

    def _populate_magnets_table(self, magnets: list[dict]) -> None:
        self.magnets_table.setRowCount(0)
        if not magnets:
            return
        self.magnets_table.setRowCount(len(magnets))
        for row, magnet in enumerate(magnets):
            href = str(magnet.get("magnet", ""))
            tags = str(magnet.get("tags", ""))
            size = str(magnet.get("size", ""))
            self.magnets_table.setItem(row, 0, QtWidgets.QTableWidgetItem(href))
            self.magnets_table.setItem(row, 1, QtWidgets.QTableWidgetItem(tags))
            self.magnets_table.setItem(row, 2, QtWidgets.QTableWidgetItem(size))
        self.magnets_table.resizeColumnsToContents()

    def _open_selected_work_link(self) -> None:
        row = self.works_table.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(self, "提示", "请先选择作品。")
            return
        link_item = self.works_table.item(row, 2)
        if not link_item:
            return
        url = link_item.text().strip()
        if not url:
            QtWidgets.QMessageBox.information(self, "提示", "该作品没有链接。")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))

    def _export_selected_magnets(self) -> None:
        row = self.works_table.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.information(self, "提示", "请先选择作品。")
            return
        code_item = self.works_table.item(row, 0)
        if not code_item:
            return
        code = code_item.text().strip() or "magnets"
        items = self.actor_list.selectedItems()
        actor_name = items[0].text() if items else ""
        magnets = self._magnets_cache.get(actor_name, {}).get(code, [])
        if not magnets:
            QtWidgets.QMessageBox.information(self, "提示", "该作品没有磁链数据。")
            return
        default_name = f"{code}.txt"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出磁链", str(Path.cwd() / default_name), "Text Files (*.txt)"
        )
        if not path:
            return
        lines = []
        for item in magnets:
            magnet = str(item.get("magnet", "")).strip()
            if magnet:
                lines.append(magnet)
        if not lines:
            QtWidgets.QMessageBox.information(self, "提示", "无可导出的磁链。")
            return
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        QtWidgets.QMessageBox.information(self, "完成", f"已导出 {len(lines)} 条。")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        LOGGER.removeHandler(self._log_handler)
        super().closeEvent(event)


def main() -> int:
    if getattr(sys, "frozen", False):
        base_dir = Path.home() / ".crawljav"
        base_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(base_dir)
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
