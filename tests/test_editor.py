import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
)

from lexiaodu.editor import TranscriptEditor
from lexiaodu.ocr import Speaker, TranscriptLine


def test_edit_ocr_text_and_speaker() -> None:
    application = QApplication.instance() or QApplication([])
    editor = TranscriptEditor(
        [TranscriptLine(speaker=Speaker.PARENT, text="原文字")]
    )
    table = editor.findChild(QTableWidget, "transcriptTable")
    speaker = editor.findChild(QComboBox, "speaker-0")

    assert application is not None
    assert table is not None
    assert speaker is not None
    table.item(0, 1).setText("校正后的文字")
    speaker.setCurrentText(Speaker.ADVISOR.value)

    transcript = editor.transcript()
    assert transcript == [
        TranscriptLine(speaker=Speaker.ADVISOR, text="校正后的文字")
    ]
    assert transcript[0].speaker is Speaker.ADVISOR
    editor.close()


def test_manual_paste_adds_fallback_line() -> None:
    application = QApplication.instance() or QApplication([])
    editor = TranscriptEditor(notice="OCR 不可用")
    manual = editor.findChild(QPlainTextEdit, "manualText")

    assert application is not None
    assert manual is not None
    manual.setPlainText("  手动粘贴的聊天文字  ")

    assert editor.add_manual_text(Speaker.PARENT)
    assert editor.transcript() == [
        TranscriptLine(speaker=Speaker.PARENT, text="手动粘贴的聊天文字")
    ]
    assert manual.toPlainText() == ""
    editor.close()


def test_ocr_editor_requires_explicit_confirmation_to_generate() -> None:
    application = QApplication.instance() or QApplication([])
    editor = TranscriptEditor(
        [TranscriptLine(speaker=Speaker.PARENT, text="识别文字")]
    )
    confirm = editor.findChild(QPushButton, "confirmTranscript")
    accepted: list[bool] = []
    editor.accepted.connect(lambda: accepted.append(True))

    assert application is not None
    assert confirm is not None
    assert confirm.text() == "确认无误并生成建议"
    assert accepted == []

    confirm.click()
    assert accepted == [True]
    editor.close()
