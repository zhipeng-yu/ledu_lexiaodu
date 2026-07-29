from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject

from lexiaodu.capture import CaptureError, ScreenCapture
from lexiaodu.domain import ScreenRegion
from lexiaodu.editor import TranscriptEditor
from lexiaodu.ocr import OcrEngine, OcrError, OcrUnavailableError, TranscriptLine
from lexiaodu.selection import SelectionOverlay
from lexiaodu.toolbar import FloatingToolbar


class CaptureController(QObject):
    """Coordinate selection, in-memory capture, OCR, and correction UI."""

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
    ) -> None:
        super().__init__(toolbar)
        self._toolbar = toolbar
        self._capture = capture
        self._ocr = ocr
        self._selector_factory = selector_factory
        self._editor_factory = editor_factory
        self._selector: SelectionOverlay | None = None
        self._editor: TranscriptEditor | None = None
        toolbar.capture_requested.connect(self.start_capture)

    def start_capture(self) -> None:
        if self._selector is not None:
            return
        self._toolbar.hide()
        self._toolbar.set_status("请拖框选择聊天区域")
        selector = self._selector_factory()
        self._selector = selector
        selector.region_selected.connect(self.capture_region)
        selector.cancelled.connect(self.cancel_capture)
        selector.start()

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
        notice = "请核对 OCR 文字和发言人。"
        try:
            lines = self._ocr.recognize(result.image)
        except OcrUnavailableError as exc:
            lines = []
            notice = f"{exc}。请在下方手动粘贴文字。"
            self._toolbar.set_status("OCR 不可用，可手动粘贴")
        except OcrError as exc:
            lines = []
            notice = f"{exc}。请在下方手动粘贴文字。"
            self._toolbar.set_status("OCR 失败，可手动粘贴")
        else:
            if lines:
                self._toolbar.set_status(f"识别到 {len(lines)} 条文字")
            else:
                notice = "OCR 未识别到文字，请在下方手动粘贴。"
                self._toolbar.set_status("未识别到文字，可手动粘贴")

        self._editor = self._editor_factory(lines, notice)
        self._editor.show()
