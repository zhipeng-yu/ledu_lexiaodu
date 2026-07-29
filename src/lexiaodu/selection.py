from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QWidget

from lexiaodu.domain import ScreenRegion


def region_from_points(
    start: QPoint,
    end: QPoint,
    desktop_offset: QPoint = QPoint(),
    *,
    minimum_size: int = 4,
) -> ScreenRegion | None:
    """Build a normalized desktop region from two overlay-local points."""

    left = min(start.x(), end.x())
    top = min(start.y(), end.y())
    width = abs(end.x() - start.x())
    height = abs(end.y() - start.y())
    if width < minimum_size or height < minimum_size:
        return None
    return ScreenRegion(
        x=desktop_offset.x() + left,
        y=desktop_offset.y() + top,
        width=width,
        height=height,
    )


class SelectionOverlay(QWidget):
    """A translucent virtual-desktop overlay for drag-to-select capture."""

    region_selected = Signal(object)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self.setWindowTitle("框选截图区域")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def start(self) -> None:
        screens = QGuiApplication.screens()
        if not screens:
            self.cancelled.emit()
            return
        geometry = screens[0].geometry()
        for screen in screens[1:]:
            geometry = geometry.united(screen.geometry())
        self.setGeometry(geometry)
        self._start = None
        self._current = None
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def _selection_rect(self) -> QRect | None:
        if self._start is None or self._current is None:
            return None
        left = min(self._start.x(), self._current.x())
        top = min(self._start.y(), self._current.y())
        return QRect(
            left,
            top,
            abs(self._current.x() - self._start.x()),
            abs(self._current.y() - self._start.y()),
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(10, 14, 20, 105))
        selection = self._selection_rect()
        if selection is None or selection.isEmpty():
            painter.setPen(QColor(255, 255, 255, 225))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "拖动鼠标框选聊天区域 · Esc 取消",
            )
            return

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(selection, Qt.GlobalColor.transparent)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceOver
        )
        painter.setPen(QPen(QColor("#4f8cff"), 2))
        painter.drawRect(selection)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._current = self._start
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._current = event.position().toPoint()
        region = region_from_points(
            self._start,
            self._current,
            self.geometry().topLeft(),
        )
        if region is None:
            self._start = None
            self._current = None
            self.update()
            return

        self.hide()
        QTimer.singleShot(80, lambda: self.region_selected.emit(region))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.cancelled.emit()
            return
        super().keyPressEvent(event)
