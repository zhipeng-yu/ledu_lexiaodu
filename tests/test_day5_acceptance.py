from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
)

from lexiaodu.advice import AdviceService
from lexiaodu.capture import CaptureResult
from lexiaodu.chat import AiChatDialog
from lexiaodu.domain import ScreenRegion
from lexiaodu.editor import TranscriptEditor
from lexiaodu.feedback import FeedbackReason, FeedbackStore
from lexiaodu.generator import SimulatedGenerator
from lexiaodu.knowledge import KnowledgeBase
from lexiaodu.ocr import Speaker, TranscriptLine
from lexiaodu.risk import DeterministicRiskRules
from lexiaodu.toolbar import FloatingToolbar
from lexiaodu.workflow import CaptureController


class _MemoryCapture:
    def __init__(self) -> None:
        self.image = QImage(800, 480, QImage.Format.Format_RGB32)

    def capture(self, region: ScreenRegion) -> CaptureResult:
        return CaptureResult(self.image, region, "acceptance-screen")


class _MemoryOcr:
    def preload(self) -> None:
        pass

    def recognize(self, image: QImage) -> list[TranscriptLine]:
        assert not image.isNull()
        return [
            TranscriptLine(
                Speaker.PARENT,
                "我要投述课程并申请退款",
                confidence=0.82,
            )
        ]


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 1500) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not predicate():
        if monotonic() >= deadline:
            raise AssertionError("等待 Day 5 端到端流程超时")
        QTest.qWait(1)


def _files_under(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def test_complete_private_advice_workflow(tmp_path: Path, caplog) -> None:
    """Exercise the full demo path without persisting screenshots or chat text."""

    caplog.set_level(logging.DEBUG)
    application = QApplication.instance() or QApplication([])
    knowledge_dir = tmp_path / "knowledge"
    policy_dir = knowledge_dir / "policy"
    style_dir = knowledge_dir / "style_case"
    policy_dir.mkdir(parents=True)
    style_dir.mkdir()
    (policy_dir / "投诉处理规则.txt").write_text(
        "# 退款与投诉处理\n"
        "家长提出退款或投诉时，顾问不得承诺处理结果，应转人工核实。",
        encoding="utf-8",
    )
    (style_dir / "安抚表达.txt").write_text(
        "# 投诉沟通\n先表达理解，再说明将转人工核实。",
        encoding="utf-8",
    )
    knowledge = KnowledgeBase(knowledge_dir, tmp_path / "knowledge.sqlite3")
    knowledge.rebuild()
    feedback_path = tmp_path / "feedback.sqlite3"
    toolbar = FloatingToolbar("乐小读", 460, 52)
    advice_dialog = AiChatDialog()
    controller = CaptureController(
        toolbar,
        _MemoryCapture(),
        _MemoryOcr(),
        editor_factory=TranscriptEditor,
        advice_factory=lambda: advice_dialog,
        advice_service=AdviceService(
            knowledge,
            SimulatedGenerator(),
            DeterministicRiskRules(),
        ),
        feedback_store=FeedbackStore(feedback_path),
    )
    sensitive_transcript = "我要投诉课程并申请退款"
    edited_reply = "顾问编辑后的敏感回复正文"

    try:
        assert application is not None
        files_before_capture = _files_under(tmp_path)
        controller.capture_region(ScreenRegion(0, 0, 800, 480))
        _wait_until(lambda: isinstance(controller._editor, TranscriptEditor))

        editor = controller._editor
        assert isinstance(editor, TranscriptEditor)
        table = editor.findChild(QTableWidget, "transcriptTable")
        manual_text = editor.findChild(QPlainTextEdit, "manualText")
        add_parent = editor.findChild(QPushButton, "addParent")
        confirm = editor.findChild(QPushButton, "confirmTranscript")
        assert table is not None
        assert manual_text is not None
        assert add_parent is not None
        assert confirm is not None

        # Correct the OCR typo, then paste a missing message into the editor.
        table.item(0, 1).setText(sensitive_transcript)
        manual_text.setPlainText("请马上给答复")
        QTest.mouseClick(add_parent, Qt.MouseButton.LeftButton)
        assert [line.text for line in editor.transcript()] == [
            sensitive_transcript,
            "请马上给答复",
        ]
        QTest.mouseClick(confirm, Qt.MouseButton.LeftButton)

        history = advice_dialog.findChild(QListWidget, "chatHistory")
        assert history is not None
        _wait_until(lambda: history.count() == 1)
        card = history.itemWidget(history.item(0))
        assert card is not None
        fact_source = card.findChild(QLabel, "factSource")
        assert fact_source is not None
        assert "投诉处理规则.txt" in fact_source.text()

        reply = card.findChild(QPlainTextEdit, "wechatReply")
        confirmation = card.findChild(QCheckBox, "riskConfirmation")
        copy_button = card.findChild(QPushButton, "copyReply")
        useful = card.findChild(QPushButton, "feedbackUseful")
        reason = card.findChild(QComboBox, "feedbackReason")
        submit = card.findChild(QPushButton, "submitFeedback")
        assert reply is not None
        assert confirmation is not None
        assert copy_button is not None
        assert useful is not None
        assert reason is not None
        assert submit is not None

        reply.setPlainText(edited_reply)
        QGuiApplication.clipboard().setText("")
        assert not copy_button.isEnabled()
        assert QGuiApplication.clipboard().text() != edited_reply
        confirmation.setChecked(True)
        QTest.mouseClick(copy_button, Qt.MouseButton.LeftButton)
        assert QGuiApplication.clipboard().text() == edited_reply

        # Capture, OCR, correction, retrieval, generation and copy add no files.
        assert _files_under(tmp_path) == files_before_capture

        QTest.mouseClick(useful, Qt.MouseButton.LeftButton)
        reason.setCurrentIndex(reason.findData(FeedbackReason.CLEAR))
        QTest.mouseClick(submit, Qt.MouseButton.LeftButton)
        assert feedback_path.is_file()

        with sqlite3.connect(feedback_path) as connection:
            columns = [
                row[1] for row in connection.execute("PRAGMA table_info(feedback)")
            ]
            stored = connection.execute(
                "SELECT useful, reason FROM feedback"
            ).fetchall()
        assert columns == [
            "id",
            "suggestion_id",
            "useful",
            "reason",
            "created_at",
        ]
        assert stored == [(1, FeedbackReason.CLEAR.value)]
        database_bytes = feedback_path.read_bytes()
        assert sensitive_transcript.encode("utf-8") not in database_bytes
        assert edited_reply.encode("utf-8") not in database_bytes
        assert sensitive_transcript not in caplog.text
        assert edited_reply not in caplog.text
    finally:
        advice_dialog.close()
        controller.shutdown()
        toolbar.close()
