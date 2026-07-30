from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy, QToolBar


class FloatingToolbar(QToolBar):
    capture_requested = Signal()
    ai_chat_requested = Signal()

    def __init__(self, app_name: str, width: int, height: int) -> None:
        super().__init__()
        self._drag_offset: QPoint | None = None
        self.setObjectName("floatingToolbar")
        self.setWindowTitle(app_name)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMovable(False)
        self.setFloatable(False)
        self.setFixedSize(width, height)

        title = QLabel(app_name)
        title.setObjectName("title")
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(title)

        capture_action = QAction("框选截图", self)
        capture_action.setToolTip("拖框截取聊天区域并识别文字")
        capture_action.triggered.connect(self.capture_requested.emit)
        self.addAction(capture_action)

        chat_action = QAction("AI 问答", self)
        chat_action.setToolTip("手动输入家长问题并与 AI 多轮问答")
        chat_action.triggered.connect(self.ai_chat_requested.emit)
        self.addAction(chat_action)

        close_action = QAction("关闭", self)
        close_action.triggered.connect(QApplication.quit)
        self.addAction(close_action)

        self._status = QLabel("就绪")
        self._status.setObjectName("status")
        self.addWidget(self._status)

        self.setStyleSheet(
            """
            QToolBar#floatingToolbar {
                background: #20252d;
                border: 1px solid #3a4350;
                border-radius: 10px;
                padding: 6px 10px;
                spacing: 8px;
            }
            QLabel { color: #f4f6f8; }
            QLabel#title { font-size: 15px; font-weight: 600; }
            QLabel#status { color: #aeb8c5; }
            QToolButton {
                color: #f4f6f8;
                background: #356ae6;
                border: 0;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QToolButton:hover { background: #477af0; }
            """
        )

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    @property
    def status_text(self) -> str:
        return self._status.text()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)
