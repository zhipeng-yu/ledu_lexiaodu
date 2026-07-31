import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
)

from lexiaodu.advice import AdviceSuggestion
from lexiaodu.chat import AiChatDialog, ChatMessage, ChatRole
from lexiaodu.feedback import FeedbackReason, FeedbackSubmission
from lexiaodu.knowledge import KnowledgeType, SearchResult
from lexiaodu.risk import RiskAssessment, RiskLevel, TransferStatus


def _suggestion(level: RiskLevel) -> AdviceSuggestion:
    high_risk = level is RiskLevel.HIGH
    return AdviceSuggestion(
        suggestion_id=f"{level.value}-suggestion",
        concern_summary="家长关注请假申请时间。",
        wechat_reply="您好，请提前提交请假申请。",
        facts=(
            SearchResult(
                knowledge_type=KnowledgeType.POLICY,
                document_name="请假制度.txt",
                locator="申请流程",
                evidence="请假须由监护人提前提交申请。",
                score=2.0,
            ),
        ),
        risk=RiskAssessment(
            level=level,
            warnings=("涉及投诉，必须转人工处理。" if high_risk else "请核对事实。",),
            transfer_status=(
                TransferStatus.REQUIRED
                if high_risk
                else TransferStatus.NOT_REQUIRED
            ),
        ),
    )


def test_send_parent_question_without_fabricating_ai_response() -> None:
    application = QApplication.instance() or QApplication([])
    dialog = AiChatDialog()
    chat_input = dialog.findChild(QPlainTextEdit, "chatInput")
    submitted: list[str] = []
    dialog.question_submitted.connect(submitted.append)

    assert application is not None
    assert chat_input is not None
    chat_input.setPlainText("  家长想了解请假流程\n需要哪些材料？  ")

    assert dialog.send_question()
    assert submitted == ["家长想了解请假流程\n需要哪些材料？"]
    assert dialog.messages == (
        ChatMessage(
            ChatRole.QUESTION,
            "家长想了解请假流程\n需要哪些材料？",
        ),
    )
    assert "等待 AI 回复" in dialog.status_text
    assert chat_input.toPlainText() == ""

    assert not dialog.send_question()
    assert len(dialog.messages) == 1
    dialog.close()


def test_chat_uses_single_column_plain_text_turns() -> None:
    application = QApplication.instance() or QApplication([])
    dialog = AiChatDialog()
    history = dialog.findChild(QListWidget, "chatHistory")
    assert history is not None

    dialog.show()
    assert dialog.append_ai_response("第一行\n**不解析为粗体** <b>也不是 HTML</b>")
    application.processEvents()

    turn = history.itemWidget(history.item(0))
    assert turn is not None
    assert turn.objectName() == "assistantTurn"
    role = turn.findChild(QLabel, "turnRole")
    body = turn.findChild(QLabel, "turnBody")
    assert role is not None
    assert body is not None
    assert role.text() == "AI"
    assert body.text() == "第一行\n**不解析为粗体** <b>也不是 HTML</b>"
    assert body.textFormat() is Qt.TextFormat.PlainText
    assert body.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert turn.width() == history.viewport().width()
    dialog.close()


def test_enter_sends_and_shift_enter_inserts_a_line_break() -> None:
    application = QApplication.instance() or QApplication([])
    dialog = AiChatDialog()
    chat_input = dialog.findChild(QPlainTextEdit, "chatInput")
    submitted: list[str] = []
    dialog.question_submitted.connect(submitted.append)

    assert chat_input is not None
    dialog.show()
    chat_input.setFocus()
    chat_input.setPlainText("第一行")
    chat_input.moveCursor(chat_input.textCursor().MoveOperation.End)
    QTest.keyClick(
        chat_input,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    chat_input.insertPlainText("第二行")
    assert chat_input.toPlainText() == "第一行\n第二行"

    QTest.keyClick(chat_input, Qt.Key.Key_Return)
    application.processEvents()
    assert submitted == ["第一行\n第二行"]
    assert chat_input.toPlainText() == ""

    QTest.keyClick(chat_input, Qt.Key.Key_Return)
    assert submitted == ["第一行\n第二行"]
    dialog.close()


def test_chat_supports_multiple_turns_and_scrolls_to_latest() -> None:
    application = QApplication.instance() or QApplication([])
    dialog = AiChatDialog()
    chat_input = dialog.findChild(QPlainTextEdit, "chatInput")
    history = dialog.findChild(QListWidget, "chatHistory")

    assert chat_input is not None
    assert history is not None
    dialog.resize(700, 360)
    dialog.show()
    chat_input.setPlainText("第一个问题")
    assert dialog.send_question()
    assert dialog.append_ai_response("第一条 AI 回复")
    chat_input.setPlainText("继续追问")
    assert dialog.send_question()
    for index in range(12):
        assert dialog.append_ai_response(f"补充回复 {index}")
    application.processEvents()

    assert dialog.messages[:3] == (
        ChatMessage(ChatRole.QUESTION, "第一个问题"),
        ChatMessage(ChatRole.ASSISTANT, "第一条 AI 回复"),
        ChatMessage(ChatRole.QUESTION, "继续追问"),
    )
    assert history.count() == 15
    scroll_bar = history.verticalScrollBar()
    assert scroll_bar.maximum() > 0
    assert scroll_bar.value() == scroll_bar.maximum()
    assert "AI 已回复" in dialog.status_text
    dialog.close()


def test_structured_suggestion_contains_complete_editable_workspace() -> None:
    application = QApplication.instance() or QApplication([])
    dialog = AiChatDialog()
    history = dialog.findChild(QListWidget, "chatHistory")
    assert history is not None
    assert dialog.append_suggestion(_suggestion(RiskLevel.LOW))
    application.processEvents()

    card = history.itemWidget(history.item(0))
    assert card is not None
    assert card.objectName() == "suggestionTurn"
    concern = card.findChild(QLabel, "concernSummary")
    reply = card.findChild(QPlainTextEdit, "wechatReply")
    fact = card.findChild(QLabel, "factEvidence")
    risk = card.findChild(QLabel, "riskWarning")
    transfer = card.findChild(QLabel, "transferStatus")
    assert concern is not None and "请假" in concern.text()
    assert reply is not None and not reply.isReadOnly()
    assert fact is not None and "监护人" in fact.text()
    assert risk is not None and "核对" in risk.text()
    assert transfer is not None and "无需转人工" in transfer.text()
    dialog.close()


def test_copy_uses_edited_reply_and_high_risk_requires_confirmation() -> None:
    application = QApplication.instance() or QApplication([])
    dialog = AiChatDialog()
    history = dialog.findChild(QListWidget, "chatHistory")
    assert history is not None
    assert dialog.append_suggestion(_suggestion(RiskLevel.HIGH))
    application.processEvents()

    card = history.itemWidget(history.item(0))
    assert card is not None
    reply = card.findChild(QPlainTextEdit, "wechatReply")
    confirmation = card.findChild(QCheckBox, "riskConfirmation")
    copy_button = card.findChild(QPushButton, "copyReply")
    assert reply is not None
    assert confirmation is not None
    assert copy_button is not None
    reply.setPlainText("顾问编辑后的回复")

    assert confirmation.isVisibleTo(card)
    assert not copy_button.isEnabled()
    assert not card.copy_reply()
    assert QGuiApplication.clipboard().text() != "顾问编辑后的回复"

    confirmation.setChecked(True)
    assert copy_button.isEnabled()
    QTest.mouseClick(copy_button, Qt.MouseButton.LeftButton)
    assert QGuiApplication.clipboard().text() == "顾问编辑后的回复"
    dialog.close()


def test_structured_feedback_emits_reason_without_chat_text() -> None:
    application = QApplication.instance() or QApplication([])
    dialog = AiChatDialog()
    history = dialog.findChild(QListWidget, "chatHistory")
    submissions: list[FeedbackSubmission] = []
    dialog.feedback_submitted.connect(submissions.append)
    assert history is not None
    assert dialog.append_suggestion(_suggestion(RiskLevel.LOW))
    application.processEvents()

    card = history.itemWidget(history.item(0))
    assert card is not None
    useful = card.findChild(QPushButton, "feedbackUseful")
    reason = card.findChild(QComboBox, "feedbackReason")
    submit = card.findChild(QPushButton, "submitFeedback")
    assert useful is not None
    assert reason is not None
    assert submit is not None

    QTest.mouseClick(useful, Qt.MouseButton.LeftButton)
    reason.setCurrentIndex(reason.findData(FeedbackReason.CLEAR))
    QTest.mouseClick(submit, Qt.MouseButton.LeftButton)

    assert submissions == [
        FeedbackSubmission(
            suggestion_id="低风险-suggestion",
            useful=True,
            reason=FeedbackReason.CLEAR,
        )
    ]
    assert not hasattr(submissions[0], "transcript")
    assert not hasattr(submissions[0], "reply")
    dialog.close()
