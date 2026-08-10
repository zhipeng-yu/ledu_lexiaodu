from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError

import pytest

from lexiaodu.chat_repository import ConversationRepository
from lexiaodu.local_crypto import DataCipher


@pytest.fixture
def cipher() -> DataCipher:
    return DataCipher(b"c" * 32)


@pytest.fixture
def database_path(tmp_path):
    return tmp_path / "chat.sqlite3"


def test_conversation_messages_are_encrypted_isolated_and_searchable(
    database_path,
    cipher,
) -> None:
    repository = ConversationRepository(database_path, cipher)
    first = repository.create_conversation("英语咨询")
    second = repository.create_conversation("数学咨询")
    first_message = repository.append_user_message(
        first.id,
        "FIRST-PRIVATE-CONTENT",
        request_id="first-request",
    )
    repository.append_user_message(
        second.id,
        "SECOND-PRIVATE-CONTENT",
        request_id="second-request",
    )

    assert repository.list_messages(first.id) == (first_message,)
    assert tuple(
        conversation.id
        for conversation in repository.search_conversations("FIRST-PRIVATE")
    ) == (first.id,)
    assert b"FIRST-PRIVATE-CONTENT" not in database_path.read_bytes()
    with pytest.raises(FrozenInstanceError):
        first.title = "changed"


def test_restart_interrupts_pending_requests_without_automatic_completion(
    database_path,
    cipher,
) -> None:
    repository = ConversationRepository(database_path, cipher)
    conversation = repository.create_conversation("restart")
    repository.append_user_message(
        conversation.id,
        "等待恢复",
        request_id="stable-request",
    )
    repository.mark_request_processing(conversation.id, "stable-request")

    reopened = ConversationRepository(database_path, cipher)

    retryable = reopened.list_retryable_requests(conversation.id)
    assert len(retryable) == 1
    assert retryable[0].request_id == "stable-request"
    assert retryable[0].processing_status == "interrupted"


def test_assistant_append_is_idempotent_and_completes_request(
    database_path,
    cipher,
) -> None:
    repository = ConversationRepository(database_path, cipher)
    conversation = repository.create_conversation("idempotent")
    repository.append_user_message(conversation.id, "问题", request_id="request")

    first = repository.append_assistant_message(
        conversation.id,
        "第一次回答",
        in_reply_to_request_id="request",
    )
    second = repository.append_assistant_message(
        conversation.id,
        "不应覆盖",
        in_reply_to_request_id="request",
    )

    assert second == first
    assert tuple(message.body for message in repository.list_messages(conversation.id)) == (
        "问题",
        "第一次回答",
    )
    assert repository.list_retryable_requests(conversation.id) == ()


def test_reopen_removes_legacy_screenshot_content_and_tables(
    database_path,
    cipher,
) -> None:
    repository = ConversationRepository(database_path, cipher)
    conversation = repository.create_conversation("legacy cleanup")
    repository.append_user_message(
        conversation.id,
        "保留的普通消息",
        request_id="text-request",
    )
    repository.append_user_message(
        conversation.id,
        "必须删除的 OCR 校正文案",
        request_id="screenshot-request",
        kind="screenshot",
    )
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS attachments(id TEXT);
            CREATE TABLE IF NOT EXISTS corrected_ocr_texts(id TEXT);
            CREATE TABLE IF NOT EXISTS reply_cards(id TEXT);
            CREATE TABLE IF NOT EXISTS cleanup_jobs(id TEXT);
            """
        )

    reopened = ConversationRepository(database_path, cipher)

    assert tuple(message.body for message in reopened.list_messages(conversation.id)) == (
        "保留的普通消息",
    )
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert not tables & {
        "attachments",
        "corrected_ocr_texts",
        "reply_cards",
        "cleanup_jobs",
    }


def test_delete_physically_removes_conversation_and_messages(database_path, cipher) -> None:
    repository = ConversationRepository(database_path, cipher)
    conversation = repository.create_conversation("delete")
    repository.append_user_message(conversation.id, "删除正文", request_id="delete")

    repository.delete_conversation(conversation.id)

    assert repository.list_conversations() == ()
    with pytest.raises(KeyError):
        repository.get_conversation(conversation.id)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
