import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Sequence

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from lexiaodu.capture import CaptureResult
from lexiaodu.domain import ScreenRegion
from lexiaodu.ocr import (
    OcrUnavailableError,
    Speaker,
    TranscriptLine,
)
from lexiaodu.toolbar import FloatingToolbar
from lexiaodu.workflow import CaptureController


class FakeSelector(QObject):
    region_selected = Signal(object)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.started = False

    def start(self) -> None:
        self.started = True

    def hide(self) -> None:
        pass


class FakeCapture:
    def __init__(self) -> None:
        self.region: ScreenRegion | None = None
        self.image = QImage(1000, 500, QImage.Format.Format_RGB32)

    def capture(self, region: ScreenRegion) -> CaptureResult:
        self.region = region
        return CaptureResult(self.image, region, "fake-screen")


class FakeOcr:
    def __init__(self, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.image: QImage | None = None

    def recognize(self, image: QImage) -> list[TranscriptLine]:
        self.image = image
        if self.unavailable:
            raise OcrUnavailableError("本地 PaddleOCR 未安装")
        return [TranscriptLine(speaker=Speaker.PARENT, text="识别文字")]


class FakeEditor(QWidget):
    instances: list["FakeEditor"] = []

    def __init__(
        self, lines: Sequence[TranscriptLine], notice: str
    ) -> None:
        super().__init__()
        self.lines = list(lines)
        self.notice = notice
        self.__class__.instances.append(self)


def test_toolbar_selection_capture_ocr_editor_integration() -> None:
    application = QApplication.instance() or QApplication([])
    toolbar = FloatingToolbar("乐小读", 360, 52)
    selector = FakeSelector()
    capture = FakeCapture()
    ocr = FakeOcr()
    FakeEditor.instances.clear()
    controller = CaptureController(
        toolbar,
        capture,
        ocr,
        selector_factory=lambda: selector,
        editor_factory=FakeEditor,
    )
    region = ScreenRegion(100, 50, 1000, 500)

    assert application is not None
    toolbar.capture_requested.emit()
    assert selector.started
    selector.region_selected.emit(region)

    assert capture.region == region
    assert ocr.image is capture.image
    assert FakeEditor.instances[-1].lines == [
        TranscriptLine(speaker=Speaker.PARENT, text="识别文字")
    ]
    assert toolbar.status_text == "识别到 1 条文字"

    FakeEditor.instances[-1].close()
    toolbar.close()
    del controller


def test_ocr_unavailable_opens_manual_fallback_editor() -> None:
    application = QApplication.instance() or QApplication([])
    toolbar = FloatingToolbar("乐小读", 360, 52)
    capture = FakeCapture()
    FakeEditor.instances.clear()
    controller = CaptureController(
        toolbar,
        capture,
        FakeOcr(unavailable=True),
        selector_factory=FakeSelector,
        editor_factory=FakeEditor,
    )

    assert application is not None
    controller.capture_region(ScreenRegion(0, 0, 1000, 500))

    editor = FakeEditor.instances[-1]
    assert editor.lines == []
    assert "手动粘贴" in editor.notice
    assert toolbar.status_text == "OCR 不可用，可手动粘贴"

    editor.close()
    toolbar.close()
    del controller
