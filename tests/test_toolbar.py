import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from lexiaodu.toolbar import FloatingToolbar


def test_toolbar_is_frameless_and_stays_on_top() -> None:
    application = QApplication.instance() or QApplication([])
    toolbar = FloatingToolbar("乐小读", width=360, height=52)

    assert application is not None
    assert toolbar.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert toolbar.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert toolbar.size().width() == 360

    toolbar.close()
