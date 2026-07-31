from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal, Slot

from lexiaodu.advice import AdviceService, AdviceSuggestion
from lexiaodu.capture import CaptureError, ScreenCapture
from lexiaodu.chat import AiChatDialog
from lexiaodu.domain import ScreenRegion
from lexiaodu.editor import TranscriptEditor
from lexiaodu.feedback import FeedbackStore, FeedbackSubmission
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
    _suggestion_ready = Signal(object)
    _suggestion_failed = Signal(object)

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
        advice_factory: Callable[[], AiChatDialog] = AiChatDialog,
        advice_service: AdviceService | None = None,
        feedback_store: FeedbackStore | None = None,
    ) -> None:
        super().__init__(toolbar)
        self._toolbar = toolbar
        self._capture = capture
        self._ocr = ocr
        self._selector_factory = selector_factory
        self._editor_factory = editor_factory
        self._chat_factory = chat_factory
        self._advice_factory = advice_factory
        self._advice_service = advice_service
        self._feedback_store = feedback_store
        self._selector: SelectionOverlay | None = None
        self._editor: TranscriptEditor | None = None
        self._chat_dialog: AiChatDialog | None = None
        self._advice_dialog: AiChatDialog | None = None
        self._recognition_in_progress = False
        self._shutting_down = False

        self._ocr_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="lexiaodu-ocr",
        )
        self._advice_executor = (
            ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="lexiaodu-advice",
            )
            if advice_service is not None
            else None
        )
        self._recognized.connect(self._recognition_finished)
        self._unavailable.connect(self._recognition_unavailable)
        self._failed.connect(self._recognition_failed)
        self._suggestion_ready.connect(self._show_suggestion)
        self._suggestion_failed.connect(self._show_suggestion_error)
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
            dialog.feedback_submitted.connect(self._save_feedback)
            self._chat_dialog = dialog
        self._chat_dialog.set_manual_mode()
        self._chat_dialog.show()
        self._chat_dialog.raise_()
        self._chat_dialog.activateWindow()

    @Slot(str)
    def _submit_chat_question(self, text: str) -> None:
        self._toolbar.set_status(
            "已提交家长问题，正在检索知识"
            if self._advice_service is not None
            else "已提交家长问题，等待 AI 回复"
        )
        self.ai_question_submitted.emit(text)
        lines = [TranscriptLine(speaker=Speaker.PARENT, text=text)]
        self.transcript_ready.emit(lines)
        if self._chat_dialog is not None:
            self._request_suggestion(lines, self._chat_dialog)

    @Slot(str)
    def append_ai_response(self, text: str) -> None:
        if self._chat_dialog is None:
            self.start_ai_chat()
        if (
            self._chat_dialog is not None
            and self._chat_dialog.append_ai_response(text)
        ):
            self._toolbar.set_status("AI 已回复")

    def _request_suggestion(
        self,
        lines: Sequence[TranscriptLine],
        target: AiChatDialog,
    ) -> None:
        if (
            self._advice_service is None
            or self._advice_executor is None
            or self._shutting_down
        ):
            return
        try:
            transcript = "\n".join(
                f"{Speaker(line.speaker).value}：{line.text.strip()}"
                for line in lines
            )
        except (AttributeError, TypeError, ValueError) as exc:
            target.show_generation_error(f"对话数据无效：{exc}")
            self._toolbar.set_status("建议生成失败，请检查校正内容")
            return
        if not target.is_advice_mode:
            target.set_generating()
        try:
            future = self._advice_executor.submit(
                self._advice_service.create,
                transcript,
            )
        except RuntimeError as exc:
            target.show_generation_error(f"无法启动建议任务：{exc}")
            self._toolbar.set_status("建议任务启动失败")
            return
        future.add_done_callback(
            lambda completed, target=target: self._suggestion_done(
                completed,
                target,
            )
        )

    def _suggestion_done(
        self,
        future: Future[AdviceSuggestion],
        target: AiChatDialog,
    ) -> None:
        if self._shutting_down:
            return
        try:
            suggestion = future.result()
        except Exception as exc:
            self._suggestion_failed.emit((target, str(exc)))
        else:
            self._suggestion_ready.emit((target, suggestion))

    @Slot(object)
    def _show_suggestion(
        self,
        result: tuple[AiChatDialog, AdviceSuggestion],
    ) -> None:
        target, suggestion = result
        if target.append_suggestion(suggestion):
            self._toolbar.set_status("建议已生成，请核对后使用")

    @Slot(object)
    def _show_suggestion_error(
        self,
        result: tuple[AiChatDialog, str],
    ) -> None:
        target, message = result
        target.show_generation_error(message)
        self._toolbar.set_status("建议生成失败，请检查知识索引")

    @Slot(object)
    def _save_feedback(self, submission: FeedbackSubmission) -> None:
        if self._feedback_store is None:
            return
        try:
            self._feedback_store.save(submission)
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._toolbar.set_status(f"反馈保存失败：{exc}")
        else:
            self._toolbar.set_status("反馈已记录（未保存聊天正文）")

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
        self._toolbar.set_status(
            f"已确认 {len(lines)} 条文字，正在检索知识"
            if self._advice_service is not None
            else f"已确认 {len(lines)} 条文字，等待 AI 处理"
        )
        self.transcript_ready.emit(lines)
        if self._advice_service is None:
            return
        if self._advice_dialog is None:
            dialog = self._advice_factory()
            dialog.feedback_submitted.connect(self._save_feedback)
            self._advice_dialog = dialog
        self._advice_dialog.begin_advice_session(len(lines))
        self._advice_dialog.show()
        self._advice_dialog.raise_()
        self._advice_dialog.activateWindow()
        self._request_suggestion(lines, self._advice_dialog)

    @Slot()
    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._ocr_executor.shutdown(wait=True, cancel_futures=True)
        if self._advice_executor is not None:
            self._advice_executor.shutdown(wait=True, cancel_futures=True)
