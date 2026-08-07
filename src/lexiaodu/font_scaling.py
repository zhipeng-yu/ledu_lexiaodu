from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import QApplication


_FONT_DELTA_PROPERTY = "_lexiaodu_font_delta_points"
_FALLBACK_POINT_SIZE = 9.0


def scaled_point_size(base_point_size: float) -> float:
    application = QApplication.instance()
    raw_delta = (
        application.property(_FONT_DELTA_PROPERTY)
        if application is not None
        else None
    )
    try:
        delta = float(raw_delta)
    except (TypeError, ValueError):
        delta = 0.0
    return base_point_size + delta


class ApplicationFontScaler(QObject):
    def __init__(
        self,
        application: QApplication,
        *,
        minimum_point_size: float = 8.0,
        maximum_point_size: float = 24.0,
        initial_increment: float = 1.0,
    ) -> None:
        super().__init__(application)
        self._application = application
        self._base_font = QFont(application.font())
        raw_point_size = self._base_font.pointSizeF()
        self._base_point_size = (
            raw_point_size
            if raw_point_size > 0
            else _FALLBACK_POINT_SIZE
        )
        self._minimum_point_size = minimum_point_size
        self._maximum_point_size = maximum_point_size
        self._current_point_size = self._base_point_size
        application.installEventFilter(self)
        self._set_point_size(self._base_point_size + initial_increment)

    @property
    def current_point_size(self) -> float:
        return self._current_point_size

    def _set_point_size(self, requested: float) -> None:
        point_size = min(
            self._maximum_point_size,
            max(self._minimum_point_size, requested),
        )
        self._current_point_size = point_size
        self._application.setProperty(
            _FONT_DELTA_PROPERTY,
            point_size - self._base_point_size,
        )
        font = QFont(self._base_font)
        font.setPointSizeF(point_size)
        self._application.setFont(font)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
        ):
            modifiers = event.modifiers()
            controlled = bool(
                modifiers & Qt.KeyboardModifier.ControlModifier
            )
            excluded = bool(
                modifiers
                & (
                    Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier
                )
            )
            if controlled and not excluded and event.key() == Qt.Key.Key_Plus:
                self._set_point_size(self._current_point_size + 1.0)
                return True
            if controlled and not excluded and event.key() == Qt.Key.Key_Minus:
                self._set_point_size(self._current_point_size - 1.0)
                return True
        return super().eventFilter(watched, event)
