import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from lexiaodu.font_scaling import ApplicationFontScaler


def _set_application_point_size(
    application: QApplication,
    point_size: float,
) -> None:
    font = QFont(application.font())
    font.setPointSizeF(point_size)
    application.setFont(font)


@pytest.fixture
def qt_application():
    application = QApplication.instance() or QApplication([])
    original_font = QFont(application.font())
    original_widgets = set(application.topLevelWidgets())
    original_scalers = set(application.findChildren(ApplicationFontScaler))
    yield application

    for widget in set(application.topLevelWidgets()) - original_widgets:
        widget.close()
        widget.deleteLater()
    for scaler in (
        set(application.findChildren(ApplicationFontScaler))
        - original_scalers
    ):
        application.removeEventFilter(scaler)
        scaler.deleteLater()
    application.setProperty("_lexiaodu_font_delta_points", None)
    application.setFont(original_font)
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def test_scaler_starts_one_point_larger_and_applies_to_new_widgets(
    qt_application: QApplication,
) -> None:
    _set_application_point_size(qt_application, 10.0)

    scaler = ApplicationFontScaler(qt_application)
    widget = QWidget()

    assert scaler.current_point_size == pytest.approx(11.0)
    assert qt_application.font().pointSizeF() == pytest.approx(11.0)
    assert widget.font().pointSizeF() == pytest.approx(11.0)


def test_ctrl_plus_and_minus_adjust_while_input_has_focus(
    qt_application: QApplication,
) -> None:
    _set_application_point_size(qt_application, 10.0)
    scaler = ApplicationFontScaler(qt_application)
    editor = QLineEdit()
    editor.show()
    editor.setFocus()

    QTest.keyClick(
        editor,
        Qt.Key.Key_Plus,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert scaler.current_point_size == pytest.approx(12.0)

    QTest.keyClick(
        editor,
        Qt.Key.Key_Minus,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert scaler.current_point_size == pytest.approx(11.0)
    assert editor.text() == ""


def test_scaler_clamps_repeated_shortcuts_to_safe_bounds(
    qt_application: QApplication,
) -> None:
    _set_application_point_size(qt_application, 23.0)
    scaler = ApplicationFontScaler(qt_application)
    target = QLineEdit()

    QTest.keyClick(
        target,
        Qt.Key.Key_Plus,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert scaler.current_point_size == pytest.approx(24.0)

    QTest.keyClick(
        target,
        Qt.Key.Key_Plus,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert scaler.current_point_size == pytest.approx(24.0)

    for _ in range(20):
        QTest.keyClick(
            target,
            Qt.Key.Key_Minus,
            Qt.KeyboardModifier.ControlModifier,
        )
    assert scaler.current_point_size == pytest.approx(8.0)


def test_keypad_plus_uses_the_same_global_adjustment(
    qt_application: QApplication,
) -> None:
    _set_application_point_size(qt_application, 10.0)
    scaler = ApplicationFontScaler(qt_application)
    target = QLineEdit()
    modifiers = (
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.KeypadModifier
    )

    QTest.keyClick(target, Qt.Key.Key_Plus, modifiers)

    assert scaler.current_point_size == pytest.approx(12.0)


def test_pixel_only_system_font_uses_nine_point_fallback(
    qt_application: QApplication,
) -> None:
    font = QFont(qt_application.font())
    font.setPixelSize(12)
    qt_application.setFont(font)

    scaler = ApplicationFontScaler(qt_application)

    assert scaler.current_point_size == pytest.approx(10.0)

