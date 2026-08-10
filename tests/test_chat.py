import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QPlainTextEdit,
    QPushButton,
)

from lexiaodu.advice import AdviceSuggestion
from lexiaodu.chat import SuggestionCard
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


def test_suggestion_card_keeps_component_styles() -> None:
    application = QApplication.instance() or QApplication([])
    card = SuggestionCard(_suggestion(RiskLevel.LOW))
    card.show()
    application.processEvents()

    badge = card.findChild(QLabel, "riskBadge")
    warning = card.findChild(QLabel, "riskWarning")
    copy_button = card.findChild(QPushButton, "copyReply")
    assert badge is not None
    assert warning is not None
    assert copy_button is not None
    assert badge.palette().color(QPalette.ColorRole.WindowText) == QColor(
        "#2f5f45"
    )
    assert warning.palette().color(QPalette.ColorRole.WindowText) == QColor(
        "#6b5a2c"
    )
    assert copy_button.palette().color(
        QPalette.ColorRole.ButtonText
    ) == QColor("#ffffff")
    card.close()


def test_copy_uses_edited_reply_and_high_risk_requires_confirmation() -> None:
    application = QApplication.instance() or QApplication([])
    card = SuggestionCard(_suggestion(RiskLevel.HIGH))
    card.show()
    application.processEvents()
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
    QTest.mouseClick(copy_button, Qt.MouseButton.LeftButton)
    assert QGuiApplication.clipboard().text() == "顾问编辑后的回复"
    card.close()


def test_structured_feedback_emits_reason_without_chat_text() -> None:
    application = QApplication.instance() or QApplication([])
    card = SuggestionCard(_suggestion(RiskLevel.LOW))
    submissions: list[FeedbackSubmission] = []
    card.feedback_submitted.connect(submissions.append)
    card.show()
    application.processEvents()

    useful = card.findChild(QPushButton, "feedbackUseful")
    reason = card.findChild(QComboBox, "feedbackReason")
    submit = card.findChild(QPushButton, "submitFeedback")
    feedback = card.findChild(QFrame, "feedbackPanel")
    assert useful is not None
    assert reason is not None
    assert submit is not None
    assert feedback is not None

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
    card.close()
