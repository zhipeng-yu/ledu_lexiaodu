import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
)

from lexiaodu.advice import AdviceSuggestion
from lexiaodu.chat import SuggestionCard
from lexiaodu.chat_window import (
    ChatConversationView,
    ChatMainWindow,
    ChatTurnView,
)
from lexiaodu.knowledge import KnowledgeType, SearchResult
from lexiaodu.risk import RiskAssessment, RiskLevel, TransferStatus


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _suggestion() -> AdviceSuggestion:
    return AdviceSuggestion(
        suggestion_id="formal-reply",
        concern_summary="家长担心请假流程。",
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
            level=RiskLevel.LOW,
            warnings=("请核对事实。",),
            transfer_status=TransferStatus.NOT_REQUIRED,
        ),
    )


def test_window_exposes_chat_first_shell_with_closed_context_drawer() -> None:
    application = _application()
    window = ChatMainWindow()

    assert isinstance(window, QMainWindow)
    assert window.findChild(QListWidget, "conversationSidebar") is not None
    assert window.findChild(QListWidget, "messageTimeline") is not None
    assert window.findChild(QPlainTextEdit, "chatComposer") is not None
    assert window.findChild(QPushButton, "captureScreenshot") is not None
    assert window.findChild(QPushButton, "sendMessage") is not None
    drawer = window.findChild(QFrame, "contextDrawer")
    assert drawer is not None
    assert drawer.isHidden()
    assert application is not None
    window.close()


def test_conversation_selection_uses_item_ids_and_replaces_visible_turns() -> None:
    application = _application()
    window = ChatMainWindow()
    sidebar = window.findChild(QListWidget, "conversationSidebar")
    timeline = window.findChild(QListWidget, "messageTimeline")
    selected: list[str] = []
    window.conversation_selected.connect(selected.append)
    assert sidebar is not None
    assert timeline is not None

    window.set_conversations(
        (
            ChatConversationView("conversation-a", "同名家长咨询"),
            ChatConversationView("conversation-b", "同名家长咨询"),
        )
    )
    sidebar.setCurrentRow(0)
    assert selected == ["conversation-a"]
    window.show_conversation(
        "conversation-a",
        (ChatTurnView("turn-a", "user", "FIRST-THREAD"),),
    )
    assert timeline.count() == 1

    sidebar.setCurrentRow(1)
    assert selected == ["conversation-a", "conversation-b"]
    window.show_conversation(
        "conversation-b",
        (ChatTurnView("turn-b", "assistant", "SECOND-THREAD"),),
    )

    assert timeline.count() == 1
    turn = timeline.itemWidget(timeline.item(0))
    assert turn is not None
    body = turn.findChild(QLabel, "turnBody")
    assert body is not None
    assert body.text() == "SECOND-THREAD"
    assert "FIRST-THREAD" not in body.text()
    assert application is not None
    window.close()


def test_enter_sends_and_shift_enter_inserts_a_line_break() -> None:
    application = _application()
    window = ChatMainWindow()
    composer = window.findChild(QPlainTextEdit, "chatComposer")
    submitted: list[str] = []
    window.send_requested.connect(submitted.append)
    assert composer is not None

    window.show()
    composer.setFocus()
    composer.setPlainText("第一行")
    composer.moveCursor(composer.textCursor().MoveOperation.End)
    QTest.keyClick(
        composer,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    composer.insertPlainText("第二行")
    assert composer.toPlainText() == "第一行\n第二行"

    QTest.keyClick(composer, Qt.Key.Key_Return)
    application.processEvents()
    assert submitted == ["第一行\n第二行"]
    assert composer.toPlainText() == ""
    window.close()


def test_retry_emits_the_original_request_id() -> None:
    application = _application()
    window = ChatMainWindow()
    timeline = window.findChild(QListWidget, "messageTimeline")
    retried: list[str] = []
    window.retry_requested.connect(retried.append)
    assert timeline is not None

    window.show_conversation(
        "conversation-a",
        (
            ChatTurnView(
                "turn-a",
                "user",
                "需要重试的问题",
                request_id="original-request-id",
                status="failed",
            ),
        ),
    )
    turn = timeline.itemWidget(timeline.item(0))
    assert turn is not None
    retry = turn.findChild(QPushButton, "retryRequest")
    assert retry is not None

    QTest.mouseClick(retry, Qt.MouseButton.LeftButton)
    assert retried == ["original-request-id"]
    assert application is not None
    window.close()


def test_workspace_actions_emit_the_selected_id_and_search_text() -> None:
    application = _application()
    window = ChatMainWindow()
    sidebar = window.findChild(QListWidget, "conversationSidebar")
    search = window.findChild(QLineEdit, "conversationSearch")
    created: list[bool] = []
    renamed: list[str] = []
    deleted: list[str] = []
    searched: list[str] = []
    captured: list[bool] = []
    pasted: list[bool] = []
    generated: list[str] = []
    drawers: list[str] = []
    window.create_conversation_requested.connect(lambda: created.append(True))
    window.rename_conversation_requested.connect(renamed.append)
    window.delete_conversation_requested.connect(deleted.append)
    window.search_requested.connect(searched.append)
    window.capture_requested.connect(lambda: captured.append(True))
    window.paste_requested.connect(lambda: pasted.append(True))
    window.generate_reply_requested.connect(generated.append)
    window.open_drawer_requested.connect(drawers.append)
    assert sidebar is not None
    assert search is not None

    window.set_conversations(
        (ChatConversationView("stored-id", "标题不是身份"),)
    )
    sidebar.setCurrentRow(0)
    search.setText("英语开口")
    for object_name in (
        "newConversation",
        "renameConversation",
        "deleteConversation",
        "captureScreenshot",
        "pasteScreenshot",
        "generateReply",
        "openContextDrawer",
    ):
        button = window.findChild(QPushButton, object_name)
        assert button is not None
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    assert created == [True]
    assert renamed == ["stored-id"]
    assert deleted == ["stored-id"]
    assert searched == ["英语开口"]
    assert captured == [True]
    assert pasted == [True]
    assert generated == ["stored-id"]
    assert drawers == ["stored-id"]
    assert application is not None
    window.close()


def test_replacing_sidebar_cannot_emit_actions_for_a_stale_conversation() -> None:
    application = _application()
    window = ChatMainWindow()
    sidebar = window.findChild(QListWidget, "conversationSidebar")
    renamed: list[str] = []
    deleted: list[str] = []
    window.rename_conversation_requested.connect(renamed.append)
    window.delete_conversation_requested.connect(deleted.append)
    assert sidebar is not None

    window.set_conversations((ChatConversationView("a", "会话 A"),))
    sidebar.setCurrentRow(0)
    assert window.active_conversation_id == "a"

    window.set_conversations((ChatConversationView("b", "会话 B"),))
    assert sidebar.currentItem() is None
    for object_name in ("renameConversation", "deleteConversation"):
        button = window.findChild(QPushButton, object_name)
        assert button is not None
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert renamed == []
    assert deleted == []

    sidebar.setCurrentRow(0)
    for object_name in ("renameConversation", "deleteConversation"):
        button = window.findChild(QPushButton, object_name)
        assert button is not None
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert renamed == ["b"]
    assert deleted == ["b"]
    assert application is not None
    window.close()


def test_formal_reply_card_appears_only_when_explicitly_appended() -> None:
    application = _application()
    window = ChatMainWindow()
    timeline = window.findChild(QListWidget, "messageTimeline")
    assert timeline is not None

    window.show_conversation(
        "conversation-a",
        (
            ChatTurnView(
                "turn-a",
                "assistant",
                "普通分析，不是正式回复卡。",
            ),
        ),
    )
    assert timeline.findChild(SuggestionCard) is None

    assert window.append_suggestion(_suggestion())
    assert timeline.count() == 2
    assert timeline.findChild(SuggestionCard) is not None
    assert application is not None
    window.close()
