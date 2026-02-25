"""GUI 启动入口。"""

from app.gui import main_window as _main_window
from app.gui import data_view
from app.gui import gui_config

MainWindow = _main_window.MainWindow
QtWidgets = _main_window.QtWidgets
is_cookie_valid = _main_window.is_cookie_valid
load_cookie_dict = _main_window.load_cookie_dict
main = _main_window.main

__all__ = [
    "MainWindow",
    "QtWidgets",
    "data_view",
    "gui_config",
    "is_cookie_valid",
    "load_cookie_dict",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
