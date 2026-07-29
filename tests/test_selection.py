import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

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
