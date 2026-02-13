from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from time import perf_counter
from typing import Literal

from PyQt5 import QtCore, QtGui, QtWidgets

import mdcx_magnets
import gui_data_view as gdv
from config import LOGGER
from fetch_runtime import FetchConfig
from get_actor_works import run_actor_works
from get_collect_actors import run_collect_actors
from get_collect_scope_magnets import run_collection_magnets
from get_collect_scope_works import run_collection_works
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

from gui_config import (
    DEFAULT_BROWSER_TIMEOUT_SECONDS,
    DEFAULT_BROWSER_USER_DATA_DIR,
    DEFAULT_CHALLENGE_TIMEOUT_SECONDS,
    DEFAULT_COLLECT_SCOPE,
    DEFAULT_COOKIE,
    DEFAULT_DB,
    DEFAULT_FETCH_MODE,
    DEFAULT_OUTPUT,
    load_ini_config,
    migrate_legacy_config_once,
    resolve_stored_path,
    save_ini_config,
    select_runtime_root,
)

_RUNTIME_ROOT, _RUNTIME_FALLBACK_USED = select_runtime_root(
    frozen=bool(getattr(sys, "frozen", False)),
    executable=sys.executable,
    cwd=Path.cwd(),
    home=Path.home(),
)
os.chdir(_RUNTIME_ROOT)




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
        filter_mode: Literal["actor", "code", "series"],
        filter_values: list[str],
        collect_scope: Literal["actor", "series", "maker", "director", "code"],
        fetch_mode: Literal["httpx", "browser"],
        browser_user_data_dir: str,
        browser_headless: bool,
        browser_timeout_seconds: int,
        challenge_timeout_seconds: int,
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
        self.filter_mode = filter_mode
        self.filter_values = filter_values
        self.collect_scope = collect_scope
        self.fetch_config = FetchConfig(
            mode=fetch_mode,
            browser_user_data_dir=browser_user_data_dir,
            browser_headless=browser_headless,
            browser_timeout_seconds=browser_timeout_seconds,
            challenge_timeout_seconds=challenge_timeout_seconds,
        )
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
            LOGGER.info(
                "当前筛选模式：%s，筛选值：%s",
                self.filter_mode,
                ",".join(self.filter_values) if self.filter_values else "(空)",
            )
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
                        collect_scope=self.collect_scope,
                        fetch_config=self.fetch_config,
                    )
                elif func is run_actor_works:
                    actor_filter = (
                        self.filter_values or None if self.filter_mode == "actor" else None
                    )
                    if self.collect_scope == "actor":
                        self._run_stage(
                            idx,
                            total,
                            label,
                            func,
                            db_path=self.db_path,
                            tags=self.tags,
                            cookie_json=self.cookie_path,
                            actor_name=actor_filter,
                            fetch_config=self.fetch_config,
                        )
                    else:
                        self._run_stage(
                            idx,
                            total,
                            label,
                            run_collection_works,
                            db_path=self.db_path,
                            cookie_json=self.cookie_path,
                            collect_scope=self.collect_scope,
                            collection_name=actor_filter,
                            fetch_config=self.fetch_config,
                        )
                elif func is run_magnet_jobs:
                    actor_filter = (
                        self.filter_values or None if self.filter_mode == "actor" else None
                    )
                    code_keywords = (
                        self.filter_values or None if self.filter_mode == "code" else None
                    )
                    series_prefixes = (
                        self.filter_values or None if self.filter_mode == "series" else None
                    )
                    if self.collect_scope == "actor":
                        self._run_stage(
                            idx,
                            total,
                            label,
                            func,
                            out_root=self.output_dir,
                            cookie_json=self.cookie_path,
                            db_path=self.db_path,
                            actor_name=actor_filter,
                            code_keywords=code_keywords,
                            series_prefixes=series_prefixes,
                            fetch_config=self.fetch_config,
                        )
                    else:
                        self._run_stage(
                            idx,
                            total,
                            label,
                            run_collection_magnets,
                            cookie_json=self.cookie_path,
                            db_path=self.db_path,
                            collect_scope=self.collect_scope,
                            collection_name=actor_filter,
                            code_keywords=code_keywords,
                            series_prefixes=series_prefixes,
                            fetch_config=self.fetch_config,
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
        self._all_view_rows: list[gdv.WorkViewRow] = []
        self._active_view_rows: list[gdv.WorkViewRow] = []
        self._current_actor_rows: list[gdv.WorkViewRow] = []
        self._runtime_root_path = _RUNTIME_ROOT
        self._runtime_fallback_used = _RUNTIME_FALLBACK_USED

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
        self._migrate_legacy_config_once()
        self._load_defaults()
        self._ensure_default_db()
        self._refresh_history()
        self._load_data()
        if self._runtime_fallback_used:
            QtCore.QTimer.singleShot(0, self._show_runtime_fallback_notice)

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
        self.filter_mode_combo = QtWidgets.QComboBox()
        self.filter_mode_combo.addItem("演员筛选", "actor")
        self.filter_mode_combo.addItem("番号筛选", "code")
        self.filter_mode_combo.addItem("系列筛选", "series")
        self.filter_values_input = QtWidgets.QLineEdit()
        self.collect_scope_combo = QtWidgets.QComboBox()
        self.collect_scope_combo.addItem("收藏维度: 演员", "actor")
        self.collect_scope_combo.addItem("收藏维度: 系列", "series")
        self.collect_scope_combo.addItem("收藏维度: 片商/卖家", "maker")
        self.collect_scope_combo.addItem("收藏维度: 导演", "director")
        self.collect_scope_combo.addItem("收藏维度: 番号", "code")
        self.fetch_mode_combo = QtWidgets.QComboBox()
        self.fetch_mode_combo.addItem("httpx（默认）", "httpx")
        self.fetch_mode_combo.addItem("browser（Playwright）", "browser")
        self.browser_profile_input = QtWidgets.QLineEdit(
            str(DEFAULT_BROWSER_USER_DATA_DIR)
        )
        self.browser_headless_cb = QtWidgets.QCheckBox("无头模式")
        self.browser_timeout_spin = QtWidgets.QSpinBox()
        self.browser_timeout_spin.setRange(5, 600)
        self.browser_timeout_spin.setValue(DEFAULT_BROWSER_TIMEOUT_SECONDS)
        self.challenge_timeout_spin = QtWidgets.QSpinBox()
        self.challenge_timeout_spin.setRange(30, 3600)
        self.challenge_timeout_spin.setValue(DEFAULT_CHALLENGE_TIMEOUT_SECONDS)
        self.filter_mode_combo.currentIndexChanged.connect(self._on_filter_mode_changed)
        self._on_filter_mode_changed()

        cookie_btn = QtWidgets.QPushButton("浏览")
        db_btn = QtWidgets.QPushButton("浏览")
        output_btn = QtWidgets.QPushButton("浏览")
        browser_profile_btn = QtWidgets.QPushButton("浏览")
        cookie_btn.setObjectName("ghostButton")
        db_btn.setObjectName("ghostButton")
        output_btn.setObjectName("ghostButton")
        browser_profile_btn.setObjectName("ghostButton")

        cookie_btn.clicked.connect(self._pick_cookie)
        db_btn.clicked.connect(self._pick_db)
        output_btn.clicked.connect(self._pick_output)
        browser_profile_btn.clicked.connect(self._pick_browser_profile)

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

        config_layout.addWidget(QtWidgets.QLabel("筛选模式"), 4, 0)
        config_layout.addWidget(self.filter_mode_combo, 4, 1, 1, 2)
        config_layout.addWidget(QtWidgets.QLabel("筛选值"), 5, 0)
        config_layout.addWidget(self.filter_values_input, 5, 1, 1, 2)
        config_layout.addWidget(QtWidgets.QLabel("收藏维度"), 6, 0)
        config_layout.addWidget(self.collect_scope_combo, 6, 1, 1, 2)
        config_layout.addWidget(QtWidgets.QLabel("抓取模式"), 7, 0)
        config_layout.addWidget(self.fetch_mode_combo, 7, 1, 1, 2)
        config_layout.addWidget(QtWidgets.QLabel("浏览器会话目录"), 8, 0)
        config_layout.addWidget(self.browser_profile_input, 8, 1)
        config_layout.addWidget(browser_profile_btn, 8, 2)
        config_layout.addWidget(QtWidgets.QLabel("浏览器超时(s)"), 9, 0)
        config_layout.addWidget(self.browser_timeout_spin, 9, 1, 1, 2)
        config_layout.addWidget(QtWidgets.QLabel("验证等待(s)"), 10, 0)
        config_layout.addWidget(self.challenge_timeout_spin, 10, 1, 1, 2)
        config_layout.addWidget(QtWidgets.QLabel("Browser 选项"), 11, 0)
        config_layout.addWidget(self.browser_headless_cb, 11, 1, 1, 2)

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

        data_toolbar = QtWidgets.QVBoxLayout()
        data_toolbar.setSpacing(8)
        toolbar_row_top = QtWidgets.QHBoxLayout()
        toolbar_row_top.setSpacing(8)
        toolbar_row_bottom = QtWidgets.QHBoxLayout()
        toolbar_row_bottom.setSpacing(8)
        self.search_mode_combo = QtWidgets.QComboBox()
        self.search_mode_combo.addItem("演员", "actor")
        self.search_mode_combo.addItem("番号", "code")
        self.search_mode_combo.addItem("标题", "title")
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("输入关键词（包含匹配）")
        self.search_input.setMinimumWidth(340)
        self.search_input.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self.clear_search_btn = QtWidgets.QPushButton("清空")
        self.clear_search_btn.setObjectName("ghostButton")

        self.actor_sort_combo = QtWidgets.QComboBox()
        self.actor_sort_combo.addItem("演员 A-Z", "actor_asc")
        self.actor_sort_combo.addItem("演员 Z-A", "actor_desc")
        self.works_sort_combo = QtWidgets.QComboBox()
        self.works_sort_combo.addItem("番号 ↑", "code_asc")
        self.works_sort_combo.addItem("番号 ↓", "code_desc")
        self.works_sort_combo.addItem("标题 ↑", "title_asc")
        self.works_sort_combo.addItem("标题 ↓", "title_desc")

        self.magnet_filter_combo = QtWidgets.QComboBox()
        self.magnet_filter_combo.addItem("磁链: 全部", "all")
        self.magnet_filter_combo.addItem("磁链: 有", "with")
        self.magnet_filter_combo.addItem("磁链: 无", "without")
        self.code_filter_combo = QtWidgets.QComboBox()
        self.code_filter_combo.addItem("无码筛选: 全部", "all")
        self.code_filter_combo.addItem("无码筛选: 有码", "coded")
        self.code_filter_combo.addItem("无码筛选: 无码", "uncensored")
        self.subtitle_filter_combo = QtWidgets.QComboBox()
        self.subtitle_filter_combo.addItem("字幕: 全部", "all")
        self.subtitle_filter_combo.addItem("字幕: 有", "subtitle")
        self.subtitle_filter_combo.addItem("字幕: 无", "no_subtitle")

        self.refresh_data_btn = QtWidgets.QPushButton("刷新")
        self.open_link_btn = QtWidgets.QPushButton("打开链接")
        self.export_btn = QtWidgets.QPushButton("导出选中")
        self.works_edit_cb = QtWidgets.QCheckBox("编辑作品")
        self.save_works_btn = QtWidgets.QPushButton("保存修改")
        self.result_count_label = QtWidgets.QLabel("演员: 0 | 作品: 0")
        self.result_count_label.setObjectName("hintLabel")
        self.refresh_data_btn.setObjectName("ghostButton")
        self.open_link_btn.setObjectName("ghostButton")
        self.export_btn.setObjectName("ghostButton")
        self.save_works_btn.setObjectName("ghostButton")
        self.refresh_data_btn.clicked.connect(self._load_data)
        self.open_link_btn.clicked.connect(self._open_selected_work_link)
        self.export_btn.clicked.connect(self._export_selected_magnets)
        self.works_edit_cb.toggled.connect(self._on_works_edit_toggled)
        self.save_works_btn.clicked.connect(self._save_works_edits)
        self.clear_search_btn.clicked.connect(self.search_input.clear)
        self.save_works_btn.setEnabled(False)

        self.search_mode_combo.currentIndexChanged.connect(
            lambda _: self._refresh_data_view()
        )
        self.search_input.textChanged.connect(lambda _: self._refresh_data_view())
        self.actor_sort_combo.currentIndexChanged.connect(
            lambda _: self._refresh_data_view()
        )
        self.works_sort_combo.currentIndexChanged.connect(
            lambda _: self._refresh_data_view()
        )
        self.magnet_filter_combo.currentIndexChanged.connect(
            lambda _: self._refresh_data_view()
        )
        self.code_filter_combo.currentIndexChanged.connect(
            lambda _: self._refresh_data_view()
        )
        self.subtitle_filter_combo.currentIndexChanged.connect(
            lambda _: self._refresh_data_view()
        )

        toolbar_row_top.addWidget(QtWidgets.QLabel("搜索"))
        toolbar_row_top.addWidget(self.search_mode_combo)
        toolbar_row_top.addWidget(self.search_input, stretch=1)
        toolbar_row_top.addWidget(self.clear_search_btn)
        toolbar_row_top.addStretch(1)

        toolbar_row_bottom.addWidget(self.actor_sort_combo)
        toolbar_row_bottom.addWidget(self.works_sort_combo)
        toolbar_row_bottom.addWidget(self.magnet_filter_combo)
        toolbar_row_bottom.addWidget(self.code_filter_combo)
        toolbar_row_bottom.addWidget(self.subtitle_filter_combo)
        toolbar_row_bottom.addWidget(self.refresh_data_btn)
        toolbar_row_bottom.addWidget(self.open_link_btn)
        toolbar_row_bottom.addWidget(self.export_btn)
        toolbar_row_bottom.addWidget(self.works_edit_cb)
        toolbar_row_bottom.addWidget(self.save_works_btn)
        toolbar_row_bottom.addStretch(1)
        toolbar_row_bottom.addWidget(self.result_count_label)

        data_toolbar.addLayout(toolbar_row_top)
        data_toolbar.addLayout(toolbar_row_bottom)
        data_outer.addLayout(data_toolbar)

        data_layout = QtWidgets.QHBoxLayout()
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(12)

        actor_box = QtWidgets.QGroupBox("演员")
        actor_layout = QtWidgets.QVBoxLayout(actor_box)
        actor_layout.setContentsMargins(12, 12, 12, 12)
        actor_layout.setSpacing(8)
        self.actor_list = QtWidgets.QListWidget()
        self.actor_list.itemSelectionChanged.connect(self._on_actor_selected)
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
        self.works_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.works_table.itemSelectionChanged.connect(self._on_work_selected)
        self.works_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.works_table.customContextMenuRequested.connect(self._on_works_context_menu)
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
        self.default_fetch_mode_combo = QtWidgets.QComboBox()
        self.default_fetch_mode_combo.addItem("httpx（默认）", "httpx")
        self.default_fetch_mode_combo.addItem("browser（Playwright）", "browser")
        self.default_browser_profile = QtWidgets.QLineEdit(
            str(DEFAULT_BROWSER_USER_DATA_DIR)
        )
        self.default_browser_headless_cb = QtWidgets.QCheckBox("无头模式")
        self.default_browser_timeout_spin = QtWidgets.QSpinBox()
        self.default_browser_timeout_spin.setRange(5, 600)
        self.default_browser_timeout_spin.setValue(DEFAULT_BROWSER_TIMEOUT_SECONDS)
        self.default_challenge_timeout_spin = QtWidgets.QSpinBox()
        self.default_challenge_timeout_spin.setRange(30, 3600)
        self.default_challenge_timeout_spin.setValue(DEFAULT_CHALLENGE_TIMEOUT_SECONDS)
        default_browser_profile_btn = QtWidgets.QPushButton("浏览")
        default_browser_profile_btn.setObjectName("ghostButton")
        default_browser_profile_btn.clicked.connect(self._pick_default_browser_profile)
        settings_form.addRow("Cookie", self.default_cookie)
        settings_form.addRow("数据库", self.default_db)
        settings_form.addRow("输出目录", self.default_output)
        settings_form.addRow("延时范围 (s)", self.delay_range)
        settings_form.addRow("抓取模式", self.default_fetch_mode_combo)
        default_browser_profile_row = QtWidgets.QHBoxLayout()
        default_browser_profile_row.addWidget(self.default_browser_profile)
        default_browser_profile_row.addWidget(default_browser_profile_btn)
        settings_form.addRow("浏览器会话目录", default_browser_profile_row)
        settings_form.addRow("浏览器超时 (s)", self.default_browser_timeout_spin)
        settings_form.addRow("验证等待 (s)", self.default_challenge_timeout_spin)
        settings_form.addRow("Browser 选项", self.default_browser_headless_cb)
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

    def _pick_browser_profile(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择浏览器会话目录", str(Path.cwd())
        )
        if path:
            self.browser_profile_input.setText(path)

    def _pick_default_browser_profile(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择默认浏览器会话目录", str(Path.cwd())
        )
        if path:
            self.default_browser_profile.setText(path)

    def _open_output_dir(self) -> None:
        path = resolve_stored_path(
            self.output_input.text().strip() or str(DEFAULT_OUTPUT), self._runtime_root()
        )
        if path.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _open_db_file(self) -> None:
        path = resolve_stored_path(
            self.db_input.text().strip() or str(DEFAULT_DB), self._runtime_root()
        )
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
            QLabel#hintLabel {
                color: #5B6B8A;
                font-size: 12px;
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
            QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QListWidget {
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

    def _runtime_root(self) -> Path:
        return self._runtime_root_path

    def _set_combo_value(self, combo: QtWidgets.QComboBox, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _config_file_path(self) -> Path:
        return self._runtime_root() / "config.ini"

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

    def _legacy_qsettings_defaults(self) -> dict[str, str]:
        settings = self._flow_settings()
        return {
            "cookie": str(settings.value("defaults/cookie", "", type=str) or ""),
            "db": str(settings.value("defaults/db", "", type=str) or ""),
            "output_dir": str(settings.value("defaults/output", "", type=str) or ""),
            "delay_range": str(
                settings.value("defaults/delay", "0.8-1.6", type=str) or "0.8-1.6"
            ),
        }

    def _migrate_legacy_config_once(self) -> None:
        try:
            migrate_legacy_config_once(
                config_file=self._config_file_path(),
                runtime_root=self._runtime_root(),
                qsettings_defaults=self._legacy_qsettings_defaults(),
                legacy_root=Path.home() / ".crawljav",
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("迁移旧配置失败，将使用默认配置：%s", exc)
            self._save_ini_config()

    def _load_ini_config(self) -> dict[str, object]:
        config_file = self._config_file_path()
        if not config_file.exists():
            self._save_ini_config()
        return load_ini_config(config_file, self._runtime_root())

    def _save_ini_config(self, *, migrated_from_legacy: bool = False) -> None:
        cookie_path = resolve_stored_path(
            self.cookie_input.text().strip() or str(DEFAULT_COOKIE),
            self._runtime_root(),
        )
        db_path = resolve_stored_path(
            self.db_input.text().strip() or str(DEFAULT_DB),
            self._runtime_root(),
        )
        output_dir = resolve_stored_path(
            self.output_input.text().strip() or str(DEFAULT_OUTPUT),
            self._runtime_root(),
        )
        fetch_mode = (
            self.fetch_mode_combo.currentData()
            if self.fetch_mode_combo.currentData() in ("httpx", "browser")
            else DEFAULT_FETCH_MODE
        )
        collect_scope = (
            self.collect_scope_combo.currentData()
            if self.collect_scope_combo.currentData()
            in ("actor", "series", "maker", "director", "code")
            else "actor"
        )
        browser_user_data_dir = resolve_stored_path(
            self.browser_profile_input.text().strip()
            or str(DEFAULT_BROWSER_USER_DATA_DIR),
            self._runtime_root(),
        )
        delay_range = self.delay_range.text().strip() or "0.8-1.6"
        save_ini_config(
            config_file=self._config_file_path(),
            runtime_root=self._runtime_root(),
            cookie_path=cookie_path,
            db_path=db_path,
            output_dir=output_dir,
            delay_range=delay_range,
            fetch_mode=fetch_mode,
            collect_scope=str(collect_scope),
            browser_user_data_dir=browser_user_data_dir,
            browser_headless=self.browser_headless_cb.isChecked(),
            browser_timeout_seconds=self.browser_timeout_spin.value(),
            challenge_timeout_seconds=self.challenge_timeout_spin.value(),
            migrated_from_legacy=migrated_from_legacy,
        )

    def _load_defaults(self) -> None:
        loaded = self._load_ini_config()
        cookie_path = Path(str(loaded["cookie"]))
        db_path = Path(str(loaded["db"]))
        output_dir = Path(str(loaded["output_dir"]))
        delay = str(loaded["delay_range"])
        fetch_mode = str(loaded.get("fetch_mode", DEFAULT_FETCH_MODE))
        collect_scope = str(loaded.get("collect_scope", DEFAULT_COLLECT_SCOPE))
        browser_profile = Path(str(loaded.get("browser_user_data_dir", DEFAULT_BROWSER_USER_DATA_DIR)))
        browser_headless = bool(loaded.get("browser_headless", False))
        browser_timeout = int(
            loaded.get("browser_timeout_seconds", DEFAULT_BROWSER_TIMEOUT_SECONDS)
        )
        challenge_timeout = int(
            loaded.get("challenge_timeout_seconds", DEFAULT_CHALLENGE_TIMEOUT_SECONDS)
        )
        self.default_cookie.setText(str(cookie_path))
        self.default_db.setText(str(db_path))
        self.default_output.setText(str(output_dir))
        self.delay_range.setText(delay)
        self._set_combo_value(self.default_fetch_mode_combo, fetch_mode)
        self.default_browser_profile.setText(str(browser_profile))
        self.default_browser_headless_cb.setChecked(browser_headless)
        self.default_browser_timeout_spin.setValue(browser_timeout)
        self.default_challenge_timeout_spin.setValue(challenge_timeout)
        self.cookie_input.setText(str(cookie_path))
        self.db_input.setText(str(db_path))
        self.output_input.setText(str(output_dir))
        self._set_combo_value(self.fetch_mode_combo, fetch_mode)
        self._set_combo_value(self.collect_scope_combo, collect_scope)
        self.browser_profile_input.setText(str(browser_profile))
        self.browser_headless_cb.setChecked(browser_headless)
        self.browser_timeout_spin.setValue(browser_timeout)
        self.challenge_timeout_spin.setValue(challenge_timeout)

    def _save_defaults(self) -> None:
        prev_db = self.db_input.text().strip()
        cookie = self.default_cookie.text().strip() or str(DEFAULT_COOKIE)
        db_path = self.default_db.text().strip() or str(DEFAULT_DB)
        output_dir = self.default_output.text().strip() or str(DEFAULT_OUTPUT)
        delay = self.delay_range.text().strip() or "0.8-1.6"
        fetch_mode = (
            self.default_fetch_mode_combo.currentData()
            if self.default_fetch_mode_combo.currentData() in ("httpx", "browser")
            else DEFAULT_FETCH_MODE
        )
        browser_profile = (
            self.default_browser_profile.text().strip()
            or str(DEFAULT_BROWSER_USER_DATA_DIR)
        )
        browser_timeout = self.default_browser_timeout_spin.value()
        challenge_timeout = self.default_challenge_timeout_spin.value()
        browser_headless = self.default_browser_headless_cb.isChecked()
        self.cookie_input.setText(cookie)
        self.db_input.setText(db_path)
        self.output_input.setText(output_dir)
        self.delay_range.setText(delay)
        self._set_combo_value(self.fetch_mode_combo, str(fetch_mode))
        self.browser_profile_input.setText(browser_profile)
        self.browser_timeout_spin.setValue(browser_timeout)
        self.challenge_timeout_spin.setValue(challenge_timeout)
        self.browser_headless_cb.setChecked(browser_headless)
        try:
            self._save_ini_config()
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "配置错误", f"保存配置失败：{exc}")
            return
        self._ensure_default_db()
        if prev_db != self.db_input.text().strip():
            self._load_data()
        QtWidgets.QMessageBox.information(self, "完成", "默认设置已保存。")

    def _ensure_default_db(self) -> None:
        db_path = resolve_stored_path(
            self.db_input.text().strip() or str(DEFAULT_DB), self._runtime_root()
        )
        self.db_input.setText(str(db_path))
        self.default_db.setText(str(db_path))
        if db_path.exists():
            return
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Storage(db_path):
                pass
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("初始化数据库失败: %s", exc)
            QtWidgets.QMessageBox.warning(self, "数据库错误", f"初始化数据库失败：{exc}")

    def _show_runtime_fallback_notice(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "提示",
            f"应用目录不可写，已将运行目录切换到：{self._runtime_root()}",
        )

    def _on_filter_mode_changed(self, *_args) -> None:
        mode = self._current_filter_mode()
        if mode == "actor":
            placeholder = "输入演员名，多个用逗号分隔"
        elif mode == "code":
            placeholder = "输入番号关键词，多个用逗号分隔（contains）"
        else:
            placeholder = "输入系列前缀，多个用逗号分隔（prefix）"
        self.filter_values_input.setPlaceholderText(placeholder)

    def _current_filter_mode(self) -> Literal["actor", "code", "series"]:
        mode = self.filter_mode_combo.currentData()
        if mode in ("actor", "code", "series"):
            return mode
        return "actor"

    def _parse_filter_values(self, raw: str) -> list[str]:
        parts = raw.replace("，", ",").split(",")
        result: list[str] = []
        seen: set[str] = set()
        for part in parts:
            item = part.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _selected_stage_labels(self) -> list[str]:
        labels: list[str] = []
        if self.collect_cb.isChecked():
            labels.append("收藏演员")
        if self.works_cb.isChecked():
            labels.append("作品列表")
        if self.magnets_cb.isChecked():
            labels.append("磁链抓取")
        if self.filter_cb.isChecked():
            labels.append("磁链筛选")
        return labels

    def _confirm_special_filter(
        self, *, mode: Literal["code", "series"], values: list[str]
    ) -> bool:
        mode_label = "番号筛选" if mode == "code" else "系列筛选"
        stages = "、".join(self._selected_stage_labels()) or "无阶段（将直接结束）"
        value_text = "、".join(values)
        message = (
            f"筛选模式：{mode_label}\n"
            f"筛选值：{value_text}\n"
            f"本次执行阶段：{stages}\n\n"
            "确认开始吗？"
        )
        reply = QtWidgets.QMessageBox.question(
            self,
            "确认执行",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return reply == QtWidgets.QMessageBox.Yes

    def _start_flow(self) -> None:
        if self._is_thread_running():
            return

        self.default_cookie.setText(self.cookie_input.text().strip())
        self.default_db.setText(self.db_input.text().strip())
        self.default_output.setText(self.output_input.text().strip())
        self._set_combo_value(
            self.default_fetch_mode_combo,
            str(self.fetch_mode_combo.currentData() or DEFAULT_FETCH_MODE),
        )
        self.default_browser_profile.setText(self.browser_profile_input.text().strip())
        self.default_browser_headless_cb.setChecked(self.browser_headless_cb.isChecked())
        self.default_browser_timeout_spin.setValue(self.browser_timeout_spin.value())
        self.default_challenge_timeout_spin.setValue(self.challenge_timeout_spin.value())
        try:
            self._save_ini_config()
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "配置错误", f"保存配置失败：{exc}")
            return

        cookie_path_obj = resolve_stored_path(
            self.cookie_input.text().strip() or str(DEFAULT_COOKIE), self._runtime_root()
        )
        db_path_obj = resolve_stored_path(
            self.db_input.text().strip() or str(DEFAULT_DB), self._runtime_root()
        )
        output_dir_obj = resolve_stored_path(
            self.output_input.text().strip() or str(DEFAULT_OUTPUT), self._runtime_root()
        )

        cookie_path = str(cookie_path_obj)
        fetch_mode = (
            self.fetch_mode_combo.currentData()
            if self.fetch_mode_combo.currentData() in ("httpx", "browser")
            else DEFAULT_FETCH_MODE
        )
        collect_scope = (
            self.collect_scope_combo.currentData()
            if self.collect_scope_combo.currentData()
            in ("actor", "series", "maker", "director", "code")
            else DEFAULT_COLLECT_SCOPE
        )
        if fetch_mode == "httpx":
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
        else:
            if cookie_path:
                try:
                    cookies = load_cookie_dict(cookie_path)
                    if not is_cookie_valid(cookies):
                        LOGGER.warning("浏览器模式下 Cookie 校验未通过，将继续使用持久化会话。")
                except SystemExit as exc:
                    LOGGER.warning("浏览器模式下未加载 Cookie，将继续使用持久化会话：%s", exc)

        filter_mode = self._current_filter_mode()
        filter_values = self._parse_filter_values(self.filter_values_input.text())
        if filter_mode in ("code", "series"):
            if not filter_values:
                QtWidgets.QMessageBox.warning(self, "缺少筛选值", "请至少输入一个筛选值。")
                return
            if not self._confirm_special_filter(mode=filter_mode, values=filter_values):
                return

        self.log_view.clear()
        self.status_label.setText("启动中...")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self._thread = QtCore.QThread(self)
        self._worker = FlowWorker(
            db_path=str(db_path_obj),
            output_dir=str(output_dir_obj),
            cookie_path=cookie_path,
            tags=self.tags_input.text().strip(),
            filter_mode=filter_mode,
            filter_values=filter_values,
            collect_scope=collect_scope,
            fetch_mode=fetch_mode,
            browser_user_data_dir=str(
                resolve_stored_path(
                    self.browser_profile_input.text().strip()
                    or str(DEFAULT_BROWSER_USER_DATA_DIR),
                    self._runtime_root(),
                )
            ),
            browser_headless=self.browser_headless_cb.isChecked(),
            browser_timeout_seconds=self.browser_timeout_spin.value(),
            challenge_timeout_seconds=self.challenge_timeout_spin.value(),
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
        cookie_path = resolve_stored_path(
            self.cookie_input.text().strip() or str(DEFAULT_COOKIE), self._runtime_root()
        )
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
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        cookie_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.cookie_status.setText("已保存到 cookie.json")
        self.cookie_input.setText(str(cookie_path))
        self.default_cookie.setText(str(cookie_path))
        try:
            self._save_ini_config()
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "配置错误", f"保存配置失败：{exc}")
            return
        QtWidgets.QMessageBox.information(self, "完成", "Cookie 校验通过并已保存。")

    def _load_data(self, *, reset_actor: bool = True) -> None:
        path = resolve_stored_path(
            self.db_input.text().strip() or str(DEFAULT_DB), self._runtime_root()
        )
        self.db_input.setText(str(path))
        self.default_db.setText(str(path))
        self._actors_cache = []
        self._works_cache = {}
        self._magnets_cache = {}
        self._all_view_rows = []
        self._active_view_rows = []
        self.actor_list.clear()
        self.works_table.setRowCount(0)
        self.magnets_table.setRowCount(0)
        self.result_count_label.setText("演员: 0 | 作品: 0")
        if not path.exists():
            self._populate_actor_list([])
            return
        try:
            with Storage(path) as store:
                actors = store.iter_actor_urls()
                self._actors_cache = [name for name, _ in actors]
                self._works_cache = store.get_all_actor_works()
                self._magnets_cache = store.get_magnets_grouped()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("读取数据库失败: %s", exc)
            QtWidgets.QMessageBox.warning(self, "数据库错误", f"读取数据库失败：{exc}")
            return
        self._all_view_rows = self._build_work_view_rows()
        self._refresh_data_view(reset_actor=reset_actor)

    def _build_work_view_rows(self) -> list[gdv.WorkViewRow]:
        rows = gdv.build_rows(self._works_cache, self._magnets_cache)
        for row in rows:
            code = str(row.get("code", ""))
            row["is_uncensored"] = self._is_uncensored_code(code)
            row["has_subtitle"] = self._has_subtitle_code(code)
        return rows

    def _current_search_mode(self) -> Literal["actor", "code", "title"]:
        mode = self.search_mode_combo.currentData()
        if mode in ("actor", "code", "title"):
            return mode
        return "actor"

    def _is_uncensored_code(self, code: str) -> bool:
        return "-U" in code.upper()

    def _has_subtitle_code(self, code: str) -> bool:
        return "-C" in code.upper()

    def _apply_data_filters(self, rows: list[gdv.WorkViewRow]) -> list[gdv.WorkViewRow]:
        searched = gdv.search_rows(
            rows,
            mode=self._current_search_mode(),
            keyword=self.search_input.text(),
        )
        return gdv.filter_rows(
            searched,
            magnet_state=self.magnet_filter_combo.currentData() or "all",
            code_state=self.code_filter_combo.currentData() or "all",
            subtitle_state=self.subtitle_filter_combo.currentData() or "all",
        )

    def _refresh_data_view(self, reset_actor: bool = False) -> None:
        current_actor = "" if reset_actor else self._current_actor_name()
        self._active_view_rows = self._apply_data_filters(self._all_view_rows)
        actor_desc = (self.actor_sort_combo.currentData() or "actor_asc") == "actor_desc"
        actor_names = gdv.sort_actor_names(self._active_view_rows, desc=actor_desc)
        empty_text = "暂无演员数据。" if not self._all_view_rows else "无匹配结果。"
        self._populate_actor_list(actor_names, empty_text=empty_text)

        if not actor_names:
            self._current_actor_rows = []
            self.works_table.setRowCount(0)
            self.magnets_table.setRowCount(0)
            self.result_count_label.setText("演员: 0 | 作品: 0")
            return

        actor_to_select = current_actor if current_actor in actor_names else actor_names[0]
        self._select_actor_by_name(actor_to_select)
        self.result_count_label.setText(
            f"演员: {len(actor_names)} | 作品: {len(self._active_view_rows)}"
        )

    def _select_actor_by_name(self, actor_name: str) -> None:
        for row in range(self.actor_list.count()):
            item = self.actor_list.item(row)
            if item and item.text() == actor_name:
                self.actor_list.setCurrentRow(row)
                return

    def _current_actor_name(self) -> str:
        items = self.actor_list.selectedItems()
        if not items:
            return ""
        return items[0].text()

    def _populate_actor_list(self, names: list[str], empty_text: str = "暂无演员数据。") -> None:
        self.actor_list.clear()
        if not names:
            self.actor_list.addItem(empty_text)
            return
        for name in names:
            self.actor_list.addItem(name)

    def _on_actor_selected(self) -> None:
        items = self.actor_list.selectedItems()
        if not items:
            return
        actor_name = items[0].text()
        if actor_name in ("暂无演员数据。", "无匹配结果。"):
            self._current_actor_rows = []
            return
        works_rows = [row for row in self._active_view_rows if row["actor"] == actor_name]
        works_sort = self.works_sort_combo.currentData() or "code_asc"
        work_key: gdv.WorkSortKey = (
            "code" if str(works_sort).startswith("code_") else "title"
        )
        desc = str(works_sort).endswith("_desc")
        sorted_rows = gdv.sort_actor_works(works_rows, key=work_key, desc=desc)
        self._current_actor_rows = sorted_rows
        works = [
            {"code": row["code"], "title": row["title"], "href": row["href"]}
            for row in sorted_rows
        ]
        self._populate_works_table(works)
        self.magnets_table.setRowCount(0)

    def _populate_works_table(self, works: list[dict]) -> None:
        self.works_table.setRowCount(0)
        if not works:
            return
        self.works_table.setRowCount(len(works))
        editable = self.works_edit_cb.isChecked()
        for row, work in enumerate(works):
            code = str(work.get("code", ""))
            title = str(work.get("title", ""))
            href = str(work.get("href", ""))
            code_item = QtWidgets.QTableWidgetItem(code)
            title_item = QtWidgets.QTableWidgetItem(title)
            href_item = QtWidgets.QTableWidgetItem(href)
            if editable:
                code_item.setFlags(code_item.flags() | QtCore.Qt.ItemIsEditable)
                title_item.setFlags(title_item.flags() | QtCore.Qt.ItemIsEditable)
            else:
                code_item.setFlags(code_item.flags() & ~QtCore.Qt.ItemIsEditable)
                title_item.setFlags(title_item.flags() & ~QtCore.Qt.ItemIsEditable)
            href_item.setFlags(href_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.works_table.setItem(row, 0, code_item)
            self.works_table.setItem(row, 1, title_item)
            self.works_table.setItem(row, 2, href_item)
        if editable:
            self.works_table.setEditTriggers(
                QtWidgets.QAbstractItemView.DoubleClicked
                | QtWidgets.QAbstractItemView.EditKeyPressed
                | QtWidgets.QAbstractItemView.SelectedClicked
            )
        else:
            self.works_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.works_table.resizeColumnsToContents()

    def _selected_work_rows(self) -> list[gdv.WorkViewRow]:
        selected_indexes = sorted({index.row() for index in self.works_table.selectedIndexes()})
        rows: list[gdv.WorkViewRow] = []
        for row_index in selected_indexes:
            if 0 <= row_index < len(self._current_actor_rows):
                rows.append(self._current_actor_rows[row_index])
        return rows

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

    def _on_works_context_menu(self, pos: QtCore.QPoint) -> None:
        selected_rows = self._selected_work_rows()
        menu = QtWidgets.QMenu(self)
        copy_code_action = menu.addAction("复制番号")
        copy_title_action = menu.addAction("复制标题")
        copy_magnet_action = menu.addAction("复制磁链")
        has_selection = bool(selected_rows)
        copy_code_action.setEnabled(has_selection)
        copy_title_action.setEnabled(has_selection)
        copy_magnet_action.setEnabled(has_selection)

        action = menu.exec_(self.works_table.viewport().mapToGlobal(pos))
        if action is copy_code_action:
            self._copy_selected_works("code")
        elif action is copy_title_action:
            self._copy_selected_works("title")
        elif action is copy_magnet_action:
            self._copy_selected_works("magnet")

    def _copy_selected_works(self, kind: gdv.CopyKind) -> None:
        actor_name = self._current_actor_name()
        actor_magnets = self._magnets_cache.get(actor_name, {})
        text = gdv.build_copy_text(kind, self._selected_work_rows(), actor_magnets)
        if not text:
            QtWidgets.QMessageBox.information(self, "提示", "没有可复制内容。")
            return
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        QtWidgets.QMessageBox.information(self, "完成", "已复制到剪贴板。")

    def _on_works_edit_toggled(self, checked: bool) -> None:
        self.save_works_btn.setEnabled(checked)
        self._on_actor_selected()

    def _save_works_edits(self) -> None:
        if not self.works_edit_cb.isChecked():
            return
        actor_name = self._current_actor_name()
        if not actor_name:
            return
        pending_changes: list[tuple[str, str, str]] = []
        for row_index in range(self.works_table.rowCount()):
            original = self._current_actor_rows[row_index]
            code_item = self.works_table.item(row_index, 0)
            title_item = self.works_table.item(row_index, 1)
            if not code_item or not title_item:
                continue
            new_code = code_item.text().strip()
            new_title = title_item.text().strip()
            old_code = str(original.get("code", "")).strip()
            old_title = str(original.get("title", "")).strip()
            if not new_code:
                QtWidgets.QMessageBox.warning(self, "保存失败", "番号不能为空。")
                return
            if new_code != old_code or new_title != old_title:
                pending_changes.append((old_code, new_code, new_title))

        if not pending_changes:
            QtWidgets.QMessageBox.information(self, "提示", "没有需要保存的修改。")
            return

        db_path = self.db_input.text().strip() or str(DEFAULT_DB)
        db_path_obj = resolve_stored_path(db_path, self._runtime_root())
        try:
            with Storage(str(db_path_obj)) as store:
                for old_code, new_code, new_title in pending_changes:
                    updated = store.update_work_fields(
                        actor_name=actor_name,
                        old_code=old_code,
                        new_code=new_code,
                        new_title=new_title,
                    )
                    if not updated:
                        raise ValueError(f"未找到作品：{old_code}")
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "保存失败", str(exc))
            self._on_actor_selected()
            return
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "保存失败", f"写入数据库失败：{exc}")
            self._on_actor_selected()
            return

        QtWidgets.QMessageBox.information(self, "完成", f"已保存 {len(pending_changes)} 条修改。")
        self._load_data(reset_actor=False)

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
        selected_rows = self._selected_work_rows()
        if not selected_rows:
            QtWidgets.QMessageBox.information(self, "提示", "请先选择作品。")
            return
        actor_name = self._current_actor_name()
        actor_magnets = self._magnets_cache.get(actor_name, {})
        if len(selected_rows) == 1:
            code = selected_rows[0]["code"].strip() or "magnets"
            magnets = actor_magnets.get(code, [])
            lines = list(
                dict.fromkeys(
                    [
                        str(item.get("magnet", "")).strip()
                        for item in magnets
                        if str(item.get("magnet", "")).strip()
                    ]
                )
            )
            default_name = f"{code}.txt"
        else:
            lines = gdv.build_magnet_export_lines(selected_rows, actor_magnets)
            default_name = "batch_magnets.txt"

        if not lines:
            QtWidgets.QMessageBox.information(self, "提示", "所选作品无可导出磁链。")
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出磁链", str(Path.cwd() / default_name), "Text Files (*.txt)"
        )
        if not path:
            return
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        QtWidgets.QMessageBox.information(self, "完成", f"已导出 {len(lines)} 条。")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        try:
            self._save_ini_config()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("关闭前保存配置失败：%s", exc)
        LOGGER.removeHandler(self._log_handler)
        super().closeEvent(event)


def main() -> int:
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
