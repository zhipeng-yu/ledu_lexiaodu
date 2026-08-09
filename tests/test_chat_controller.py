from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Callable, Sequence
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from lexiaodu.attachments import AttachmentStore
from lexiaodu.capture import CaptureResult
from lexiaodu.chat_controller import ChatController
from lexiaodu.chat_window import ChatConversationView, ChatTurnView
from lexiaodu.context import ContextBuilder, ContextPackage
from lexiaodu.conversations import ConversationRepository
from lexiaodu.domain import ScreenRegion
from lexiaodu.editor import CorrectedTranscript
from lexiaodu.local_crypto import DataCipher
from lexiaodu.ocr import Speaker, TranscriptLine


class FakeWindow(QObject):
    conversation_selected = Signal(str)
    send_requested = Signal(str)
    retry_requested = Signal(str)
    capture_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._active_conversation_id: str | None = None
        self.conversations: tuple[ChatConversationView, ...] = ()
        self.turns: tuple[ChatTurnView, ...] = ()
        self.shown: list[tuple[str, tuple[ChatTurnView, ...]]] = []

    @property
    def active_conversation_id(self) -> str | None:
        return self._active_conversation_id

    def set_conversations(
        self, conversations: tuple[ChatConversationView, ...]
    ) -> None:
        self.conversations = conversations
        self._active_conversation_id = None

    def show_conversation(
        self,
        conversation_id: str,
        turns: tuple[ChatTurnView, ...],
    ) -> None:
        self._active_conversation_id = conversation_id
        self.turns = turns
        self.shown.append((conversation_id, turns))

    def select(self, conversation_id: str) -> None:
        self._active_conversation_id = conversation_id
        self.conversation_selected.emit(conversation_id)


class ManualExecutor:
    def __init__(self) -> None:
        self.pending: list[
            tuple[Future[Any], Callable[..., Any], tuple[Any, ...]]
        ] = []
        self.shutdown_calls: list[tuple[bool, bool]] = []

    def submit(
        self, function: Callable[..., Any], *args: Any
    ) -> Future[Any]:
        future: Future[Any] = Future()
        self.pending.append((future, function, args))
        return future

    def run_next(self) -> Future[Any]:
        future, function, args = self.pending.pop(0)
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(function(*args))
            except BaseException as exc:
                future.set_exception(exc)
        return future

    def shutdown(
        self, *, wait: bool = True, cancel_futures: bool = False
    ) -> None:
        self.shutdown_calls.append((wait, cancel_futures))


class ImmediateExecutor(ManualExecutor):
    def submit(
        self, function: Callable[..., Any], *args: Any
    ) -> Future[Any]:
        future = super().submit(function, *args)
        self.run_next()
        return future


class CancelPendingExecutor(ManualExecutor):
    def shutdown(
        self, *, wait: bool = True, cancel_futures: bool = False
    ) -> None:
        super().shutdown(wait=wait, cancel_futures=cancel_futures)
        if not cancel_futures:
            return
        pending = list(self.pending)
        self.pending.clear()
        for future, _function, _args in pending:
            future.cancel()


class RecordingRepository:
    def __init__(
        self,
        repository: ConversationRepository,
        events: list[str],
    ) -> None:
        self._repository = repository
        self._events = events

    def append_user_message(self, *args: Any, **kwargs: Any) -> Any:
        self._events.append("append:start")
        message = self._repository.append_user_message(*args, **kwargs)
        self._events.append("append:done")
        return message

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repository, name)


class RecordingAssistant:
    def __init__(
        self,
        repository: ConversationRepository,
        outcomes: Sequence[str | BaseException],
        events: list[str] | None = None,
    ) -> None:
        self._repository = repository
        self._outcomes = list(outcomes)
        self._events = events
        self.calls: list[tuple[ContextPackage, str]] = []

    def respond(self, context: ContextPackage, request_id: str) -> str:
        if self._events is not None:
            self._events.append("assistant")
        request = next(
            message
            for conversation in self._repository.list_conversations()
            for message in self._repository.list_messages(conversation.id)
            if message.request_id == request_id
        )
        assert request.processing_status == "processing"
        self.calls.append((context, request_id))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeCapture:
    def __init__(self, image: QImage) -> None:
        self.image = image
        self.regions: list[ScreenRegion] = []

    def capture(self, region: ScreenRegion) -> CaptureResult:
        self.regions.append(region)
        return CaptureResult(self.image, region, "test-screen")


class FakeOcr:
    def __init__(self, lines: Sequence[TranscriptLine] = ()) -> None:
        self.lines = list(lines)
        self.preload_calls = 0
        self.images: list[QImage] = []

    def preload(self) -> None:
        self.preload_calls += 1

    def recognize(self, image: QImage) -> list[TranscriptLine]:
        self.images.append(image)
        return self.lines


class FakeSelector(QObject):
    region_selected = Signal(object)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.hidden = False

    def start(self) -> None:
        self.started = True

    def hide(self) -> None:
        self.hidden = True


class FakeEditor(QObject):
    accepted = Signal()
    finished = Signal(int)

    def __init__(
        self,
        lines: Sequence[TranscriptLine],
        notice: str,
        corrected_text: str,
    ) -> None:
        super().__init__()
        self.lines = tuple(lines)
        self.notice = notice
        self.corrected_text = corrected_text
        self.shown = False
        self.closed = False
        self.deleted_later = False

    def corrected_transcript(self) -> CorrectedTranscript:
        line = TranscriptLine(Speaker.PARENT, self.corrected_text)
        return CorrectedTranscript((line,), self.corrected_text)

    def show(self) -> None:
        self.shown = True

    def close(self) -> None:
        self.closed = True

    def deleteLater(self) -> None:
        self.deleted_later = True


def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def repository_at(path: Path) -> ConversationRepository:
    return ConversationRepository(path, DataCipher(b"c" * 32))


def context_builder(repository: Any) -> ContextBuilder:
    return ContextBuilder(
        repository,
        recent_limit=20,
        related_limit=10,
        character_budget=10_000,
    )


def inert_capture_dependencies() -> tuple[
    FakeCapture,
    FakeOcr,
    Callable[[], FakeSelector],
    Callable[[Sequence[TranscriptLine], str], FakeEditor],
]:
    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    return (
        FakeCapture(image),
        FakeOcr(),
        FakeSelector,
        lambda lines, notice: FakeEditor(lines, notice, "unused"),
    )


def test_send_persists_before_assistant_and_background_result_stays_with_owner(
    tmp_path: Path,
) -> None:
    application()
    real_repository = repository_at(tmp_path / "chat.sqlite3")
    first = real_repository.create_conversation("first")
    second = real_repository.create_conversation("second")
    events: list[str] = []
    repository = RecordingRepository(real_repository, events)
    assistant = RecordingAssistant(real_repository, ["FIRST-ANSWER"], events)
    assistant_executor = ManualExecutor()
    capture, ocr, selector_factory, editor_factory = inert_capture_dependencies()
    window = FakeWindow()
    ChatController(
        window,
        repository,
        object(),
        context_builder(repository),
        assistant,
        capture,
        ocr,
        selector_factory,
        editor_factory,
        assistant_executor,
        ImmediateExecutor(),
    )

    window.select(first.id)
    window.send_requested.emit("FIRST-QUESTION")
    request = real_repository.list_messages(first.id)[0]
    assert request.processing_status == "processing"
    assert assistant.calls == []

    window.select(second.id)
    shown_before_completion = list(window.shown)
    assistant_executor.run_next()

    assert events == ["append:start", "append:done", "assistant"]
    assert [message.body for message in real_repository.list_messages(first.id)] == [
        "FIRST-QUESTION",
        "FIRST-ANSWER",
    ]
    assert real_repository.list_messages(second.id) == ()
    assert window.active_conversation_id == second.id
    assert window.shown == shown_before_completion


def test_assistant_failure_marks_the_existing_request_failed(
    tmp_path: Path,
) -> None:
    application()
    repository = repository_at(tmp_path / "chat.sqlite3")
    conversation = repository.create_conversation("failure")
    assistant = RecordingAssistant(repository, [RuntimeError("offline")])
    assistant_executor = ManualExecutor()
    capture, ocr, selector_factory, editor_factory = inert_capture_dependencies()
    window = FakeWindow()
    ChatController(
        window,
        repository,
        object(),
        context_builder(repository),
        assistant,
        capture,
        ocr,
        selector_factory,
        editor_factory,
        assistant_executor,
        ImmediateExecutor(),
    )

    window.select(conversation.id)
    window.send_requested.emit("FAIL-QUESTION")
    assistant_executor.run_next()

    messages = repository.list_messages(conversation.id)
    assert len(messages) == 1
    assert messages[0].body == "FAIL-QUESTION"
    assert messages[0].processing_status == "failed"
    assert len(window.turns) == 1
    assert window.turns[0].status == "failed"
    assert window.turns[0].request_id == messages[0].request_id


def test_retry_reuses_request_id_and_repeated_retry_cannot_add_two_answers(
    tmp_path: Path,
) -> None:
    application()
    repository = repository_at(tmp_path / "chat.sqlite3")
    conversation = repository.create_conversation("retry")
    assistant = RecordingAssistant(
        repository,
        [RuntimeError("first failure"), "RETRY-ANSWER"],
    )
    assistant_executor = ManualExecutor()
    capture, ocr, selector_factory, editor_factory = inert_capture_dependencies()
    window = FakeWindow()
    ChatController(
        window,
        repository,
        object(),
        context_builder(repository),
        assistant,
        capture,
        ocr,
        selector_factory,
        editor_factory,
        assistant_executor,
        ImmediateExecutor(),
    )

    window.select(conversation.id)
    window.send_requested.emit("RETRY-QUESTION")
    assistant_executor.run_next()
    request_id = repository.list_messages(conversation.id)[0].request_id
    assert request_id is not None

    window.retry_requested.emit(request_id)
    window.retry_requested.emit(request_id)
    assert len(assistant_executor.pending) == 1
    assistant_executor.run_next()
    window.retry_requested.emit(request_id)

    messages = repository.list_messages(conversation.id)
    assert [call_request_id for _, call_request_id in assistant.calls] == [
        request_id,
        request_id,
    ]
    assert [message.role for message in messages] == ["user", "assistant"]
    assert [message.body for message in messages] == [
        "RETRY-QUESTION",
        "RETRY-ANSWER",
    ]
    assert sum(turn.role == "assistant" for turn in window.turns) == 1
    assert assistant_executor.pending == []


def test_reconstruction_shows_interrupted_request_without_auto_sending(
    tmp_path: Path,
) -> None:
    application()
    database_path = tmp_path / "chat.sqlite3"
    first_repository = repository_at(database_path)
    conversation = first_repository.create_conversation("restart")
    first_repository.append_user_message(
        conversation.id,
        "INTERRUPTED-QUESTION",
        request_id="restart-request",
    )
    first_repository.mark_request_processing(
        conversation.id,
        "restart-request",
    )

    reopened = repository_at(database_path)
    assistant = RecordingAssistant(reopened, ["MUST-NOT-RUN"])
    assistant_executor = ManualExecutor()
    capture, ocr, selector_factory, editor_factory = inert_capture_dependencies()
    window = FakeWindow()
    ChatController(
        window,
        reopened,
        object(),
        context_builder(reopened),
        assistant,
        capture,
        ocr,
        selector_factory,
        editor_factory,
        assistant_executor,
        ImmediateExecutor(),
    )

    window.select(conversation.id)

    assert assistant.calls == []
    assert assistant_executor.pending == []
    assert len(window.turns) == 1
    assert window.turns[0].text == "INTERRUPTED-QUESTION"
    assert window.turns[0].status == "interrupted"
    assert window.turns[0].request_id == "restart-request"


def test_screenshot_uses_capture_start_owner_and_sends_only_corrected_context(
    tmp_path: Path,
) -> None:
    application()
    repository = repository_at(tmp_path / "chat.sqlite3")
    first = repository.create_conversation("capture owner")
    second = repository.create_conversation("later selection")
    attachments = AttachmentStore(
        tmp_path / "attachments",
        repository,
        DataCipher(b"c" * 32),
    )
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(QColor(11, 22, 33))
    capture = FakeCapture(image)
    ocr = FakeOcr([TranscriptLine(Speaker.PARENT, "RAW-OCR")])
    selector = FakeSelector()
    editors: list[FakeEditor] = []

    def editor_factory(
        lines: Sequence[TranscriptLine], notice: str
    ) -> FakeEditor:
        editor = FakeEditor(lines, notice, "CORRECTED-OCR")
        editors.append(editor)
        return editor

    assistant = RecordingAssistant(repository, ["SCREENSHOT-ANSWER"])
    assistant_executor = ManualExecutor()
    ocr_executor = ManualExecutor()
    window = FakeWindow()
    ChatController(
        window,
        repository,
        attachments,
        context_builder(repository),
        assistant,
        capture,
        ocr,
        lambda: selector,
        editor_factory,
        assistant_executor,
        ocr_executor,
    )
    ocr_executor.run_next()  # preload

    window.select(first.id)
    window.capture_requested.emit()
    assert selector.started
    region = ScreenRegion(10, 20, 4, 3)
    selector.region_selected.emit(region)
    assert capture.regions == [region]
    assert len(ocr_executor.pending) == 1

    window.select(second.id)
    ocr_executor.run_next()
    assert len(editors) == 1
    assert editors[0].shown
    assert editors[0].lines[0].text == "RAW-OCR"

    editors[0].accepted.emit()
    first_attachments = attachments.list_for_conversation(first.id)
    assert len(first_attachments) == 1
    assert first_attachments[0].corrected_text == "CORRECTED-OCR"
    assert attachments.list_for_conversation(second.id) == ()
    assert len(assistant_executor.pending) == 1

    assistant_executor.run_next()
    assert len(assistant.calls) == 1
    package, request_id = assistant.calls[0]
    assert isinstance(package, ContextPackage)
    assert package.attachment_texts == first_attachments
    assert package.render_for_model().count("CORRECTED-OCR") >= 1
    assert "RAW-OCR" not in package.render_for_model()
    assert not any(isinstance(item, QImage) for item in package.all_items())
    first_messages = repository.list_messages(first.id)
    assert first_messages[0].kind == "screenshot"
    assert first_messages[0].body == "CORRECTED-OCR"
    assert first_messages[0].request_id == request_id
    assert first_messages[1].body == "SCREENSHOT-ANSWER"
    assert repository.list_messages(second.id) == ()
    assert window.active_conversation_id == second.id


def test_shutdown_closes_and_deletes_an_open_transcript_editor(
    tmp_path: Path,
) -> None:
    application()
    repository = repository_at(tmp_path / "chat.sqlite3")
    conversation = repository.create_conversation("open editor")
    attachments = AttachmentStore(
        tmp_path / "attachments",
        repository,
        DataCipher(b"c" * 32),
    )
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    capture = FakeCapture(image)
    ocr = FakeOcr([TranscriptLine(Speaker.PARENT, "OCR")])
    selector = FakeSelector()
    editors: list[FakeEditor] = []

    def editor_factory(
        lines: Sequence[TranscriptLine], notice: str
    ) -> FakeEditor:
        editor = FakeEditor(lines, notice, "CORRECTED")
        editors.append(editor)
        return editor

    assistant = RecordingAssistant(repository, ["unused"])
    assistant_executor = ManualExecutor()
    ocr_executor = ManualExecutor()
    window = FakeWindow()
    controller = ChatController(
        window,
        repository,
        attachments,
        context_builder(repository),
        assistant,
        capture,
        ocr,
        lambda: selector,
        editor_factory,
        assistant_executor,
        ocr_executor,
    )
    ocr_executor.run_next()  # preload
    window.select(conversation.id)
    window.capture_requested.emit()
    selector.region_selected.emit(ScreenRegion(10, 20, 4, 3))
    ocr_executor.run_next()
    assert len(editors) == 1
    assert editors[0].shown

    controller.shutdown()

    assert editors[0].closed
    assert editors[0].deleted_later
    assert assistant_executor.shutdown_calls == [(True, True)]
    assert ocr_executor.shutdown_calls == [(True, True)]


def test_shutdown_cancellation_cannot_construct_or_show_an_ocr_editor(
    tmp_path: Path,
) -> None:
    application()
    repository = repository_at(tmp_path / "chat.sqlite3")
    conversation = repository.create_conversation("pending OCR")
    attachments = AttachmentStore(
        tmp_path / "attachments",
        repository,
        DataCipher(b"c" * 32),
    )
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    capture = FakeCapture(image)
    ocr = FakeOcr([TranscriptLine(Speaker.PARENT, "MUST-NOT-RUN")])
    selector = FakeSelector()
    editors: list[FakeEditor] = []

    def editor_factory(
        lines: Sequence[TranscriptLine], notice: str
    ) -> FakeEditor:
        editor = FakeEditor(lines, notice, "MUST-NOT-SHOW")
        editors.append(editor)
        return editor

    ocr_executor = CancelPendingExecutor()
    window = FakeWindow()
    controller = ChatController(
        window,
        repository,
        attachments,
        context_builder(repository),
        RecordingAssistant(repository, ["unused"]),
        capture,
        ocr,
        lambda: selector,
        editor_factory,
        ManualExecutor(),
        ocr_executor,
    )
    ocr_executor.run_next()  # preload
    window.select(conversation.id)
    window.capture_requested.emit()
    selector.region_selected.emit(ScreenRegion(10, 20, 4, 3))
    assert len(ocr_executor.pending) == 1
    pending_ocr = ocr_executor.pending[0][0]
    shown_before_shutdown = list(window.shown)

    controller.shutdown()

    assert pending_ocr.cancelled()
    assert ocr.images == []
    assert editors == []
    assert window.shown == shown_before_shutdown


def test_open_editor_blocks_capture_and_accept_or_close_releases_it(
    tmp_path: Path,
) -> None:
    application()
    repository = repository_at(tmp_path / "chat.sqlite3")
    conversation = repository.create_conversation("sequential capture")
    attachments = AttachmentStore(
        tmp_path / "attachments",
        repository,
        DataCipher(b"c" * 32),
    )
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    capture = FakeCapture(image)
    ocr = FakeOcr([TranscriptLine(Speaker.PARENT, "OCR")])
    selectors: list[FakeSelector] = []
    editors: list[FakeEditor] = []

    def selector_factory() -> FakeSelector:
        selector = FakeSelector()
        selectors.append(selector)
        return selector

    def editor_factory(
        lines: Sequence[TranscriptLine], notice: str
    ) -> FakeEditor:
        editor = FakeEditor(lines, notice, f"CORRECTED-{len(editors) + 1}")
        editors.append(editor)
        return editor

    ocr_executor = ManualExecutor()
    window = FakeWindow()
    ChatController(
        window,
        repository,
        attachments,
        context_builder(repository),
        RecordingAssistant(repository, ["unused"]),
        capture,
        ocr,
        selector_factory,
        editor_factory,
        ManualExecutor(),
        ocr_executor,
    )
    ocr_executor.run_next()  # preload
    window.select(conversation.id)

    window.capture_requested.emit()
    selectors[0].region_selected.emit(ScreenRegion(10, 20, 4, 3))
    ocr_executor.run_next()
    assert len(editors) == 1
    assert editors[0].shown

    window.capture_requested.emit()
    assert len(selectors) == 1

    editors[0].finished.emit(0)
    window.capture_requested.emit()
    assert len(selectors) == 2
    assert selectors[1].started
    selectors[1].region_selected.emit(ScreenRegion(20, 30, 4, 3))
    ocr_executor.run_next()
    assert len(editors) == 2
    assert editors[1].shown

    window.capture_requested.emit()
    assert len(selectors) == 2

    editors[1].accepted.emit()
    window.capture_requested.emit()
    assert len(selectors) == 3
    assert selectors[2].started


def test_pending_ocr_keeps_single_owner_until_cancel_or_editor_completion(
    tmp_path: Path,
) -> None:
    application()
    repository = repository_at(tmp_path / "chat.sqlite3")
    conversation = repository.create_conversation("single screenshot owner")
    attachments = AttachmentStore(
        tmp_path / "attachments",
        repository,
        DataCipher(b"c" * 32),
    )
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    capture = FakeCapture(image)
    ocr = FakeOcr([TranscriptLine(Speaker.PARENT, "OCR")])
    selectors: list[FakeSelector] = []
    editors: list[FakeEditor] = []

    def selector_factory() -> FakeSelector:
        selector = FakeSelector()
        selectors.append(selector)
        return selector

    def editor_factory(
        lines: Sequence[TranscriptLine], notice: str
    ) -> FakeEditor:
        editor = FakeEditor(lines, notice, "CORRECTED")
        editors.append(editor)
        return editor

    ocr_executor = ManualExecutor()
    window = FakeWindow()
    controller = ChatController(
        window,
        repository,
        attachments,
        context_builder(repository),
        RecordingAssistant(repository, ["unused"]),
        capture,
        ocr,
        selector_factory,
        editor_factory,
        ManualExecutor(),
        ocr_executor,
    )
    ocr_executor.run_next()  # preload
    window.select(conversation.id)

    window.capture_requested.emit()
    selectors[0].region_selected.emit(ScreenRegion(10, 20, 4, 3))
    assert len(ocr_executor.pending) == 1

    window.capture_requested.emit()
    assert len(selectors) == 1
    assert len(ocr_executor.pending) == 1

    pending_ocr, _function, _args = ocr_executor.pending.pop(0)
    pending_ocr.cancel()
    assert editors == []

    window.capture_requested.emit()
    assert len(selectors) == 2
    selectors[1].region_selected.emit(ScreenRegion(20, 30, 4, 3))
    ocr_executor.run_next()
    assert len(ocr.images) == 1
    assert len(editors) == 1
    assert editors[0].shown

    window.capture_requested.emit()
    assert len(selectors) == 2

    editors[0].finished.emit(0)
    window.capture_requested.emit()
    assert len(selectors) == 3
    selectors[2].cancelled.emit()

    window.capture_requested.emit()
    assert len(selectors) == 4
    assert selectors[3].started
    controller.shutdown()
