from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Callable, Sequence
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from lexiaodu.chat_context import ContextBuilder, ContextPackage
from lexiaodu.chat_controller import ChatController
from lexiaodu.chat_repository import ConversationRepository
from lexiaodu.chat_window import ChatConversationView, ChatTurnView
from lexiaodu.local_crypto import DataCipher


class FakeWindow(QObject):
    create_conversation_requested = Signal()
    conversation_selected = Signal(str)
    rename_conversation_requested = Signal(str)
    delete_conversation_requested = Signal(str)
    search_requested = Signal(str)
    send_requested = Signal(str)
    retry_requested = Signal(str)

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

    def select_conversation(self, conversation_id: str) -> bool:
        if not any(item.id == conversation_id for item in self.conversations):
            return False
        self.select(conversation_id)
        return True

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


def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def repository_at(path: Path) -> ConversationRepository:
    return ConversationRepository(path, DataCipher(b"c" * 32))


def context_builder(repository: Any) -> ContextBuilder:
    return ContextBuilder(
        repository,
        character_budget=10_000,
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
    window = FakeWindow()
    ChatController(
        window,
        repository,
        context_builder(repository),
        assistant,
        assistant_executor,
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
    window = FakeWindow()
    ChatController(
        window,
        repository,
        context_builder(repository),
        assistant,
        assistant_executor,
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
    window = FakeWindow()
    ChatController(
        window,
        repository,
        context_builder(repository),
        assistant,
        assistant_executor,
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


@pytest.mark.parametrize(
    "mark_processing",
    [False, True],
    ids=["pending", "processing"],
)
def test_reconstruction_shows_unfinished_request_without_auto_sending(
    tmp_path: Path, mark_processing: bool
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
    if mark_processing:
        first_repository.mark_request_processing(
            conversation.id,
            "restart-request",
        )

    reopened = repository_at(database_path)
    assistant = RecordingAssistant(reopened, ["MUST-NOT-RUN"])
    assistant_executor = ManualExecutor()
    window = FakeWindow()
    ChatController(
        window,
        reopened,
        context_builder(reopened),
        assistant,
        assistant_executor,
    )

    window.select(conversation.id)

    assert assistant.calls == []
    assert assistant_executor.pending == []
    assert len(window.turns) == 1
    assert window.turns[0].text == "INTERRUPTED-QUESTION"
    assert window.turns[0].status == "interrupted"
    assert window.turns[0].request_id == "restart-request"


def _workspace_controller(
    tmp_path: Path,
) -> tuple[ChatController, FakeWindow, ConversationRepository]:
    repository = repository_at(tmp_path / "chat.sqlite3")
    window = FakeWindow()
    controller = ChatController(
        window,
        repository,
        context_builder(repository),
        RecordingAssistant(repository, []),
        ManualExecutor(),
    )
    return controller, window, repository


def test_create_intent_persists_and_selects_a_new_conversation(
    tmp_path: Path,
) -> None:
    application()
    controller, window, repository = _workspace_controller(tmp_path)

    window.create_conversation_requested.emit()

    conversations = repository.list_conversations()
    assert len(conversations) == 1
    assert conversations[0].title == "新会话"
    assert window.active_conversation_id == conversations[0].id
    controller.shutdown()


def test_search_intent_filters_titles_and_clearing_restores_all(
    tmp_path: Path,
) -> None:
    application()
    repository = repository_at(tmp_path / "chat.sqlite3")
    repository.create_conversation("英语开口练习")
    repository.create_conversation("数学计算练习")
    controller, window, repository = _workspace_controller(tmp_path)

    window.search_requested.emit("英语")
    assert [item.title for item in window.conversations] == ["英语开口练习"]

    window.search_requested.emit("")
    assert {item.title for item in window.conversations} == {
        "英语开口练习",
        "数学计算练习",
    }
    controller.shutdown()


def test_rename_intent_uses_entered_title_and_keeps_selection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application()
    repository = repository_at(tmp_path / "chat.sqlite3")
    conversation = repository.create_conversation("旧标题")
    controller, window, repository = _workspace_controller(tmp_path)
    window.select(conversation.id)
    monkeypatch.setattr(
        "lexiaodu.chat_controller.QInputDialog.getText",
        lambda *_args, **_kwargs: ("新标题", True),
    )

    window.rename_conversation_requested.emit(conversation.id)

    assert repository.get_conversation(conversation.id).title == "新标题"
    assert window.active_conversation_id == conversation.id
    controller.shutdown()


def test_delete_intent_removes_conversation_and_refreshes_ui(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application()
    repository = repository_at(tmp_path / "chat.sqlite3")
    conversation = repository.create_conversation("待删除")
    controller, window, repository = _workspace_controller(tmp_path)
    window.select(conversation.id)
    monkeypatch.setattr(
        "lexiaodu.chat_controller.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    window.delete_conversation_requested.emit(conversation.id)

    assert repository.list_conversations() == ()
    assert window.conversations == ()
    assert window.active_conversation_id is None
    controller.shutdown()
