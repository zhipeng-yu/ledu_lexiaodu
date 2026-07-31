import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Callable, Sequence
from threading import Thread, current_thread
from time import monotonic

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
)

from lexiaodu.advice import AdviceSuggestion
from lexiaodu.capture import CaptureResult
from lexiaodu.chat import AiChatDialog, ChatMessage, ChatRole
from lexiaodu.domain import ScreenRegion
from lexiaodu.editor import TranscriptEditor
from lexiaodu.knowledge import KnowledgeType, SearchResult
from lexiaodu.ocr import (
    OcrUnavailableError,
    Speaker,
    TranscriptLine,
)
from lexiaodu.toolbar import FloatingToolbar
from lexiaodu.risk import RiskAssessment, RiskLevel, TransferStatus
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
        self.preload_count = 0
        self.recognize_thread: Thread | None = None

    def preload(self) -> None:
        self.preload_count += 1

    def recognize(self, image: QImage) -> list[TranscriptLine]:
        self.image = image
        self.recognize_thread = current_thread()
        if self.unavailable:
            raise OcrUnavailableError("本地 PaddleOCR 未安装")
        return [TranscriptLine(speaker=Speaker.PARENT, text="识别文字")]


class FakeEditor(QDialog):
    instances: list["FakeEditor"] = []

    def __init__(
        self, lines: Sequence[TranscriptLine], notice: str
    ) -> None:
        super().__init__()
        self.lines = list(lines)
        self.notice = notice
        self.__class__.instances.append(self)

    def transcript(self) -> list[TranscriptLine]:
        return self.lines


class FakeAdviceService:
    def __init__(self) -> None:
        self.transcripts: list[str] = []

    def create(self, transcript: str) -> AdviceSuggestion:
        self.transcripts.append(transcript)
        return AdviceSuggestion(
            suggestion_id="generated-suggestion",
            concern_summary="家长关注阅读安排。",
            wechat_reply="您好，本周安排两次共读。",
            facts=(
                SearchResult(
                    knowledge_type=KnowledgeType.POLICY,
                    document_name="阅读制度.txt",
                    locator="每周安排",
                    evidence="每周安排两次共读。",
                    score=2.0,
                ),
            ),
            risk=RiskAssessment(
                RiskLevel.LOW,
                ("请核对事实。",),
                TransferStatus.NOT_REQUIRED,
            ),
        )


def wait_until(predicate: Callable[[], bool], timeout_ms: int = 1000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not predicate():
        if monotonic() >= deadline:
            raise AssertionError("等待异步 OCR 结果超时")
        QTest.qWait(1)


def test_ocr_models_preload_before_capture() -> None:
    application = QApplication.instance() or QApplication([])
    toolbar = FloatingToolbar("乐小读", 360, 52)
    ocr = FakeOcr()
    controller = CaptureController(
        toolbar,
        FakeCapture(),
        ocr,
        selector_factory=FakeSelector,
        editor_factory=FakeEditor,
    )

    assert application is not None
    wait_until(lambda: ocr.preload_count == 1)
    assert ocr.image is None

    controller.shutdown()
    toolbar.close()


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
    ready: list[list[TranscriptLine]] = []
    controller.transcript_ready.connect(ready.append)
    region = ScreenRegion(100, 50, 1000, 500)

    assert application is not None
    toolbar.capture_requested.emit()
    assert selector.started
    selector.region_selected.emit(region)

    assert capture.region == region
    assert FakeEditor.instances == []
    assert toolbar.status_text == "正在识别…"
    wait_until(lambda: bool(FakeEditor.instances))

    assert ocr.image is not None
    assert ocr.image.cacheKey() == capture.image.cacheKey()
    assert ocr.preload_count == 1
    assert ocr.recognize_thread is not current_thread()
    assert FakeEditor.instances[-1].lines == [
        TranscriptLine(speaker=Speaker.PARENT, text="识别文字")
    ]
    assert toolbar.status_text == "识别到 1 条文字"

    FakeEditor.instances[-1].accept()
    assert ready == [
        [TranscriptLine(speaker=Speaker.PARENT, text="识别文字")]
    ]
    assert toolbar.status_text == "已确认 1 条文字，等待 AI 处理"
    controller.shutdown()
    toolbar.close()


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
    assert toolbar.status_text == "正在识别…"
    wait_until(lambda: bool(FakeEditor.instances))

    editor = FakeEditor.instances[-1]
    assert editor.lines == []
    assert "手动粘贴" in editor.notice
    assert toolbar.status_text == "OCR 不可用，可手动粘贴"

    editor.close()
    controller.shutdown()
    toolbar.close()


def test_ai_chat_submits_parent_questions_and_preserves_history() -> None:
    application = QApplication.instance() or QApplication([])
    toolbar = FloatingToolbar("乐小读", 460, 52)
    chat = AiChatDialog()
    controller = CaptureController(
        toolbar,
        FakeCapture(),
        FakeOcr(),
        selector_factory=FakeSelector,
        editor_factory=FakeEditor,
        chat_factory=lambda: chat,
    )
    questions: list[str] = []
    ready: list[list[TranscriptLine]] = []
    controller.ai_question_submitted.connect(questions.append)
    controller.transcript_ready.connect(ready.append)

    assert application is not None
    toolbar.ai_chat_requested.emit()
    chat_input = chat.findChild(QPlainTextEdit, "chatInput")
    assert chat.isVisible()
    assert chat_input is not None
    assert chat.windowTitle() == "AI 问答"
    assert not chat.is_advice_mode
    assert chat_input.isVisible()
    chat_input.setPlainText("孩子不愿意阅读怎么办？")
    assert chat.send_question()

    assert questions == ["孩子不愿意阅读怎么办？"]
    assert ready == [
        [
            TranscriptLine(
                speaker=Speaker.PARENT,
                text="孩子不愿意阅读怎么办？",
            )
        ]
    ]
    assert toolbar.status_text == "已提交家长问题，等待 AI 回复"

    controller.append_ai_response("可以先从孩子感兴趣的主题开始。")
    assert chat.messages == (
        ChatMessage(ChatRole.QUESTION, "孩子不愿意阅读怎么办？"),
        ChatMessage(
            ChatRole.ASSISTANT,
            "可以先从孩子感兴趣的主题开始。",
        ),
    )
    chat.hide()
    toolbar.ai_chat_requested.emit()
    assert chat.isVisible()
    assert len(chat.messages) == 2

    chat.close()
    controller.shutdown()
    toolbar.close()


def test_ai_chat_generates_structured_suggestion_in_background() -> None:
    application = QApplication.instance() or QApplication([])
    toolbar = FloatingToolbar("乐小读", 460, 52)
    chat = AiChatDialog()
    advice = FakeAdviceService()
    controller = CaptureController(
        toolbar,
        FakeCapture(),
        FakeOcr(),
        selector_factory=FakeSelector,
        editor_factory=FakeEditor,
        chat_factory=lambda: chat,
        advice_service=advice,
    )

    assert application is not None
    toolbar.ai_chat_requested.emit()
    chat_input = chat.findChild(QPlainTextEdit, "chatInput")
    history = chat.findChild(QListWidget, "chatHistory")
    assert chat_input is not None
    assert history is not None
    chat_input.setPlainText("孩子这周怎么安排阅读？")
    assert chat.send_question()

    wait_until(lambda: len(chat.messages) == 2)
    assert advice.transcripts == ["家长：孩子这周怎么安排阅读？"]
    assert chat.messages[-1] == ChatMessage(
        ChatRole.ASSISTANT,
        "您好，本周安排两次共读。",
    )
    assert history.itemWidget(history.item(1)).objectName() == "suggestionTurn"
    assert toolbar.status_text == "建议已生成，请核对后使用"

    chat.close()
    controller.shutdown()
    toolbar.close()


def test_confirmed_ocr_transcript_opens_result_only_suggestion_workspace() -> None:
    application = QApplication.instance() or QApplication([])
    toolbar = FloatingToolbar("乐小读", 460, 52)
    manual_chat = AiChatDialog()
    advice_dialog = AiChatDialog()
    advice = FakeAdviceService()
    FakeEditor.instances.clear()
    controller = CaptureController(
        toolbar,
        FakeCapture(),
        FakeOcr(),
        selector_factory=FakeSelector,
        editor_factory=FakeEditor,
        chat_factory=lambda: manual_chat,
        advice_factory=lambda: advice_dialog,
        advice_service=advice,
    )

    assert application is not None
    controller.capture_region(ScreenRegion(0, 0, 1000, 500))
    wait_until(lambda: bool(FakeEditor.instances))
    assert not advice_dialog.isVisible()
    assert advice.transcripts == []
    FakeEditor.instances[-1].accept()

    assert advice_dialog.isVisible()
    assert not manual_chat.isVisible()
    assert advice_dialog.windowTitle() == "顾问建议"
    assert advice_dialog.is_advice_mode
    advice_input = advice_dialog.findChild(QPlainTextEdit, "chatInput")
    assert advice_input is not None
    assert not advice_input.isVisible()
    wait_until(lambda: len(advice_dialog.messages) == 1)
    assert advice_dialog.messages[0] == ChatMessage(
        ChatRole.ASSISTANT,
        "您好，本周安排两次共读。",
    )
    assert advice.transcripts == ["家长：识别文字"]

    advice_dialog.close()
    manual_chat.close()
    controller.shutdown()
    toolbar.close()


def test_real_editor_confirmation_reaches_generated_advice() -> None:
    application = QApplication.instance() or QApplication([])
    toolbar = FloatingToolbar("乐小读", 460, 52)
    advice_dialog = AiChatDialog()
    advice = FakeAdviceService()
    controller = CaptureController(
        toolbar,
        FakeCapture(),
        FakeOcr(),
        selector_factory=FakeSelector,
        editor_factory=TranscriptEditor,
        advice_factory=lambda: advice_dialog,
        advice_service=advice,
    )

    assert application is not None
    controller._show_editor(
        [TranscriptLine(Speaker.PARENT, "怎么请假")],
        "请核对",
    )
    assert isinstance(controller._editor, TranscriptEditor)
    confirm = controller._editor.findChild(
        QPushButton,
        "confirmTranscript",
    )
    assert confirm is not None
    assert advice.transcripts == []

    confirm.click()
    wait_until(lambda: len(advice_dialog.messages) == 1)

    assert advice.transcripts == ["家长：怎么请假"]
    assert "后续建议已生成" in advice_dialog.status_text

    advice_dialog.close()
    controller.shutdown()
    toolbar.close()
