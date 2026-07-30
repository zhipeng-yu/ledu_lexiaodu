import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from lexiaodu.app import _configure_application
from lexiaodu.domain import ScreenRegion
from lexiaodu.selection import SelectionOverlay, region_from_points


def test_normalize_drag_points_into_desktop_region() -> None:
    region = region_from_points(
        QPoint(300, 200),
        QPoint(100, 80),
        QPoint(-1920, 0),
    )

    assert region == ScreenRegion(x=-1820, y=80, width=200, height=120)


def test_ignore_tiny_drag_region() -> None:
    assert region_from_points(QPoint(10, 10), QPoint(12, 12)) is None


def test_selection_overlay_is_frameless_and_stays_on_top() -> None:
    application = QApplication.instance() or QApplication([])
    overlay = SelectionOverlay()

    assert application is not None
    assert overlay.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint

    overlay.close()


def test_delayed_selection_survives_while_all_windows_are_hidden() -> None:
    application = QApplication.instance() or QApplication([])
    previous_quit_policy = application.quitOnLastWindowClosed()
    overlay = SelectionOverlay()
    selected: list[ScreenRegion] = []
    overlay.region_selected.connect(selected.append)

    try:
        _configure_application(application, "乐小读")
        overlay.start()
        QTest.mousePress(
            overlay,
            Qt.MouseButton.LeftButton,
            pos=QPoint(10, 10),
        )
        QTest.mouseRelease(
            overlay,
            Qt.MouseButton.LeftButton,
            pos=QPoint(110, 90),
        )

        assert not overlay.isVisible()
        QTest.qWait(100)
        assert len(selected) == 1
        assert selected[0].width == 100
        assert selected[0].height == 80
    finally:
        overlay.close()
        application.setQuitOnLastWindowClosed(previous_quit_policy)
