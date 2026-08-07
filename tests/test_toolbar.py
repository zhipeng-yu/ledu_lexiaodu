import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from lexiaodu.font_scaling import ApplicationFontScaler
from lexiaodu.toolbar import FloatingToolbar


def test_toolbar_title_follows_global_scaling() -> None:
    application = QApplication.instance() or QApplication([])
    original_font = QFont(application.font())
    original_delta = application.property(
        "_lexiaodu_font_delta_points"
    )
    base_font = QFont(original_font)
    base_font.setPointSizeF(10.0)
    application.setFont(base_font)
    scaler = ApplicationFontScaler(application)
    toolbar = FloatingToolbar("乐小读", width=460, height=52)

    try:
        toolbar.show()
        application.processEvents()
        title = toolbar.findChild(QLabel, "title")
        assert title is not None
        assert title.font().pointSizeF() == pytest.approx(12.0)

        QTest.keyClick(
            toolbar,
            Qt.Key.Key_Plus,
            Qt.KeyboardModifier.ControlModifier,
        )
        application.processEvents()

        assert title.font().pointSizeF() == pytest.approx(13.0)
    finally:
        toolbar.close()
        application.removeEventFilter(scaler)
        scaler.deleteLater()
        application.setProperty(
            "_lexiaodu_font_delta_points",
            original_delta,
        )
        application.setFont(original_font)
        application.processEvents()


def test_toolbar_is_frameless_and_stays_on_top() -> None:
    application = QApplication.instance() or QApplication([])
    toolbar = FloatingToolbar("乐小读", width=460, height=52)

    assert application is not None
    assert toolbar.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert toolbar.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert toolbar.size().width() == 460
    assert any(action.text() == "框选截图" for action in toolbar.actions())
    assert any(action.text() == "AI 问答" for action in toolbar.actions())

    toolbar.close()
