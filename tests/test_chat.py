import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPlainTextEdit

from lexiaodu.chat import AiChatDialog, ChatMessage, ChatRole


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
