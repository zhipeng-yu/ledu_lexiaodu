from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from lexiaodu.ocr import Speaker, TranscriptLine


@dataclass(frozen=True, slots=True)
class CorrectedTranscript:
    lines: tuple[TranscriptLine, ...]
    text: str


class TranscriptEditor(QDialog):
    """Editable OCR transcript with an explicit manual-paste fallback."""

    def __init__(
        self,
        lines: Sequence[TranscriptLine] = (),
        notice: str = "",
    ) -> None:
        super().__init__()
        self.setObjectName("transcriptEditor")
        self.setWindowTitle("OCR 文字校正")
        self.resize(760, 520)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        layout = QVBoxLayout(self)
        self._notice = QLabel(notice or "请核对 OCR 文字和发言人。")
        self._notice.setObjectName("notice")
        self._notice.setWordWrap(True)
        layout.addWidget(self._notice)

        self._table = QTableWidget(0, 3)
        self._table.setObjectName("transcriptTable")
        self._table.setHorizontalHeaderLabels(["发言人", "文字", "置信度"])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, self._table.horizontalHeader().ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, self._table.horizontalHeader().ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, self._table.horizontalHeader().ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        layout.addWidget(self._table, 1)

        for line in lines:
            self._append_row(
                speaker=line.speaker,
                text=line.text,
                confidence=line.confidence,
            )

        table_actions = QHBoxLayout()
        add_row = QPushButton("添加空白发言")
        add_row.clicked.connect(
            lambda: self._append_row(Speaker.PARENT, "", None)
        )
        table_actions.addWidget(add_row)
        remove_rows = QPushButton("删除所选")
        remove_rows.clicked.connect(self._remove_selected_rows)
        table_actions.addWidget(remove_rows)
        table_actions.addStretch()
        layout.addLayout(table_actions)

        layout.addWidget(QLabel("OCR 不可用或识别遗漏时，可在此粘贴文字："))
        self._manual_text = QPlainTextEdit()
        self._manual_text.setObjectName("manualText")
        self._manual_text.setPlaceholderText("粘贴一段发言，然后选择发言人…")
        self._manual_text.setMaximumHeight(110)
        layout.addWidget(self._manual_text)

        manual_actions = QHBoxLayout()
        add_parent = QPushButton("作为家长添加")
        add_parent.setObjectName("addParent")
        add_parent.clicked.connect(
            lambda: self.add_manual_text(Speaker.PARENT)
        )
        manual_actions.addWidget(add_parent)
        add_advisor = QPushButton("作为顾问添加")
        add_advisor.setObjectName("addAdvisor")
        add_advisor.clicked.connect(
            lambda: self.add_manual_text(Speaker.ADVISOR)
        )
        manual_actions.addWidget(add_advisor)
        manual_actions.addStretch()
        confirm_button = QPushButton("确认无误并生成建议")
        confirm_button.setObjectName("confirmTranscript")
        confirm_button.clicked.connect(self.accept)
        manual_actions.addWidget(confirm_button)
        layout.addLayout(manual_actions)

    @property
    def notice(self) -> str:
        return self._notice.text()

    def _append_row(
        self,
        speaker: Speaker,
        text: str,
        confidence: float | None,
    ) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        speaker_editor = QComboBox()
        speaker_editor.setObjectName(f"speaker-{row}")
        for option in Speaker:
            speaker_editor.addItem(option.value, option)
        speaker_editor.setCurrentText(speaker.value)
        self._table.setCellWidget(row, 0, speaker_editor)

        self._table.setItem(row, 1, QTableWidgetItem(text))
        confidence_text = (
            f"{confidence:.0%}" if confidence is not None else "手动"
        )
        confidence_item = QTableWidgetItem(confidence_text)
        confidence_item.setFlags(
            confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable
        )
        self._table.setItem(row, 2, confidence_item)

    def _remove_selected_rows(self) -> None:
        rows = sorted(
            {index.row() for index in self._table.selectedIndexes()},
            reverse=True,
        )
        for row in rows:
            self._table.removeRow(row)

    def add_manual_text(self, speaker: Speaker) -> bool:
        text = self._manual_text.toPlainText().strip()
        if not text:
            return False
        self._append_row(speaker, text, None)
        self._manual_text.clear()
        return True

    def transcript(self) -> list[TranscriptLine]:
        lines: list[TranscriptLine] = []
        for row in range(self._table.rowCount()):
            speaker_editor = self._table.cellWidget(row, 0)
            text_item = self._table.item(row, 1)
            if not isinstance(speaker_editor, QComboBox) or text_item is None:
                continue
            text = text_item.text().strip()
            if not text:
                continue
            speaker = speaker_editor.currentData()
            lines.append(TranscriptLine(speaker=speaker, text=text))
        return lines

    def corrected_transcript(self) -> CorrectedTranscript:
        lines = tuple(self.transcript())
        return CorrectedTranscript(
            lines=lines,
            text="\n".join(line.text for line in lines),
        )
