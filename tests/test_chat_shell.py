from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
)

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


def test_single_screenshot_draft_can_send_without_text(
    tmp_path,
    monkeypatch,
) -> None:
    _application()
    path = tmp_path / "long.png"
    image = QImage(20, 400, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    assert image.save(str(path), "PNG")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(path), "PNG (*.png)"),
    )
    window = ChatMainWindow()
    window.set_conversations((ChatConversationView("c1", "截图"),))
    assert window.select_conversation("c1")
    sent = []
    window.send_image_requested.connect(lambda text, draft: sent.append((text, draft)))

    window.findChild(QPushButton, "selectScreenshot").click()
    assert window.submit_composer()

    assert sent[0][0] == ""
    assert sent[0][1].height == 400
    assert window.findChild(QLabel, "screenshotDraft").isHidden()
    window.close()


def test_screenshot_draft_can_be_replaced_or_removed(tmp_path, monkeypatch) -> None:
    _application()
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    for path, height in ((first_path, 20), (second_path, 40)):
        image = QImage(20, height, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        assert image.save(str(path), "PNG")
    selected_paths = iter((str(first_path), str(second_path)))
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (next(selected_paths), "PNG (*.png)"),
    )
    window = ChatMainWindow()
    select = window.findChild(QPushButton, "selectScreenshot")
    draft = window.findChild(QLabel, "screenshotDraft")

    select.click()
    assert not draft.isHidden()
    select.click()
    assert window._screenshot_draft.height == 40
    window.findChild(QPushButton, "removeScreenshot").click()

    assert draft.isHidden()
    assert window._screenshot_draft is None
    window.close()


def test_screenshot_draft_is_discarded_when_conversation_changes_or_is_unset(
    tmp_path,
    monkeypatch,
) -> None:
    _application()
    path = tmp_path / "private.png"
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    assert image.save(str(path), "PNG")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(path), "PNG (*.png)"),
    )
    first = ChatConversationView("a", "A")
    second = ChatConversationView("b", "B")
    window = ChatMainWindow()
    window.set_conversations((first, second))
    assert window.select_conversation(first.id)
    window.findChild(QPushButton, "selectScreenshot").click()
    sent_text: list[str] = []
    sent_images: list[tuple[str, object]] = []
    window.send_requested.connect(sent_text.append)
    window.send_image_requested.connect(
        lambda text, draft: sent_images.append((text, draft))
    )

    assert window.select_conversation(second.id)
    window.findChild(QPlainTextEdit, "chatComposer").setPlainText("B message")
    assert window.submit_composer()

    assert sent_text == ["B message"]
    assert sent_images == []
    assert window._screenshot_draft is None

    window.findChild(QPushButton, "selectScreenshot").click()
    assert window._screenshot_draft is not None
    window.set_conversations((first,))

    assert window.active_conversation_id is None
    assert window._screenshot_draft is None
    window.close()


def test_invalid_screenshot_file_is_rejected_without_emitting(tmp_path, monkeypatch) -> None:
    _application()
    path = tmp_path / "not-an-image.png"
    path.write_bytes(b"not an image")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(path), "All files (*)"),
    )
    window = ChatMainWindow()
    sent = []
    window.send_image_requested.connect(lambda text, draft: sent.append((text, draft)))

    window.findChild(QPushButton, "selectScreenshot").click()

    assert window._screenshot_draft is None
    assert sent == []
    assert window.findChild(QLabel, "screenshotDraft").isHidden()
    window.close()


def test_timeline_turn_renders_a_bounded_image_thumbnail() -> None:
    _application()
    image = QImage(20, 400, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    window = ChatMainWindow()

    window.show_conversation(
        "c1",
        (ChatTurnView("m1", "user", "", image=image),),
    )

    thumbnail = window.findChild(QLabel, "turnImage")
    assert thumbnail is not None
    assert thumbnail.pixmap().width() <= 320
    assert thumbnail.pixmap().height() <= 240
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
