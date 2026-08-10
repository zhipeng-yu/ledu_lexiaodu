from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QInputMethodEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

@dataclass(frozen=True, slots=True)
class ChatConversationView:
    id: str
    title: str
    subtitle: str = ""


@dataclass(frozen=True, slots=True)
class ChatTurnView:
    id: str
    role: str
    text: str
    request_id: str | None = None
    status: str = "complete"
    kind: str = "message"


class _Composer(QPlainTextEdit):
    submit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._placeholder_before_composition: str | None = None

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        if event.preeditString() and self._placeholder_before_composition is None:
            self._placeholder_before_composition = self.placeholderText()
            self.setPlaceholderText("")
        super().inputMethodEvent(event)
        if (
            not event.preeditString()
            and self._placeholder_before_composition is not None
        ):
            self.setPlaceholderText(self._placeholder_before_composition)
            self._placeholder_before_composition = None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        has_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if is_enter and not has_shift:
            event.accept()
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)


class _ConversationItem(QWidget):
    def __init__(self, conversation: ChatConversationView) -> None:
        super().__init__()
        self.setObjectName("conversationItem")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)

        title = QLabel(conversation.title)
        title.setObjectName("conversationTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(False)
        layout.addWidget(title)

        if conversation.subtitle:
            subtitle = QLabel(conversation.subtitle)
            subtitle.setObjectName("conversationSubtitle")
            subtitle.setTextFormat(Qt.TextFormat.PlainText)
            subtitle.setWordWrap(False)
            layout.addWidget(subtitle)


class _TimelineTurn(QFrame):
    retry_requested = Signal(str)

    def __init__(self, turn: ChatTurnView) -> None:
        super().__init__()
        self.setObjectName(
            "toolActivity"
            if turn.kind == "tool"
            else ("userTurn" if turn.role == "user" else "assistantTurn")
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 13, 18, 14)
        layout.setSpacing(7)

        if turn.kind == "tool":
            role_text = "本地工具"
        elif turn.role == "user":
            role_text = "顾问"
        else:
            role_text = "乐小读"
        role = QLabel(role_text)
        role.setObjectName("turnRole")
        layout.addWidget(role)

        body = QLabel(turn.text)
        body.setObjectName("turnBody")
        body.setTextFormat(Qt.TextFormat.PlainText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(body)

        if turn.status in {"failed", "interrupted"} and turn.request_id:
            retry_row = QHBoxLayout()
            status = QLabel(
                "生成未完成，可以从原问题重试"
                if turn.status == "interrupted"
                else "生成失败，可以重试"
            )
            status.setObjectName("requestStatus")
            retry_row.addWidget(status)
            retry_row.addStretch()
            retry = QPushButton("重试")
            retry.setObjectName("retryRequest")
            retry.setProperty("requestId", turn.request_id)
            retry.clicked.connect(
                lambda checked=False, request_id=turn.request_id: (
                    self.retry_requested.emit(request_id)
                )
            )
            retry_row.addWidget(retry)
            layout.addLayout(retry_row)


class ChatMainWindow(QMainWindow):
    """Presentation-only shell for the independent advisor chat."""

    create_conversation_requested = Signal()
    conversation_selected = Signal(str)
    rename_conversation_requested = Signal(str)
    delete_conversation_requested = Signal(str)
    search_requested = Signal(str)
    send_requested = Signal(str)
    retry_requested = Signal(str)
    close_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._active_conversation_id: str | None = None
        self.setObjectName("chatMainWindow")
        self.setWindowTitle("乐小读 · 家长沟通顾问")
        self.resize(1180, 760)

        root = QWidget()
        root.setObjectName("chatWorkspace")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())
        root_layout.addWidget(self._build_chat_region(), 1)

        self.setStyleSheet(
            """
            QMainWindow#chatMainWindow, QWidget#chatWorkspace {
                background: #f5f3ed;
                color: #24312f;
            }
            QFrame#sidebarPanel {
                background: #223835;
                border: 0;
            }
            QLabel#workspaceEyebrow, QLabel#sidebarCaption {
                color: #b8c8c2;
                font-weight: 600;
            }
            QLabel#workspaceTitle {
                color: #f7f3e8;
                font-weight: 700;
            }
            QLineEdit#conversationSearch {
                background: #f8f6ef;
                color: #24312f;
                border: 1px solid #80918c;
                border-radius: 6px;
                padding: 7px 9px;
            }
            QListWidget#conversationSidebar {
                background: transparent;
                border: 0;
                outline: 0;
            }
            QListWidget#conversationSidebar::item {
                border-bottom: 1px solid #38504c;
            }
            QListWidget#conversationSidebar::item:selected {
                background: #31534d;
                border-left: 3px solid #d2a85d;
            }
            QLabel#conversationTitle { color: #f7f3e8; font-weight: 600; }
            QLabel#conversationSubtitle { color: #b8c8c2; }
            QPushButton#newConversation {
                background: #d2a85d;
                color: #1d2e2b;
                border: 0;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 700;
            }
            QPushButton#renameConversation, QPushButton#deleteConversation {
                background: transparent;
                color: #dce6e2;
                border: 1px solid #60756f;
                border-radius: 5px;
                padding: 6px 9px;
            }
            QFrame#chatHeader, QFrame#composerPanel {
                background: #fbfaf6;
                border-bottom: 1px solid #ddd8cc;
            }
            QLabel#chatHeading { color: #24312f; font-weight: 700; }
            QLabel#chatSubheading, QLabel#composerHint, QLabel#requestStatus {
                color: #6d7672;
            }
            QListWidget#messageTimeline {
                background: #f5f3ed;
                border: 0;
                outline: 0;
            }
            QListWidget#messageTimeline::item,
            QListWidget#messageTimeline::item:selected {
                background: transparent;
                border: 0;
                padding: 0;
            }
            QFrame#userTurn {
                background: #e7eeeb;
                border-bottom: 1px solid #d5dfdb;
            }
            QFrame#assistantTurn {
                background: #fbfaf6;
                border-bottom: 1px solid #e4dfd4;
            }
            QFrame#toolActivity {
                background: #f0ede4;
                border-left: 3px solid #b59358;
            }
            QLabel#turnRole { color: #46615b; font-weight: 700; }
            QLabel#turnBody { color: #273330; }
            QPlainTextEdit#chatComposer {
                background: #ffffff;
                color: #24312f;
                border: 1px solid #b7b9b0;
                border-radius: 7px;
                padding: 9px;
                selection-background-color: #8faea6;
            }
            QPushButton#sendMessage {
                background: #315f57;
                color: #ffffff;
                border: 0;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 700;
            }
            QPushButton#retryRequest {
                background: #ffffff;
                color: #31534d;
                border: 1px solid #aeb9b5;
                border-radius: 5px;
                padding: 7px 10px;
            }
            """
        )

    @property
    def active_conversation_id(self) -> str | None:
        return self._active_conversation_id

    def closeEvent(self, event: QCloseEvent) -> None:
        self.close_requested.emit()
        super().closeEvent(event)

    def _build_sidebar(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("sidebarPanel")
        panel.setMinimumWidth(236)
        panel.setMaximumWidth(310)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(10)

        eyebrow = QLabel("独立会话工作台")
        eyebrow.setObjectName("workspaceEyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("家长沟通顾问")
        title.setObjectName("workspaceTitle")
        layout.addWidget(title)

        create = QPushButton("＋ 新建会话")
        create.setObjectName("newConversation")
        create.clicked.connect(self.create_conversation_requested.emit)
        layout.addWidget(create)

        search = QLineEdit()
        search.setObjectName("conversationSearch")
        search.setPlaceholderText("搜索本地会话")
        search.setClearButtonEnabled(True)
        search.textChanged.connect(self.search_requested.emit)
        layout.addWidget(search)

        caption = QLabel("最近会话")
        caption.setObjectName("sidebarCaption")
        layout.addWidget(caption)

        self._conversations = QListWidget()
        self._conversations.setObjectName("conversationSidebar")
        self._conversations.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._conversations.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._conversations.currentItemChanged.connect(
            self._on_conversation_selected
        )
        layout.addWidget(self._conversations, 1)

        actions = QHBoxLayout()
        rename = QPushButton("重命名")
        rename.setObjectName("renameConversation")
        rename.clicked.connect(self._request_rename)
        actions.addWidget(rename)
        delete = QPushButton("删除")
        delete.setObjectName("deleteConversation")
        delete.clicked.connect(self._request_delete)
        actions.addWidget(delete)
        layout.addLayout(actions)
        return panel

    def _build_chat_region(self) -> QWidget:
        region = QWidget()
        region.setObjectName("chatRegion")
        layout = QVBoxLayout(region)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("chatHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 16, 22, 15)
        headings = QVBoxLayout()
        headings.setSpacing(3)
        heading = QLabel("会话")
        heading.setObjectName("chatHeading")
        headings.addWidget(heading)
        subheading = QLabel("当前内容仅来自所选会话")
        subheading.setObjectName("chatSubheading")
        headings.addWidget(subheading)
        header_layout.addLayout(headings)
        header_layout.addStretch()
        layout.addWidget(header)

        self._timeline = QListWidget()
        self._timeline.setObjectName("messageTimeline")
        self._timeline.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._timeline.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._timeline.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._timeline.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        layout.addWidget(self._timeline, 1)

        composer_panel = QFrame()
        composer_panel.setObjectName("composerPanel")
        composer_layout = QVBoxLayout(composer_panel)
        composer_layout.setContentsMargins(18, 13, 18, 16)
        composer_layout.setSpacing(9)

        self._composer = _Composer()
        self._composer.setObjectName("chatComposer")
        self._composer.setPlaceholderText("输入家长问题或补充情况…")
        self._composer.setMinimumHeight(76)
        self._composer.setMaximumHeight(132)
        self._composer.submit_requested.connect(self.submit_composer)
        composer_layout.addWidget(self._composer)

        actions = QHBoxLayout()
        actions.setSpacing(7)
        actions.addStretch()
        hint = QLabel("Enter 发送 · Shift+Enter 换行")
        hint.setObjectName("composerHint")
        actions.addWidget(hint)
        send = QPushButton("发送")
        send.setObjectName("sendMessage")
        send.clicked.connect(self.submit_composer)
        actions.addWidget(send)
        composer_layout.addLayout(actions)
        layout.addWidget(composer_panel)
        return region

    def set_conversations(
        self, conversations: tuple[ChatConversationView, ...]
    ) -> None:
        active_id = self._active_conversation_id
        blocker = QSignalBlocker(self._conversations)
        self._conversations.clear()
        active_item: QListWidgetItem | None = None
        for conversation in conversations:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, conversation.id)
            widget = _ConversationItem(conversation)
            item.setSizeHint(widget.sizeHint())
            self._conversations.addItem(item)
            self._conversations.setItemWidget(item, widget)
            if conversation.id == active_id:
                active_item = item
        if active_item is not None:
            self._conversations.setCurrentItem(active_item)
        else:
            self._active_conversation_id = None
            self._timeline.clear()
        del blocker

    def select_conversation(self, conversation_id: str) -> bool:
        for row in range(self._conversations.count()):
            item = self._conversations.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == conversation_id:
                self._conversations.setCurrentItem(item)
                return True
        return False

    def show_conversation(
        self,
        conversation_id: str,
        turns: tuple[ChatTurnView, ...],
    ) -> None:
        self._active_conversation_id = conversation_id
        self._timeline.clear()
        for turn in turns:
            self.append_turn(turn)

    def append_turn(self, turn: ChatTurnView) -> None:
        widget = _TimelineTurn(turn)
        widget.retry_requested.connect(self.retry_requested.emit)
        self._append_timeline_widget(widget)

    def append_tool_activity(self, text: str) -> bool:
        activity = text.strip()
        if not activity:
            return False
        self.append_turn(ChatTurnView("", "tool", activity, kind="tool"))
        return True

    @Slot()
    def submit_composer(self) -> bool:
        text = self._composer.toPlainText().strip()
        if self._active_conversation_id is None or not text:
            return False
        self._composer.clear()
        self.send_requested.emit(text)
        return True

    def _append_timeline_widget(self, widget: QWidget) -> None:
        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self._timeline.addItem(item)
        self._timeline.setItemWidget(item, widget)
        self._timeline.scrollToBottom()

    def _on_conversation_selected(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        conversation_id = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(conversation_id, str) and conversation_id:
            self._active_conversation_id = conversation_id
            self.conversation_selected.emit(conversation_id)

    def _request_rename(self) -> None:
        conversation_id = self._selected_conversation_id()
        if conversation_id:
            self.rename_conversation_requested.emit(conversation_id)

    def _request_delete(self) -> None:
        conversation_id = self._selected_conversation_id()
        if conversation_id:
            self.delete_conversation_requested.emit(conversation_id)

    def _selected_conversation_id(self) -> str | None:
        item = self._conversations.currentItem()
        if item is None:
            return None
        conversation_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(conversation_id, str) and conversation_id:
            return conversation_id
        return None
