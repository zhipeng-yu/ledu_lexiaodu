from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class ChatRole(StrEnum):
    QUESTION = "家长问题"
    ASSISTANT = "AI"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatRole
    text: str


class _ChatInput(QPlainTextEdit):
    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        is_enter = event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        )
        is_line_break = bool(
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        )
        if is_enter and not is_line_break:
            event.accept()
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)


class _ConversationTurn(QWidget):
    def __init__(self, role: ChatRole, text: str) -> None:
        super().__init__()
        self.setObjectName(
            "questionTurn"
            if role is ChatRole.QUESTION
            else "assistantTurn"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        row_layout = QHBoxLayout(self)
        row_layout.setContentsMargins(24, 0, 24, 0)
        row_layout.setSpacing(0)
        row_layout.addStretch(1)

        content = QWidget()
        content.setObjectName("turnContent")
        content.setMaximumWidth(760)
        content.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 18, 0, 20)
        content_layout.setSpacing(8)

        role_label = QLabel(role.value)
        role_label.setObjectName("turnRole")
        content_layout.addWidget(role_label)

        body = QLabel(text)
        body.setObjectName("turnBody")
        body.setTextFormat(Qt.TextFormat.PlainText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        body.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        content_layout.addWidget(body)

        row_layout.addWidget(content, 8)
        row_layout.addStretch(1)


class AiChatDialog(QDialog):
    """Persistent web-style workspace for manually asking AI a question."""

    question_submitted = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._messages: list[ChatMessage] = []
        self.setObjectName("aiChatDialog")
        self.setWindowTitle("AI 问答")
        self.resize(880, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel("AI 家长问题分析")
        title.setObjectName("chatTitle")
        layout.addWidget(title)

        self._status = QLabel(
            "AI API 暂未接入；发送的问题会进入待分析流程。"
        )
        self._status.setObjectName("chatStatus")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._history = QListWidget()
        self._history.setObjectName("chatHistory")
        self._history.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._history.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._history.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._history.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._history.setSpacing(0)
        layout.addWidget(self._history, 1)

        composer = QFrame()
        composer.setObjectName("chatComposer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(12, 10, 12, 10)
        composer_layout.setSpacing(8)

        self._input = _ChatInput()
        self._input.setObjectName("chatInput")
        self._input.setPlaceholderText("输入家长的问题…")
        self._input.setMaximumHeight(120)
        self._input.submit_requested.connect(self.send_question)
        composer_layout.addWidget(self._input)

        actions = QHBoxLayout()
        shortcut_hint = QLabel("Enter 发送 · Shift+Enter 换行")
        shortcut_hint.setObjectName("shortcutHint")
        actions.addWidget(shortcut_hint)
        actions.addStretch()
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.hide)
        actions.addWidget(close_button)
        self._send_button = QPushButton("发送")
        self._send_button.setObjectName("sendQuestion")
        self._send_button.clicked.connect(self.send_question)
        actions.addWidget(self._send_button)
        composer_layout.addLayout(actions)
        layout.addWidget(composer)

        self.setStyleSheet(
            """
            QDialog#aiChatDialog {
                background: #ffffff;
                color: #202123;
            }
            QLabel#chatTitle {
                font-size: 18px;
                font-weight: 600;
                color: #202123;
            }
            QLabel#chatStatus,
            QLabel#shortcutHint {
                color: #6b7280;
            }
            QListWidget#chatHistory {
                background: #ffffff;
                border: 1px solid #d9dde5;
                outline: 0;
            }
            QListWidget#chatHistory::item,
            QListWidget#chatHistory::item:selected {
                background: transparent;
                border: 0;
                padding: 0;
            }
            QWidget#questionTurn {
                background: #eef4ff;
                border-bottom: 1px solid #dfe6f2;
            }
            QWidget#assistantTurn {
                background: #f7f7f8;
                border-bottom: 1px solid #e5e5e7;
            }
            QLabel#turnRole {
                color: #202123;
                font-weight: 600;
            }
            QLabel#turnBody {
                color: #2d3139;
                font-size: 14px;
            }
            QFrame#chatComposer {
                background: #ffffff;
                border: 1px solid #cbd1dc;
                border-radius: 10px;
            }
            QPlainTextEdit#chatInput {
                background: #ffffff;
                border: 0;
                padding: 2px;
                selection-background-color: #b8ccff;
            }
            QPushButton#sendQuestion {
                color: white;
                background: #356ae6;
                border: 0;
                border-radius: 6px;
                padding: 7px 20px;
            }
            QPushButton#sendQuestion:hover {
                background: #477af0;
            }
            """
        )

    @property
    def messages(self) -> tuple[ChatMessage, ...]:
        return tuple(self._messages)

    @property
    def status_text(self) -> str:
        return self._status.text()

    @Slot()
    def send_question(self) -> bool:
        text = self._input.toPlainText().strip()
        if not text:
            return False
        self._append_message(ChatRole.QUESTION, text)
        self._input.clear()
        self._status.setText("问题已提交，等待 AI 回复。")
        self.question_submitted.emit(text)
        return True

    @Slot(str)
    def append_ai_response(self, text: str) -> bool:
        response = text.strip()
        if not response:
            return False
        self._append_message(ChatRole.ASSISTANT, response)
        self._status.setText("AI 已回复，可继续追问。")
        return True

    def _append_message(self, role: ChatRole, text: str) -> None:
        self._messages.append(ChatMessage(role, text))
        turn = _ConversationTurn(role, text)

        item = QListWidgetItem()
        item.setSizeHint(turn.sizeHint())
        self._history.addItem(item)
        self._history.setItemWidget(item, turn)
        self._history.scrollToBottom()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        self._history.scrollToBottom()
