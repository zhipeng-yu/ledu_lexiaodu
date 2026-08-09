from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QListWidget

from lexiaodu.advice import AdviceSuggestion
from lexiaodu.attachments import AttachmentStore
from lexiaodu.chat import SuggestionCard
from lexiaodu.chat_controller import ChatController
from lexiaodu.chat_window import ChatMainWindow
from lexiaodu.context import ContextBuilder, ContextPackage
from lexiaodu.conversations import ConversationRepository
from lexiaodu.knowledge import KnowledgeType, SearchResult
from lexiaodu.local_crypto import DataCipher
from lexiaodu.risk import RiskAssessment, RiskLevel, TransferStatus


_APPLICATION: QApplication | None = None


def _application() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


class _TestKeyProtector:
    def protect(self, value: bytes) -> bytes:
        return b"test-envelope:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(b"test-envelope:"):
            raise ValueError("invalid test envelope")
        return value.removeprefix(b"test-envelope:")[::-1]


class _ImmediateExecutor:
    def __init__(self) -> None:
        self.shutdown_calls: list[tuple[bool, bool]] = []

    def submit(
        self,
        function: Callable[..., Any],
        *args: Any,
    ) -> Future[Any]:
        future: Future[Any] = Future()
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(function(*args))
            except BaseException as exc:
                future.set_exception(exc)
        return future

    def shutdown(
        self,
        *,
        wait: bool = True,
        cancel_futures: bool = False,
    ) -> None:
        self.shutdown_calls.append((wait, cancel_futures))


class _FakeAssistant:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[tuple[ContextPackage, str]] = []

    def respond(self, context: ContextPackage, request_id: str) -> str:
        self.calls.append((context, request_id))
        return self.answer


class _InertOcr:
    def preload(self) -> None:
        pass


class _UnusedCapture:
    def capture(self, _region: Any) -> Any:
        raise AssertionError("capture is not part of this recovery session")


def _suggestion() -> AdviceSuggestion:
    return AdviceSuggestion(
        suggestion_id="reply-card-fictional-001",
        concern_summary="虚构家长希望了解请假流程。",
        wechat_reply="您好，这是虚构演示回复。请以审核后的制度为准。",
        facts=(
            SearchResult(
                knowledge_type=KnowledgeType.POLICY,
                document_name="虚构请假制度.txt",
                locator="演示章节",
                evidence="仅用于自动化测试的虚构依据。",
                score=2.0,
            ),
        ),
        risk=RiskAssessment(
            level=RiskLevel.LOW,
            warnings=("请人工核对。",),
            transfer_status=TransferStatus.NOT_REQUIRED,
        ),
    )


def _controller(
    window: ChatMainWindow,
    repository: ConversationRepository,
    attachments: AttachmentStore,
    assistant: _FakeAssistant,
) -> ChatController:
    return ChatController(
        window,
        repository,
        attachments,
        ContextBuilder(
            repository,
            recent_limit=20,
            related_limit=10,
            character_budget=10_000,
        ),
        assistant,
        _UnusedCapture(),
        _InertOcr(),
        lambda: (_ for _ in ()).throw(
            AssertionError("selector is not part of this recovery session")
        ),
        lambda _lines, _notice: (_ for _ in ()).throw(
            AssertionError("editor is not part of this recovery session")
        ),
        _ImmediateExecutor(),
        _ImmediateExecutor(),
    )


def _dispose(
    application: QApplication,
    controller: ChatController,
    window: ChatMainWindow,
) -> None:
    controller.shutdown()
    window.close()
    window.deleteLater()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def test_restart_restores_isolated_messages_attachment_text_and_reply_card_then_delete_cleans_all(
    tmp_path: Path,
) -> None:
    application = _application()
    key_path = tmp_path / "chat.key"
    database_path = tmp_path / "chat.sqlite3"
    attachment_dir = tmp_path / "attachments"
    protector = _TestKeyProtector()
    cipher = DataCipher.open(key_path, protector)
    repository = ConversationRepository(database_path, cipher)
    attachments = AttachmentStore(attachment_dir, repository, cipher)
    first = repository.create_conversation("一年级英语咨询 A")
    second = repository.create_conversation("一年级英语咨询 B")
    cross_thread_sentinel = "-".join(
        ("FICTIONAL", "SECOND", "THREAD", "ONLY", "7KQ")
    )
    repository.append_user_message(
        second.id,
        cross_thread_sentinel,
        request_id="second-request",
    )

    image = QImage(3, 2, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    attachment = attachments.save_image(first.id, image)
    corrected_text = "虚构 OCR 校正文案，只属于会话 A。"
    attachments.save_corrected_text(first.id, attachment.id, corrected_text)
    suggestion = _suggestion()
    repository.save_reply_card(first.id, suggestion)

    first_window = ChatMainWindow()
    first_assistant = _FakeAssistant("虚构的离线演示回答。")
    first_controller = _controller(
        first_window,
        repository,
        attachments,
        first_assistant,
    )
    assert first_window.select_conversation(first.id)
    first_controller.send_message("请继续这个虚构会话。")

    assert len(first_assistant.calls) == 1
    rendered_context = first_assistant.calls[0][0].render_for_model()
    assert corrected_text in rendered_context
    assert cross_thread_sentinel not in rendered_context
    encrypted_path = attachment.encrypted_path
    _dispose(application, first_controller, first_window)
    del first_controller, first_window, repository, attachments, cipher

    reopened_cipher = DataCipher.open(key_path, protector)
    reopened_repository = ConversationRepository(database_path, reopened_cipher)
    reopened_attachments = AttachmentStore(
        attachment_dir,
        reopened_repository,
        reopened_cipher,
    )
    assert [message.body for message in reopened_repository.list_messages(first.id)] == [
        "请继续这个虚构会话。",
        "虚构的离线演示回答。",
    ]
    assert reopened_attachments.list_for_conversation(first.id)[0].corrected_text == (
        corrected_text
    )
    restored_cards = reopened_repository.list_reply_cards(first.id)
    assert len(restored_cards) == 1
    assert restored_cards[0].suggestion == suggestion

    restored_window = ChatMainWindow()
    restored_assistant = _FakeAssistant("must not run during restore")
    restored_controller = _controller(
        restored_window,
        reopened_repository,
        reopened_attachments,
        restored_assistant,
    )
    assert restored_window.select_conversation(first.id)
    timeline = restored_window.findChild(QListWidget, "messageTimeline")
    assert timeline is not None
    assert timeline.findChild(SuggestionCard) is not None
    assert restored_assistant.calls == []

    raw_database_files = tuple(tmp_path.glob("chat.sqlite3*"))
    for path in raw_database_files:
        payload = path.read_bytes()
        assert corrected_text.encode("utf-8") not in payload
        assert suggestion.wechat_reply.encode("utf-8") not in payload
        assert cross_thread_sentinel.encode("utf-8") not in payload

    reopened_repository.delete_conversation(first.id)
    assert reopened_attachments.run_cleanup_jobs(first.id) == 1
    assert not encrypted_path.exists()
    _dispose(application, restored_controller, restored_window)
    del restored_controller, restored_window, reopened_repository, reopened_attachments

    final_cipher = DataCipher.open(key_path, protector)
    final_repository = ConversationRepository(database_path, final_cipher)
    assert tuple(item.id for item in final_repository.list_conversations()) == (
        second.id,
    )
    with pytest.raises(KeyError):
        final_repository.list_messages(first.id)
    with pytest.raises(KeyError):
        final_repository.list_reply_cards(first.id)
