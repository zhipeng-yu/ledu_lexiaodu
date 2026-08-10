from __future__ import annotations

from concurrent.futures import Executor, Future
from typing import Protocol
from uuid import uuid4

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QInputDialog, QMessageBox

from lexiaodu.chat_window import (
    ChatConversationView,
    ChatMainWindow,
    ChatTurnView,
)
from lexiaodu.chat_context import ContextBuilder, ContextPackage
from lexiaodu.chat_repository import ConversationRepository, Message


class ConversationAssistant(Protocol):
    def respond(self, context: ContextPackage, request_id: str) -> str: ...


class ChatController(QObject):
    """Orchestrate persistence and assistant work."""

    _assistant_completed = Signal(object)

    def __init__(
        self,
        window: ChatMainWindow,
        repository: ConversationRepository,
        context_builder: ContextBuilder,
        assistant: ConversationAssistant,
        assistant_executor: Executor,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._repository = repository
        self._context_builder = context_builder
        self._assistant = assistant
        self._assistant_executor = assistant_executor
        self._shutting_down = False

        self._assistant_completed.connect(self._handle_assistant_completion)
        window.create_conversation_requested.connect(self.create_conversation)
        window.conversation_selected.connect(self.show_conversation)
        window.rename_conversation_requested.connect(self.rename_conversation)
        window.delete_conversation_requested.connect(self.delete_conversation)
        window.search_requested.connect(self.search_conversations)
        window.send_requested.connect(self.send_message)
        window.retry_requested.connect(self.retry_request)

        self._refresh_conversations()

    def _refresh_conversations(
        self,
        *,
        selected_id: str | None = None,
    ) -> None:
        self._window.set_conversations(
            tuple(
                ChatConversationView(conversation.id, conversation.title)
                for conversation in self._repository.list_conversations()
            )
        )
        if selected_id is not None:
            self._window.select_conversation(selected_id)

    @Slot()
    def create_conversation(self) -> None:
        if self._shutting_down:
            return
        conversation = self._repository.create_conversation("新会话")
        self._refresh_conversations(selected_id=conversation.id)

    @Slot(str)
    def rename_conversation(self, conversation_id: str) -> None:
        if self._shutting_down:
            return
        try:
            conversation = self._repository.get_conversation(conversation_id)
        except KeyError:
            self._refresh_conversations()
            return
        title, accepted = QInputDialog.getText(
            self._window,
            "重命名会话",
            "会话名称",
            text=conversation.title,
        )
        title = title.strip()
        if not accepted or not title:
            return
        self._repository.rename_conversation(conversation_id, title)
        self._refresh_conversations(selected_id=conversation_id)

    @Slot(str)
    def delete_conversation(self, conversation_id: str) -> None:
        if self._shutting_down:
            return
        answer = QMessageBox.question(
            self._window,
            "删除会话",
            "确认删除这个会话吗？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._repository.delete_conversation(conversation_id)
        self._refresh_conversations()

    @Slot(str)
    def search_conversations(self, query: str) -> None:
        if self._shutting_down:
            return
        conversations = (
            self._repository.search_conversations(query)
            if query.strip()
            else self._repository.list_conversations()
        )
        self._window.set_conversations(
            tuple(
                ChatConversationView(conversation.id, conversation.title)
                for conversation in conversations
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
            context = self._context_builder.build(conversation_id)
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
        if (
            not self._shutting_down
            and self._window.active_conversation_id == conversation_id
        ):
            self.show_conversation(conversation_id)

    @Slot()
    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._assistant_executor.shutdown(wait=True, cancel_futures=True)
