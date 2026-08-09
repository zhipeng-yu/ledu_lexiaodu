from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Executor, Future
from typing import Protocol
from uuid import uuid4

from PySide6.QtCore import QObject, Signal, Slot

from lexiaodu.attachments import AttachmentStore
from lexiaodu.capture import ScreenCapture
from lexiaodu.chat_window import (
    ChatConversationView,
    ChatMainWindow,
    ChatTurnView,
)
from lexiaodu.context import ContextBuilder, ContextPackage
from lexiaodu.conversations import ConversationRepository, Message
from lexiaodu.domain import ScreenRegion
from lexiaodu.editor import TranscriptEditor
from lexiaodu.ocr import OcrEngine, OcrError, TranscriptLine
from lexiaodu.selection import SelectionOverlay


class ConversationAssistant(Protocol):
    def respond(self, context: ContextPackage, request_id: str) -> str: ...


class ChatController(QObject):
    """Orchestrate persistence, assistant work, and screenshot drafts."""

    _assistant_completed = Signal(object)
    _ocr_completed = Signal(object)

    def __init__(
        self,
        window: ChatMainWindow,
        repository: ConversationRepository,
        attachments: AttachmentStore,
        context_builder: ContextBuilder,
        assistant: ConversationAssistant,
        capture: ScreenCapture,
        ocr: OcrEngine,
        selector_factory: Callable[[], SelectionOverlay],
        editor_factory: Callable[
            [Sequence[TranscriptLine], str], TranscriptEditor
        ],
        assistant_executor: Executor,
        ocr_executor: Executor,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._repository = repository
        self._attachments = attachments
        self._context_builder = context_builder
        self._assistant = assistant
        self._capture = capture
        self._ocr = ocr
        self._selector_factory = selector_factory
        self._editor_factory = editor_factory
        self._assistant_executor = assistant_executor
        self._ocr_executor = ocr_executor
        self._selector: SelectionOverlay | None = None
        self._editor: TranscriptEditor | None = None
        self._shutting_down = False

        self._assistant_completed.connect(self._handle_assistant_completion)
        self._ocr_completed.connect(self._handle_ocr_completion)
        window.conversation_selected.connect(self.show_conversation)
        window.send_requested.connect(self.send_message)
        window.retry_requested.connect(self.retry_request)
        window.capture_requested.connect(self.start_capture)

        self._refresh_conversations()
        self._ocr_executor.submit(self._preload_ocr)

    def _refresh_conversations(self) -> None:
        self._window.set_conversations(
            tuple(
                ChatConversationView(conversation.id, conversation.title)
                for conversation in self._repository.list_conversations()
            )
        )

    @Slot(str)
    def show_conversation(self, conversation_id: str) -> None:
        messages = self._repository.list_messages(conversation_id)
        self._window.show_conversation(
            conversation_id,
            tuple(self._turn_view(message) for message in messages),
        )

    @staticmethod
    def _turn_view(message: Message) -> ChatTurnView:
        return ChatTurnView(
            id=message.id,
            role=message.role,
            text=message.body,
            request_id=message.request_id,
            status=message.processing_status,
        )

    @Slot(str)
    def send_message(self, text: str) -> None:
        conversation_id = self._window.active_conversation_id
        body = text.strip()
        if conversation_id is None or not body or self._shutting_down:
            return
        self._start_new_request(
            conversation_id,
            body,
            request_id=uuid4().hex,
            kind="text",
        )

    def _start_new_request(
        self,
        conversation_id: str,
        body: str,
        *,
        request_id: str,
        kind: str,
    ) -> None:
        self._repository.append_user_message(
            conversation_id,
            body,
            request_id=request_id,
            kind=kind,
        )
        self._show_if_active(conversation_id)
        self._dispatch_request(conversation_id, request_id, body)

    @Slot(str)
    def retry_request(self, request_id: str) -> None:
        conversation_id = self._window.active_conversation_id
        if conversation_id is None or self._shutting_down:
            return
        request = next(
            (
                candidate
                for candidate in self._repository.list_retryable_requests(
                    conversation_id
                )
                if candidate.request_id == request_id
            ),
            None,
        )
        if request is None:
            return
        self._dispatch_request(conversation_id, request_id, request.body)

    def _dispatch_request(
        self,
        conversation_id: str,
        request_id: str,
        body: str,
    ) -> None:
        try:
            request = self._repository.mark_request_processing(
                conversation_id,
                request_id,
            )
            if request.processing_status == "completed":
                return
            context = self._context_builder.build(conversation_id, body)
            future = self._assistant_executor.submit(
                self._assistant.respond,
                context,
                request_id,
            )
        except Exception:
            self._fail_request(conversation_id, request_id)
            return
        future.add_done_callback(
            lambda completed,
            owner=conversation_id,
            owner_request=request_id: self._assistant_completed.emit(
                (owner, owner_request, completed)
            )
        )

    @Slot(object)
    def _handle_assistant_completion(
        self,
        result: tuple[str, str, Future[str]],
    ) -> None:
        conversation_id, request_id, future = result
        try:
            body = future.result()
            self._repository.append_assistant_message(
                conversation_id,
                body,
                in_reply_to_request_id=request_id,
            )
        except Exception:
            self._fail_request(conversation_id, request_id)
            return
        self._show_if_active(conversation_id)

    def _fail_request(self, conversation_id: str, request_id: str) -> None:
        try:
            self._repository.mark_request_failed(conversation_id, request_id)
        except KeyError:
            return
        self._show_if_active(conversation_id)

    def _show_if_active(self, conversation_id: str) -> None:
        if self._window.active_conversation_id == conversation_id:
            self.show_conversation(conversation_id)

    @Slot()
    def start_capture(self) -> None:
        conversation_id = self._window.active_conversation_id
        if (
            conversation_id is None
            or self._selector is not None
            or self._shutting_down
        ):
            return
        request_id = uuid4().hex
        selector = self._selector_factory()
        self._selector = selector
        selector.region_selected.connect(
            lambda region,
            owner=conversation_id,
            owner_request=request_id: self._capture_region(
                owner,
                owner_request,
                region,
            )
        )
        selector.cancelled.connect(self._cancel_capture)
        selector.start()

    @Slot()
    def _cancel_capture(self) -> None:
        self._dispose_selector()

    def _dispose_selector(self) -> None:
        if self._selector is None:
            return
        selector = self._selector
        self._selector = None
        selector.hide()
        selector.deleteLater()

    def _capture_region(
        self,
        conversation_id: str,
        request_id: str,
        region: ScreenRegion,
    ) -> None:
        self._dispose_selector()
        result = self._capture.capture(region)
        attachment = self._attachments.save_image(
            conversation_id,
            result.image,
        )
        try:
            future = self._ocr_executor.submit(
                self._ocr.recognize,
                result.image,
            )
        except Exception:
            return
        future.add_done_callback(
            lambda completed,
            owner=conversation_id,
            owner_request=request_id,
            attachment_id=attachment.id: self._ocr_completed.emit(
                (owner, owner_request, attachment_id, completed)
            )
        )

    @Slot(object)
    def _handle_ocr_completion(
        self,
        result: tuple[str, str, str, Future[list[TranscriptLine]]],
    ) -> None:
        conversation_id, request_id, attachment_id, future = result
        try:
            lines = future.result()
            notice = "请核对 OCR 文字和发言人。"
        except OcrError as exc:
            lines = []
            notice = f"{exc}。请在下方手动粘贴文字。"
        except Exception as exc:
            lines = []
            notice = f"OCR 识别失败：{exc}。请在下方手动粘贴文字。"
        editor = self._editor_factory(lines, notice)
        editor.accepted.connect(
            lambda owner=conversation_id,
            owner_request=request_id,
            owner_attachment=attachment_id,
            current_editor=editor: self._accept_correction(
                owner,
                owner_request,
                owner_attachment,
                current_editor,
            )
        )
        self._editor = editor
        editor.show()

    def _accept_correction(
        self,
        conversation_id: str,
        request_id: str,
        attachment_id: str,
        editor: TranscriptEditor,
    ) -> None:
        corrected_text = editor.corrected_transcript().text.strip()
        if not corrected_text or self._shutting_down:
            return
        self._attachments.save_corrected_text(
            conversation_id,
            attachment_id,
            corrected_text,
        )
        self._start_new_request(
            conversation_id,
            corrected_text,
            request_id=request_id,
            kind="screenshot",
        )

    def _preload_ocr(self) -> None:
        try:
            self._ocr.preload()
        except OcrError:
            pass

    @Slot()
    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._dispose_selector()
        self._assistant_executor.shutdown(wait=True, cancel_futures=True)
        self._ocr_executor.shutdown(wait=True, cancel_futures=True)
