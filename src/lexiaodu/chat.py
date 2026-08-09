from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QEvent, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QInputMethodEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
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

from lexiaodu.advice import AdviceSuggestion
from lexiaodu.feedback import (
    FeedbackReason,
    FeedbackSubmission,
    UNHELPFUL_REASONS,
    USEFUL_REASONS,
)
from lexiaodu.font_scaling import scaled_point_size


class ChatRole(StrEnum):
    QUESTION = "家长问题"
    ASSISTANT = "AI"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatRole
    text: str


class _ChatInput(QPlainTextEdit):
    submit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._placeholder_before_composition: str | None = None

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        if event.preeditString() and self._placeholder_before_composition is None:
            self._placeholder_before_composition = self.placeholderText()
            self.setPlaceholderText("")

        super().inputMethodEvent(event)

        if not event.preeditString() and self._placeholder_before_composition is not None:
            self.setPlaceholderText(self._placeholder_before_composition)
            self._placeholder_before_composition = None

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


class SuggestionCard(QWidget):
    feedback_submitted = Signal(object)

    def __init__(self, suggestion: AdviceSuggestion) -> None:
        super().__init__()
        self._suggestion = suggestion
        self._feedback_value: bool | None = None
        self.setObjectName("suggestionTurn")
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
        content.setObjectName("suggestionContent")
        content.setMaximumWidth(760)
        content.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 20, 0, 22)
        content_layout.setSpacing(10)

        heading = QHBoxLayout()
        role_label = QLabel("AI 建议")
        role_label.setObjectName("turnRole")
        heading.addWidget(role_label)
        heading.addStretch()
        risk_badge = QLabel(suggestion.risk.level.value)
        risk_badge.setObjectName(
            "highRiskBadge"
            if suggestion.risk.requires_copy_confirmation
            else "riskBadge"
        )
        heading.addWidget(risk_badge)
        content_layout.addLayout(heading)

        content_layout.addWidget(self._section_title("顾虑摘要"))
        concern = QLabel(suggestion.concern_summary)
        concern.setObjectName("concernSummary")
        concern.setTextFormat(Qt.TextFormat.PlainText)
        concern.setWordWrap(True)
        content_layout.addWidget(concern)

        content_layout.addWidget(self._section_title("可编辑微信短回复"))
        self._reply = QPlainTextEdit(suggestion.wechat_reply)
        self._reply.setObjectName("wechatReply")
        self._reply.setMinimumHeight(104)
        self._reply.setMaximumHeight(168)
        content_layout.addWidget(self._reply)

        content_layout.addWidget(self._section_title("事实依据"))
        if suggestion.facts:
            for fact in suggestion.facts:
                evidence = QFrame()
                evidence.setObjectName("factEvidenceCard")
                evidence_layout = QVBoxLayout(evidence)
                evidence_layout.setContentsMargins(10, 8, 10, 9)
                evidence_layout.setSpacing(4)
                source = QLabel(f"{fact.document_name} · {fact.locator}")
                source.setObjectName("factSource")
                evidence_layout.addWidget(source)
                fact_text = QLabel(fact.evidence)
                fact_text.setObjectName("factEvidence")
                fact_text.setTextFormat(Qt.TextFormat.PlainText)
                fact_text.setWordWrap(True)
                fact_text.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                evidence_layout.addWidget(fact_text)
                content_layout.addWidget(evidence)
        else:
            missing_evidence = QLabel("未检索到权威事实依据。")
            missing_evidence.setObjectName("missingEvidence")
            content_layout.addWidget(missing_evidence)

        content_layout.addWidget(self._section_title("风险提示"))
        risk_text = QLabel("\n".join(suggestion.risk.warnings))
        risk_text.setObjectName(
            "highRiskWarning"
            if suggestion.risk.requires_copy_confirmation
            else "riskWarning"
        )
        risk_text.setTextFormat(Qt.TextFormat.PlainText)
        risk_text.setWordWrap(True)
        content_layout.addWidget(risk_text)

        transfer = QLabel(f"转人工状态：{suggestion.risk.transfer_status.value}")
        transfer.setObjectName("transferStatus")
        content_layout.addWidget(transfer)

        self._confirmation = QCheckBox("我已阅读风险提示，确认复制高风险回复")
        self._confirmation.setObjectName("riskConfirmation")
        self._confirmation.setVisible(
            suggestion.risk.requires_copy_confirmation
        )
        content_layout.addWidget(self._confirmation)

        copy_row = QHBoxLayout()
        self._copy_status = QLabel("")
        self._copy_status.setObjectName("copyStatus")
        copy_row.addWidget(self._copy_status)
        copy_row.addStretch()
        self._copy_button = QPushButton("复制微信回复")
        self._copy_button.setObjectName("copyReply")
        self._copy_button.setEnabled(
            not suggestion.risk.requires_copy_confirmation
        )
        self._copy_button.clicked.connect(self.copy_reply)
        self._confirmation.toggled.connect(self._copy_button.setEnabled)
        copy_row.addWidget(self._copy_button)
        content_layout.addLayout(copy_row)

        feedback_frame = QFrame()
        feedback_frame.setObjectName("feedbackPanel")
        feedback_layout = QHBoxLayout(feedback_frame)
        feedback_layout.setContentsMargins(10, 8, 10, 8)
        feedback_layout.setSpacing(8)
        feedback_layout.addWidget(QLabel("这条建议"))
        self._useful_button = QPushButton("有用")
        self._useful_button.setObjectName("feedbackUseful")
        self._useful_button.setCheckable(True)
        feedback_layout.addWidget(self._useful_button)
        self._unhelpful_button = QPushButton("无用")
        self._unhelpful_button.setObjectName("feedbackUnhelpful")
        self._unhelpful_button.setCheckable(True)
        feedback_layout.addWidget(self._unhelpful_button)
        self._feedback_group = QButtonGroup(self)
        self._feedback_group.setExclusive(True)
        self._feedback_group.addButton(self._useful_button)
        self._feedback_group.addButton(self._unhelpful_button)
        self._useful_button.clicked.connect(
            lambda: self._select_feedback(True)
        )
        self._unhelpful_button.clicked.connect(
            lambda: self._select_feedback(False)
        )

        self._reason = QComboBox()
        self._reason.setObjectName("feedbackReason")
        self._reason.setEnabled(False)
        self._reason.setMinimumWidth(132)
        feedback_layout.addWidget(self._reason)
        self._feedback_button = QPushButton("提交反馈")
        self._feedback_button.setObjectName("submitFeedback")
        self._feedback_button.setEnabled(False)
        self._feedback_button.clicked.connect(self.submit_feedback)
        feedback_layout.addWidget(self._feedback_button)
        self._feedback_status = QLabel("")
        self._feedback_status.setObjectName("feedbackStatus")
        feedback_layout.addWidget(self._feedback_status)
        feedback_layout.addStretch()
        content_layout.addWidget(feedback_frame)

        row_layout.addWidget(content, 8)
        row_layout.addStretch(1)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    @Slot()
    def copy_reply(self) -> bool:
        if (
            self._suggestion.risk.requires_copy_confirmation
            and not self._confirmation.isChecked()
        ):
            return False
        QGuiApplication.clipboard().setText(self._reply.toPlainText())
        self._copy_status.setText("已复制")
        return True

    def _select_feedback(self, useful: bool) -> None:
        self._feedback_value = useful
        reasons = USEFUL_REASONS if useful else UNHELPFUL_REASONS
        self._reason.clear()
        for reason in reasons:
            self._reason.addItem(reason.value, reason)
        self._reason.setEnabled(True)
        self._feedback_button.setEnabled(True)

    @Slot()
    def submit_feedback(self) -> bool:
        raw_reason = self._reason.currentData()
        try:
            reason = FeedbackReason(raw_reason)
        except (TypeError, ValueError):
            return False
        if self._feedback_value is None:
            return False
        self.feedback_submitted.emit(
            FeedbackSubmission(
                suggestion_id=self._suggestion.suggestion_id,
                useful=self._feedback_value,
                reason=reason,
            )
        )
        for widget in (
            self._useful_button,
            self._unhelpful_button,
            self._reason,
            self._feedback_button,
        ):
            widget.setEnabled(False)
        self._feedback_status.setText("已记录")
        return True


_SuggestionCard = SuggestionCard


class AiChatDialog(QDialog):
    """Persistent web-style workspace for manually asking AI a question."""

    question_submitted = Signal(str)
    feedback_submitted = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._messages: list[ChatMessage] = []
        self._advice_mode = False
        self.setObjectName("aiChatDialog")
        self.setWindowTitle("AI 问答")
        self.resize(880, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        self._title = QLabel("AI 家长问题分析")
        self._title.setObjectName("chatTitle")
        layout.addWidget(self._title)

        self._status = QLabel(
            "本地检索与模拟生成已就绪；建议发送前请人工核对。"
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

        self._composer = QFrame()
        self._composer.setObjectName("chatComposer")
        composer_layout = QVBoxLayout(self._composer)
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
        layout.addWidget(self._composer)

        self._style_template = """
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
            QWidget#suggestionTurn {
                background: #f7f8f4;
                border-bottom: 1px solid #dfe3da;
            }
            QLabel#turnRole {
                color: #202123;
                font-weight: 600;
            }
            QLabel#turnBody {
                color: #2d3139;
                font-size: 14px;
            }
            QLabel#sectionTitle {
                color: #596152;
                font-size: 12px;
                font-weight: 600;
                margin-top: 4px;
            }
            QLabel#concernSummary {
                color: #272c25;
                font-size: 14px;
            }
            QLabel#riskBadge,
            QLabel#highRiskBadge {
                border-radius: 9px;
                padding: 3px 8px;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#riskBadge {
                color: #2f5f45;
                background: #e3efe7;
            }
            QLabel#highRiskBadge {
                color: #8c2f2f;
                background: #f9dddd;
            }
            QPlainTextEdit#wechatReply {
                background: #ffffff;
                border: 1px solid #cdd3c8;
                border-radius: 7px;
                padding: 8px;
                selection-background-color: #c6d9b9;
            }
            QFrame#factEvidenceCard {
                background: #ffffff;
                border-left: 3px solid #6f8a5e;
                border-radius: 3px;
            }
            QLabel#factSource {
                color: #53634b;
                font-weight: 600;
            }
            QLabel#factEvidence,
            QLabel#missingEvidence {
                color: #50564d;
            }
            QLabel#riskWarning {
                color: #6b5a2c;
                background: #fff7dc;
                border-radius: 5px;
                padding: 8px;
            }
            QLabel#highRiskWarning {
                color: #842b2b;
                background: #fff0f0;
                border-left: 3px solid #c04a4a;
                padding: 8px;
            }
            QLabel#transferStatus {
                color: #343a31;
                font-weight: 600;
            }
            QLabel#copyStatus,
            QLabel#feedbackStatus {
                color: #47704f;
            }
            QPushButton#copyReply {
                color: white;
                background: #315d43;
                border: 0;
                border-radius: 6px;
                padding: 7px 16px;
            }
            QPushButton#copyReply:hover { background: #3d7151; }
            QPushButton#copyReply:disabled {
                color: #999f9b;
                background: #e0e3e1;
            }
            QFrame#feedbackPanel {
                background: #edf0ea;
                border-radius: 7px;
            }
            QPushButton#feedbackUseful:checked,
            QPushButton#feedbackUnhelpful:checked {
                color: white;
                background: #5f7355;
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
        self._apply_style_sheet()

    def _apply_style_sheet(self) -> None:
        style_sheet = self._style_template
        replacements = {
            "font-size: 18px;": (
                f"font-size: {scaled_point_size(14.0):g}pt;"
            ),
            "font-size: 14px;": (
                f"font-size: {scaled_point_size(11.0):g}pt;"
            ),
            "font-size: 12px;": (
                f"font-size: {scaled_point_size(9.0):g}pt;"
            ),
        }
        for existing, scaled in replacements.items():
            style_sheet = style_sheet.replace(existing, scaled)
        self.setStyleSheet(style_sheet)

    def event(self, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.ApplicationFontChange
            and hasattr(self, "_style_template")
        ):
            self._apply_style_sheet()
        return super().event(event)

    @property
    def messages(self) -> tuple[ChatMessage, ...]:
        return tuple(self._messages)

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def is_advice_mode(self) -> bool:
        return self._advice_mode

    def set_manual_mode(self) -> None:
        self._advice_mode = False
        self.setWindowTitle("AI 问答")
        self._title.setText("AI 家长问题分析")
        self._composer.setVisible(True)

    def begin_advice_session(self, line_count: int) -> None:
        self._advice_mode = True
        self.setWindowTitle("顾问建议")
        self._title.setText("顾问建议工作台")
        self._composer.setVisible(False)
        self._status.setText(
            f"已确认 {line_count} 条 OCR 对话，正在生成后续建议…"
        )

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

    def append_parent_context(self, text: str) -> bool:
        question = text.strip()
        if not question:
            return False
        self._append_message(ChatRole.QUESTION, question)
        return True

    @Slot(object)
    def append_suggestion(self, suggestion: AdviceSuggestion) -> bool:
        if not isinstance(suggestion, AdviceSuggestion):
            return False
        self._messages.append(
            ChatMessage(ChatRole.ASSISTANT, suggestion.wechat_reply)
        )
        card = SuggestionCard(suggestion)
        card.feedback_submitted.connect(self.feedback_submitted.emit)
        self._append_turn_widget(card)
        self._status.setText("后续建议已生成，可编辑、核对并复制。")
        return True

    def set_generating(self) -> None:
        self._status.setText("正在检索本地知识并生成建议…")

    def show_generation_error(self, message: str) -> None:
        self._status.setText(f"建议生成失败：{message}")

    def _append_message(self, role: ChatRole, text: str) -> None:
        self._messages.append(ChatMessage(role, text))
        self._append_turn_widget(_ConversationTurn(role, text))

    def _append_turn_widget(self, turn: QWidget) -> None:
        item = QListWidgetItem()
        item.setSizeHint(turn.sizeHint())
        self._history.addItem(item)
        self._history.setItemWidget(item, turn)
        self._history.scrollToBottom()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        self._history.scrollToBottom()
