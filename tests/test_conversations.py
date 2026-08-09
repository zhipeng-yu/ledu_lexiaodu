from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from threading import Event, Thread

import pytest

from lexiaodu.conversations import ConversationRepository
from lexiaodu.local_crypto import DataCipher


class AdvancingClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self._current
        self._current += timedelta(seconds=1)
        return value


@pytest.fixture
def cipher() -> DataCipher:
    return DataCipher(b"c" * 32)


@pytest.fixture
def database_path(tmp_path):
    return tmp_path / "conversations.sqlite3"


@pytest.fixture
def repository(database_path, cipher) -> ConversationRepository:
    return ConversationRepository(database_path, cipher, clock=AdvancingClock())


def test_conversation_lifecycle_returns_immutable_active_records(repository) -> None:
    first = repository.create_conversation("一年级英语")
    second = repository.create_conversation("家长沟通")

    assert repository.list_conversations() == (second, first)
    assert repository.get_conversation(first.id) == first
    with pytest.raises(FrozenInstanceError):
        first.title = "mutated"

    renamed = repository.rename_conversation(first.id, "英语学习计划")

    assert renamed.id == first.id
    assert renamed.title == "英语学习计划"
    assert renamed.updated_at > first.updated_at
    assert repository.search_conversations("学习") == (renamed,)


def test_messages_and_context_never_cross_conversations(repository) -> None:
    first = repository.create_conversation("一年级英语")
    second = repository.create_conversation("一年级英语")
    first_message = repository.append_user_message(
        first.id, "家长担心跟不上 FIRST-MESSAGE", request_id="req-1"
    )
    repository.append_user_message(
        second.id, "家长担心跟不上 SECOND-MESSAGE", request_id="req-2"
    )
    first_fact = repository.save_confirmed_fact(first.id, "FIRST-FACT")
    repository.save_confirmed_fact(second.id, "SECOND-FACT")
    first_summary = repository.save_context_summary(
        first.id,
        "FIRST-SUMMARY",
        start_message_id=first_message.id,
        end_message_id=first_message.id,
        context_version=first.context_version,
    )
    second_message = repository.list_messages(second.id)[0]
    repository.save_context_summary(
        second.id,
        "SECOND-SUMMARY",
        start_message_id=second_message.id,
        end_message_id=second_message.id,
        context_version=second.context_version,
    )

    assert repository.list_messages(first.id) == (first_message,)
    assert repository.list_confirmed_facts(first.id) == (first_fact,)
    assert repository.list_context_summaries(first.id) == (first_summary,)
    assert tuple(
        conversation.id
        for conversation in repository.search_conversations("first-message")
    ) == (first.id,)
    assert all(
        item.conversation_id == first.id
        for item in (
            *repository.list_messages(first.id),
            *repository.list_confirmed_facts(first.id),
            *repository.list_context_summaries(first.id),
        )
    )


def test_user_request_is_persisted_before_processing_and_failure_is_retryable(
    repository,
) -> None:
    conversation = repository.create_conversation("请求状态")
    message = repository.append_user_message(
        conversation.id, "REQUEST-BODY", request_id="request-status"
    )

    assert message.processing_status == "pending"
    assert repository.list_retryable_requests(conversation.id) == ()

    processing = repository.mark_request_processing(
        conversation.id, "request-status", model_metadata="MODEL-SENTINEL"
    )
    assert processing.processing_status == "processing"

    failed = repository.mark_request_failed(conversation.id, "request-status")
    assert failed.processing_status == "failed"
    assert repository.list_retryable_requests(conversation.id) == (failed,)


def test_restart_marks_processing_requests_interrupted(database_path, cipher) -> None:
    first_repository = ConversationRepository(
        database_path, cipher, clock=AdvancingClock()
    )
    conversation = first_repository.create_conversation("重启恢复")
    first_repository.append_user_message(
        conversation.id, "INTERRUPTED-BODY", request_id="restart-request"
    )
    first_repository.mark_request_processing(
        conversation.id, "restart-request", model_metadata="RESTART-MODEL"
    )

    reopened = ConversationRepository(database_path, cipher, clock=AdvancingClock())

    retryable = reopened.list_retryable_requests(conversation.id)
    assert len(retryable) == 1
    assert retryable[0].request_id == "restart-request"
    assert retryable[0].processing_status == "interrupted"


def test_request_and_assistant_result_ids_prevent_duplicate_turns(repository) -> None:
    first = repository.create_conversation("去重一")
    second = repository.create_conversation("去重二")
    repository.append_user_message(first.id, "FIRST-REQUEST", request_id="unique-request")

    with pytest.raises(sqlite3.IntegrityError):
        repository.append_user_message(
            second.id, "SECOND-REQUEST", request_id="unique-request"
        )

    assistant = repository.append_assistant_message(
        first.id,
        "ASSISTANT-RESULT",
        in_reply_to_request_id="unique-request",
        model_metadata="MODEL-RESULT",
    )
    retried = repository.append_assistant_message(
        first.id,
        "SHOULD-NOT-BE-APPENDED",
        in_reply_to_request_id="unique-request",
        model_metadata="OTHER-MODEL",
    )

    assert retried == assistant
    assert repository.list_messages(first.id) == (
        repository.list_messages(first.id)[0],
        assistant,
    )
    assert repository.list_retryable_requests(first.id) == ()


def test_completed_request_cannot_drift_back_into_retry_state(repository) -> None:
    conversation = repository.create_conversation("late callback")
    repository.append_user_message(
        conversation.id, "REQUEST", request_id="completed-request"
    )
    assistant = repository.append_assistant_message(
        conversation.id,
        "RESULT",
        in_reply_to_request_id="completed-request",
    )

    late_failure = repository.mark_request_failed(
        conversation.id, "completed-request"
    )
    retried = repository.append_assistant_message(
        conversation.id,
        "DUPLICATE",
        in_reply_to_request_id="completed-request",
    )

    assert late_failure.processing_status == "completed"
    assert retried == assistant
    assert repository.list_retryable_requests(conversation.id) == ()


def test_child_write_cannot_commit_after_conversation_deletion(
    database_path, cipher, monkeypatch
) -> None:
    writer = ConversationRepository(database_path, cipher)
    deleter = ConversationRepository(database_path, cipher)
    conversation = writer.create_conversation("concurrent deletion")
    writer_validated = Event()
    release_writer = Event()
    deletion_finished = Event()
    errors: list[BaseException] = []
    original_active_check = writer._active_conversation_row

    def pause_after_validation(connection, conversation_id):
        row = original_active_check(connection, conversation_id)
        writer_validated.set()
        assert release_writer.wait(5)
        return row

    monkeypatch.setattr(writer, "_active_conversation_row", pause_after_validation)

    def append_child() -> None:
        try:
            writer.append_user_message(
                conversation.id, "LATE-CHILD", request_id="late-child"
            )
        except BaseException as exc:
            errors.append(exc)

    def delete_parent() -> None:
        try:
            deleter.delete_conversation(conversation.id)
        except BaseException as exc:
            errors.append(exc)
        finally:
            deletion_finished.set()

    writer_thread = Thread(target=append_child)
    writer_thread.start()
    assert writer_validated.wait(5)
    deletion_thread = Thread(target=delete_parent)
    deletion_thread.start()
    deletion_committed_before_release = deletion_finished.wait(0.5)
    release_writer.set()
    writer_thread.join(5)
    deletion_thread.join(5)

    with sqlite3.connect(database_path) as connection:
        child_count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
            (conversation.id,),
        ).fetchone()[0]

    assert not writer_thread.is_alive()
    assert not deletion_thread.is_alive()
    assert errors == []
    assert deletion_committed_before_release is False
    assert child_count == 0


def test_late_request_state_transition_cannot_overwrite_assistant_completion(
    database_path, cipher, monkeypatch
) -> None:
    late_callback = ConversationRepository(database_path, cipher)
    assistant_writer = ConversationRepository(database_path, cipher)
    conversation = late_callback.create_conversation("concurrent status")
    late_callback.append_user_message(
        conversation.id, "REQUEST", request_id="status-race"
    )
    request_read = Event()
    release_late_callback = Event()
    assistant_finished = Event()
    errors: list[BaseException] = []
    original_request_row = late_callback._request_row

    def pause_after_request_read(connection, conversation_id, request_id):
        row = original_request_row(connection, conversation_id, request_id)
        if not request_read.is_set():
            request_read.set()
            assert release_late_callback.wait(5)
        return row

    monkeypatch.setattr(late_callback, "_request_row", pause_after_request_read)

    def mark_failed() -> None:
        try:
            late_callback.mark_request_failed(conversation.id, "status-race")
        except BaseException as exc:
            errors.append(exc)

    def append_assistant() -> None:
        try:
            assistant_writer.append_assistant_message(
                conversation.id,
                "RESULT",
                in_reply_to_request_id="status-race",
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            assistant_finished.set()

    late_thread = Thread(target=mark_failed)
    late_thread.start()
    assert request_read.wait(5)
    assistant_thread = Thread(target=append_assistant)
    assistant_thread.start()
    assistant_committed_before_release = assistant_finished.wait(0.5)
    release_late_callback.set()
    late_thread.join(5)
    assistant_thread.join(5)

    messages = assistant_writer.list_messages(conversation.id)

    assert not late_thread.is_alive()
    assert not assistant_thread.is_alive()
    assert errors == []
    assert assistant_committed_before_release is False
    assert messages[0].processing_status == "completed"
    assert assistant_writer.list_retryable_requests(conversation.id) == ()


def test_concurrent_assistant_retries_return_the_same_persisted_result(
    database_path, cipher, monkeypatch
) -> None:
    first_writer = ConversationRepository(database_path, cipher)
    second_writer = ConversationRepository(database_path, cipher)
    conversation = first_writer.create_conversation("concurrent retry")
    first_writer.append_user_message(
        conversation.id, "REQUEST", request_id="assistant-race"
    )
    first_ready_to_insert = Event()
    release_first_writer = Event()
    second_finished = Event()
    results = []
    errors: list[BaseException] = []
    original_insert = first_writer._insert_message

    def pause_before_assistant_insert(connection, message):
        if message.role == "assistant":
            first_ready_to_insert.set()
            assert release_first_writer.wait(5)
        return original_insert(connection, message)

    monkeypatch.setattr(first_writer, "_insert_message", pause_before_assistant_insert)

    def append(repository, body, finished=None) -> None:
        try:
            results.append(
                repository.append_assistant_message(
                    conversation.id,
                    body,
                    in_reply_to_request_id="assistant-race",
                )
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            if finished is not None:
                finished.set()

    first_thread = Thread(target=append, args=(first_writer, "FIRST"))
    first_thread.start()
    assert first_ready_to_insert.wait(5)
    second_thread = Thread(
        target=append, args=(second_writer, "SECOND", second_finished)
    )
    second_thread.start()
    second_committed_before_release = second_finished.wait(0.5)
    release_first_writer.set()
    first_thread.join(5)
    second_thread.join(5)

    assistant_messages = tuple(
        message
        for message in first_writer.list_messages(conversation.id)
        if message.role == "assistant"
    )

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    assert second_committed_before_release is False
    assert len(results) == 2
    assert results[0] == results[1] == assistant_messages[0]
    assert len(assistant_messages) == 1


def test_business_content_and_model_metadata_are_not_plaintext(
    repository, database_path
) -> None:
    conversation = repository.create_conversation("TITLE-UNIQUE-SENTINEL")
    user_message = repository.append_user_message(
        conversation.id, "MESSAGE-UNIQUE-SENTINEL", request_id="encrypted-request"
    )
    repository.mark_request_processing(
        conversation.id,
        "encrypted-request",
        model_metadata="MODEL-METADATA-UNIQUE-SENTINEL",
    )
    repository.save_confirmed_fact(conversation.id, "FACT-UNIQUE-SENTINEL")
    repository.save_context_summary(
        conversation.id,
        "SUMMARY-UNIQUE-SENTINEL",
        start_message_id=user_message.id,
        end_message_id=user_message.id,
        context_version=conversation.context_version,
    )

    raw = database_path.read_bytes()
    wal_path = database_path.with_name(database_path.name + "-wal")
    if wal_path.exists():
        raw += wal_path.read_bytes()

    for sentinel in (
        b"TITLE-UNIQUE-SENTINEL",
        b"MESSAGE-UNIQUE-SENTINEL",
        b"MODEL-METADATA-UNIQUE-SENTINEL",
        b"FACT-UNIQUE-SENTINEL",
        b"SUMMARY-UNIQUE-SENTINEL",
    ):
        assert sentinel not in raw


def test_delete_hides_tombstone_and_hard_deletes_child_records(
    repository, cipher
) -> None:
    deleted = repository.create_conversation("DELETE-TITLE-SENTINEL")
    kept = repository.create_conversation("keep")
    kept_message = repository.append_user_message(
        kept.id, "KEEP-MESSAGE", request_id="keep-request"
    )
    message = repository.append_user_message(
        deleted.id, "DELETE-MESSAGE-SENTINEL", request_id="delete-request"
    )
    repository.save_confirmed_fact(deleted.id, "DELETE-FACT-SENTINEL")
    repository.save_context_summary(
        deleted.id,
        "DELETE-SUMMARY-SENTINEL",
        start_message_id=message.id,
        end_message_id=message.id,
        context_version=deleted.context_version,
    )

    repository.delete_conversation(deleted.id)

    assert tuple(
        conversation.id for conversation in repository.list_conversations()
    ) == (kept.id,)
    assert repository.search_conversations("DELETE") == ()
    with pytest.raises(KeyError):
        repository.get_conversation(deleted.id)
    with pytest.raises(KeyError):
        repository.list_messages(deleted.id)
    assert repository.list_messages(kept.id) == (kept_message,)

    with repository._connect() as connection:
        tombstone = connection.execute(
            "SELECT encrypted_title, status, deleted_at FROM conversations WHERE id = ?",
            (deleted.id,),
        ).fetchone()
        child_counts = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE conversation_id = ?",
                (deleted.id,),
            ).fetchone()[0]
            for table in ("messages", "confirmed_facts", "context_summaries")
        }
        cleanup_rows = connection.execute(
            """
            SELECT encrypted_payload FROM cleanup_jobs
            WHERE conversation_id = ? AND kind = 'delete_learning_candidates'
            """,
            (deleted.id,),
        ).fetchall()

    assert tombstone["status"] == "deleted"
    assert tombstone["deleted_at"] is not None
    assert cipher.decrypt(tombstone["encrypted_title"]) == b""
    assert child_counts == {"messages": 0, "confirmed_facts": 0, "context_summaries": 0}
    assert len(cleanup_rows) == 1
    assert cipher.decrypt(cleanup_rows[0][0]).decode() == deleted.id


def test_repository_enables_foreign_keys_wal_and_secure_delete(database_path, cipher) -> None:
    repository = ConversationRepository(database_path, cipher)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        foreign_key_rows = connection.execute(
            "PRAGMA foreign_key_list(messages)"
        ).fetchall()
    with repository._connect() as configured_connection:
        assert configured_connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert configured_connection.execute("PRAGMA secure_delete").fetchone()[0] == 1

    assert any(row[2] == "conversations" for row in foreign_key_rows)
