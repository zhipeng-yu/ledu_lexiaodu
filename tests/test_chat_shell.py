from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPlainTextEdit, QPushButton

from lexiaodu.chat_window import ChatConversationView, ChatMainWindow, ChatTurnView


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_window_uses_lexiaodu_brand_and_only_active_chat_actions() -> None:
    _application()
    window = ChatMainWindow()

    assert window.windowTitle().startswith("乐小读")
    assert window.findChild(QListWidget, "conversationSidebar") is not None
    assert window.findChild(QListWidget, "messageTimeline") is not None
    assert window.findChild(QPlainTextEdit, "chatComposer") is not None
    assert window.findChild(QPushButton, "sendMessage") is not None
    for removed_name in (
        "captureScreenshot",
        "pasteScreenshot",
        "generateReply",
        "openContextDrawer",
    ):
        assert window.findChild(QPushButton, removed_name) is None
    window.close()


def test_composer_sends_only_with_an_active_conversation() -> None:
    _application()
    window = ChatMainWindow()
    sent: list[str] = []
    window.send_requested.connect(sent.append)
    composer = window.findChild(QPlainTextEdit, "chatComposer")
    assert composer is not None
    composer.setPlainText("没有会话")
    assert not window.submit_composer()
    window.set_conversations((ChatConversationView("c1", "咨询"),))
    assert window.select_conversation("c1")
    composer.setPlainText("顾问的问题")

    QTest.keyClick(composer, Qt.Key.Key_Return)

    assert sent == ["顾问的问题"]
    assert composer.toPlainText() == ""
    window.close()


def test_show_conversation_uses_consultant_and_lexiaodu_role_labels() -> None:
    _application()
    window = ChatMainWindow()
    window.show_conversation(
        "c1",
        (
            ChatTurnView("m1", "user", "问题"),
            ChatTurnView("m2", "assistant", "回答"),
        ),
    )

    labels = {
        label.text()
        for label in window.findChildren(QLabel, "turnRole")
    }
    assert labels == {"顾问", "乐小读"}
    window.close()


def test_removing_active_conversation_clears_timeline_and_owner() -> None:
    _application()
    window = ChatMainWindow()
    window.set_conversations((ChatConversationView("c1", "咨询"),))
    window.select_conversation("c1")
    window.show_conversation("c1", (ChatTurnView("m1", "user", "私密内容"),))

    window.set_conversations(())

    timeline = window.findChild(QListWidget, "messageTimeline")
    assert timeline is not None
    assert timeline.count() == 0
    assert window.active_conversation_id is None
    window.close()
