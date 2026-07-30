from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal, Slot

from lexiaodu.capture import CaptureError, ScreenCapture
from lexiaodu.chat import AiChatDialog
from lexiaodu.domain import ScreenRegion
from lexiaodu.editor import TranscriptEditor
from lexiaodu.ocr import (
    OcrEngine,
    OcrError,
    OcrUnavailableError,
    Speaker,
    TranscriptLine,
)
from lexiaodu.selection import SelectionOverlay
from lexiaodu.toolbar import FloatingToolbar


class CaptureController(QObject):
    """Coordinate selection, in-memory capture, OCR, and correction UI."""

    transcript_ready = Signal(object)
    ai_question_submitted = Signal(str)
    _recognized = Signal(object)
    _unavailable = Signal(str)
    _failed = Signal(str)

    def __init__(
        self,
        toolbar: FloatingToolbar,
        capture: ScreenCapture,
        ocr: OcrEngine,
        *,
        selector_factory: Callable[[], SelectionOverlay] = SelectionOverlay,
        editor_factory: Callable[
            [Sequence[TranscriptLine], str], TranscriptEditor
        ] = TranscriptEditor,
        chat_factory: Callable[[], AiChatDialog] = AiChatDialog,
    ) -> None:
        super().__init__(toolbar)
        self._toolbar = toolbar
        self._capture = capture
        self._ocr = ocr
        self._selector_factory = selector_factory
        self._editor_factory = editor_factory
        self._chat_factory = chat_factory
        self._selector: SelectionOverlay | None = None
        self._editor: TranscriptEditor | None = None
        self._chat_dialog: AiChatDialog | None = None
        self._recognition_in_progress = False
        self._shutting_down = False

        self._ocr_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="lexiaodu-ocr",
        )
        self._recognized.connect(self._recognition_finished)
        self._unavailable.connect(self._recognition_unavailable)
        self._failed.connect(self._recognition_failed)
        self._ocr_executor.submit(self._preload_ocr)

        toolbar.capture_requested.connect(self.start_capture)
        toolbar.ai_chat_requested.connect(self.start_ai_chat)

    def _preload_ocr(self) -> None:
        try:
            self._ocr.preload()
        except OcrError:
            # Recognition will report the actionable error through the
            # existing manual-paste fallback when the user takes a screenshot.
            pass

    def start_capture(self) -> None:
        if self._selector is not None or self._recognition_in_progress:
            return
        self._toolbar.hide()
        self._toolbar.set_status("请拖框选择聊天区域")
        selector = self._selector_factory()
        self._selector = selector
        selector.region_selected.connect(self.capture_region)
        selector.cancelled.connect(self.cancel_capture)
        selector.start()

    @Slot()
    def start_ai_chat(self) -> None:
        if self._chat_dialog is None:
            dialog = self._chat_factory()
            dialog.question_submitted.connect(self._submit_chat_question)
            self._chat_dialog = dialog
        self._chat_dialog.show()
        self._chat_dialog.raise_()
        self._chat_dialog.activateWindow()

    @Slot(str)
    def _submit_chat_question(self, text: str) -> None:
        self._toolbar.set_status("已提交家长问题，等待 AI 回复")
        self.ai_question_submitted.emit(text)
        self.transcript_ready.emit(
            [TranscriptLine(speaker=Speaker.PARENT, text=text)]
        )

    @Slot(str)
    def append_ai_response(self, text: str) -> None:
        if self._chat_dialog is None:
            self.start_ai_chat()
        if (
            self._chat_dialog is not None
            and self._chat_dialog.append_ai_response(text)
        ):
            self._toolbar.set_status("AI 已回复")

    def cancel_capture(self) -> None:
        self._dispose_selector()
        self._toolbar.set_status("已取消截图")
        self._toolbar.show()

    def _dispose_selector(self) -> None:
        if self._selector is None:
            return
        selector = self._selector
        self._selector = None
        selector.hide()
        selector.deleteLater()

    def capture_region(self, region: ScreenRegion) -> None:
        self._dispose_selector()
        try:
            result = self._capture.capture(region)
        except CaptureError as exc:
            self._toolbar.set_status(f"截图失败：{exc}")
            self._toolbar.show()
            return

        self._toolbar.set_status("正在识别…")
        self._toolbar.show()
        self._recognition_in_progress = True
        future = self._ocr_executor.submit(self._ocr.recognize, result.image)
        future.add_done_callback(self._recognition_done)

    def _recognition_done(
        self,
        future: Future[list[TranscriptLine]],
    ) -> None:
        if self._shutting_down:
            return
        try:
            lines = future.result()
        except OcrUnavailableError as exc:
            self._unavailable.emit(str(exc))
        except OcrError as exc:
            self._failed.emit(str(exc))
        else:
            self._recognized.emit(lines)

    @Slot(object)
    def _recognition_finished(self, lines: Sequence[TranscriptLine]) -> None:
        self._recognition_in_progress = False
        notice = "请核对 OCR 文字和发言人。"
        if lines:
            self._toolbar.set_status(f"识别到 {len(lines)} 条文字")
        else:
            notice = "OCR 未识别到文字，请在下方手动粘贴。"
            self._toolbar.set_status("未识别到文字，可手动粘贴")
        self._show_editor(lines, notice)

    @Slot(str)
    def _recognition_unavailable(self, message: str) -> None:
        self._recognition_in_progress = False
        self._toolbar.set_status("OCR 不可用，可手动粘贴")
        self._show_manual_fallback(message)

    @Slot(str)
    def _recognition_failed(self, message: str) -> None:
        self._recognition_in_progress = False
        self._toolbar.set_status("OCR 失败，可手动粘贴")
        self._show_manual_fallback(message)

    def _show_manual_fallback(self, message: str) -> None:
        notice = f"{message}。请在下方手动粘贴文字。"
        self._show_editor([], notice)

    def _show_editor(
        self,
        lines: Sequence[TranscriptLine],
        notice: str,
    ) -> None:
        editor = self._editor_factory(lines, notice)
        editor.accepted.connect(
            lambda editor=editor: self._submit_editor_transcript(editor)
        )
        self._editor = editor
        editor.show()

    def _submit_editor_transcript(self, editor: TranscriptEditor) -> None:
        lines = editor.transcript()
        if not lines:
            return
        self._toolbar.set_status(f"已确认 {len(lines)} 条文字，等待 AI 处理")
        self.transcript_ready.emit(lines)

    @Slot()
    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._ocr_executor.shutdown(wait=True, cancel_futures=True)
