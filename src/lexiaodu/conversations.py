from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from lexiaodu.advice import AdviceSuggestion
from lexiaodu.knowledge import KnowledgeType, SearchResult
from lexiaodu.local_crypto import DataCipher
from lexiaodu.risk import RiskAssessment, RiskLevel, TransferStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    title: str
    status: str
    context_version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    conversation_id: str
    role: str
    kind: str
    body: str
    request_id: str | None
    in_reply_to_request_id: str | None
    processing_status: str
    created_at: datetime
    model_metadata: str | None = None
    content_revision: int = 1

    @property
    def text(self) -> str:
        return self.body


@dataclass(frozen=True, slots=True)
class ConfirmedFact:
    id: str
    conversation_id: str
    body: str
    created_at: datetime

    @property
    def text(self) -> str:
        return self.body


@dataclass(frozen=True, slots=True)
class ContextSummary:
    id: str
    conversation_id: str
    body: str
    start_message_id: str
    end_message_id: str
    context_version: int
    created_at: datetime

    @property
    def text(self) -> str:
        return self.body


@dataclass(frozen=True, slots=True)
class PendingRequest:
    conversation_id: str
    request_id: str
    message_id: str
    body: str
    processing_status: str
    created_at: datetime
    model_metadata: str | None = None

    @property
    def text(self) -> str:
        return self.body

    @property
    def status(self) -> str:
        return self.processing_status


@dataclass(frozen=True, slots=True)
class Attachment:
    id: str
    conversation_id: str
    encrypted_path: Path
    encrypted_data_key: bytes
    corrected_text: str | None
    created_at: datetime

    @property
    def text(self) -> str:
        return self.corrected_text or ""


@dataclass(frozen=True, slots=True)
class ConversationContextSnapshot:
    conversation: Conversation
    messages: tuple[Message, ...]
    confirmed_facts: tuple[ConfirmedFact, ...]
    context_summaries: tuple[ContextSummary, ...]
    attachment_texts: tuple[Attachment, ...]


@dataclass(frozen=True, slots=True)
class CleanupJob:
    id: str
    conversation_id: str
    kind: str
    payload: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReplyCard:
    id: str
    conversation_id: str
    suggestion: AdviceSuggestion
    created_at: datetime


class ConversationRepository:
    def __init__(
        self,
        database_path: str | Path,
        cipher: DataCipher,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._cipher = cipher
        self._clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    @staticmethod
    def _begin_write(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    encrypted_title BLOB NOT NULL,
                    status TEXT NOT NULL,
                    context_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    role TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    encrypted_body BLOB NOT NULL,
                    request_id TEXT UNIQUE,
                    in_reply_to_request_id TEXT UNIQUE,
                    processing_status TEXT NOT NULL,
                    encrypted_model_metadata BLOB,
                    created_at TEXT NOT NULL,
                    append_order INTEGER NOT NULL,
                    content_revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS messages_by_conversation
                    ON messages(conversation_id, created_at, id);
                CREATE TABLE IF NOT EXISTS confirmed_facts (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    encrypted_body BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS confirmed_facts_by_conversation
                    ON confirmed_facts(conversation_id, created_at, id);
                CREATE TABLE IF NOT EXISTS context_summaries (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    encrypted_body BLOB NOT NULL,
                    start_message_id TEXT NOT NULL,
                    end_message_id TEXT NOT NULL,
                    context_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS summaries_by_conversation
                    ON context_summaries(conversation_id, created_at, id);
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    encrypted_path BLOB NOT NULL,
                    encrypted_data_key BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS attachments_by_conversation
                    ON attachments(conversation_id, created_at, id);
                CREATE TABLE IF NOT EXISTS corrected_ocr_texts (
                    attachment_id TEXT PRIMARY KEY REFERENCES attachments(id),
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    encrypted_text BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS corrected_ocr_by_conversation
                    ON corrected_ocr_texts(conversation_id, created_at, attachment_id);
                CREATE TABLE IF NOT EXISTS cleanup_jobs (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    kind TEXT NOT NULL,
                    encrypted_payload BLOB NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS cleanup_jobs_by_conversation
                    ON cleanup_jobs(conversation_id, status, created_at, id);
                CREATE TABLE IF NOT EXISTS reply_cards (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    encrypted_payload BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS reply_cards_by_conversation
                    ON reply_cards(conversation_id, created_at, id);
                """
            )
            self._ensure_message_columns(connection)
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS messages_by_append_order
                ON messages(conversation_id, append_order)
                """
            )
            connection.execute(
                """
                UPDATE messages
                SET processing_status = 'interrupted'
                WHERE role = 'user'
                    AND processing_status IN ('pending', 'processing')
                """
            )

    def create_conversation(self, title: str) -> Conversation:
        now = self._now()
        conversation = Conversation(
            id=uuid4().hex,
            title=title,
            status="active",
            context_version=1,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            self._begin_write(connection)
            connection.execute(
                """
                INSERT INTO conversations(
                    id, encrypted_title, status, context_version,
                    created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    conversation.id,
                    self._encrypt_text(title),
                    conversation.status,
                    conversation.context_version,
                    self._format_time(now),
                    self._format_time(now),
                ),
            )
        return conversation

    def get_conversation(self, conversation_id: str) -> Conversation:
        with self._connect() as connection:
            row = self._active_conversation_row(connection, conversation_id)
        return self._conversation_from_row(row)

    def list_conversations(self) -> tuple[Conversation, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversations
                WHERE deleted_at IS NULL
                ORDER BY updated_at DESC, created_at DESC, id DESC
                """
            ).fetchall()
        return tuple(self._conversation_from_row(row) for row in rows)

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        now = self._now()
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            connection.execute(
                """
                UPDATE conversations
                SET encrypted_title = ?, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (self._encrypt_text(title), self._format_time(now), conversation_id),
            )
            row = self._active_conversation_row(connection, conversation_id)
        return self._conversation_from_row(row)

    def search_conversations(self, query: str) -> tuple[Conversation, ...]:
        normalized_query = query.casefold()
        matches: list[Conversation] = []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversations
                WHERE deleted_at IS NULL
                ORDER BY updated_at DESC, created_at DESC, id DESC
                """
            ).fetchall()
            for row in rows:
                conversation = self._conversation_from_row(row)
                if normalized_query in conversation.title.casefold():
                    matches.append(conversation)
                    continue
                message_rows = connection.execute(
                    """
                    SELECT encrypted_body FROM messages
                    WHERE conversation_id = ?
                    ORDER BY created_at, id
                    """,
                    (conversation.id,),
                ).fetchall()
                if any(
                    normalized_query in self._decrypt_text(message[0]).casefold()
                    for message in message_rows
                ):
                    matches.append(conversation)
        return tuple(matches)

    def append_user_message(
        self,
        conversation_id: str,
        body: str,
        *,
        request_id: str,
        kind: str = "text",
    ) -> Message:
        now = self._now()
        message = Message(
            id=uuid4().hex,
            conversation_id=conversation_id,
            role="user",
            kind=kind,
            body=body,
            request_id=request_id,
            in_reply_to_request_id=None,
            processing_status="pending",
            created_at=now,
        )
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            self._insert_message(connection, message)
            self._touch_conversation(connection, conversation_id, now)
        return message

    def append_assistant_message(
        self,
        conversation_id: str,
        body: str,
        *,
        in_reply_to_request_id: str,
        kind: str = "text",
        model_metadata: Any | None = None,
    ) -> Message:
        now = self._now()
        metadata_text = self._serialize_metadata(model_metadata)
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            request = self._request_row(
                connection, conversation_id, in_reply_to_request_id
            )
            existing = connection.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ? AND role = 'assistant'
                    AND in_reply_to_request_id = ?
                """,
                (conversation_id, in_reply_to_request_id),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE messages SET processing_status = 'completed'
                    WHERE id = ? AND conversation_id = ?
                    """,
                    (request["id"], conversation_id),
                )
                return self._message_from_row(existing)
            message = Message(
                id=uuid4().hex,
                conversation_id=conversation_id,
                role="assistant",
                kind=kind,
                body=body,
                request_id=None,
                in_reply_to_request_id=in_reply_to_request_id,
                processing_status="completed",
                created_at=now,
                model_metadata=metadata_text,
            )
            self._insert_message(connection, message)
            connection.execute(
                """
                UPDATE messages SET processing_status = 'completed'
                WHERE id = ? AND conversation_id = ?
                """,
                (request["id"], conversation_id),
            )
            self._touch_conversation(connection, conversation_id, now)
        return message

    def list_messages(self, conversation_id: str) -> tuple[Message, ...]:
        with self._connect() as connection:
            self._active_conversation_row(connection, conversation_id)
            rows = connection.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ?
                ORDER BY append_order
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._message_from_row(row) for row in rows)

    def edit_message(
        self, conversation_id: str, message_id: str, body: str
    ) -> Message:
        now = self._now()
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            message = self._message_row(connection, conversation_id, message_id)
            invalidates_summary = self._message_is_covered_by_current_summary(
                connection, conversation_id, message["append_order"]
            )
            connection.execute(
                """
                UPDATE messages
                SET encrypted_body = ?, content_revision = content_revision + 1
                WHERE id = ? AND conversation_id = ?
                """,
                (self._encrypt_text(body), message_id, conversation_id),
            )
            self._touch_after_message_change(
                connection, conversation_id, now, invalidates_summary
            )
            updated = self._message_row(connection, conversation_id, message_id)
        return self._message_from_row(updated)

    def delete_message(self, conversation_id: str, message_id: str) -> None:
        now = self._now()
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            message = self._message_row(connection, conversation_id, message_id)
            invalidates_summary = self._message_is_covered_by_current_summary(
                connection, conversation_id, message["append_order"]
            )
            connection.execute(
                """
                DELETE FROM messages WHERE id = ? AND conversation_id = ?
                """,
                (message_id, conversation_id),
            )
            self._touch_after_message_change(
                connection, conversation_id, now, invalidates_summary
            )

    def mark_request_processing(
        self,
        conversation_id: str,
        request_id: str,
        *,
        model_metadata: Any | None = None,
    ) -> PendingRequest:
        return self._set_request_status(
            conversation_id,
            request_id,
            "processing",
            model_metadata=model_metadata,
        )

    def mark_request_failed(
        self, conversation_id: str, request_id: str
    ) -> PendingRequest:
        return self._set_request_status(conversation_id, request_id, "failed")

    def list_retryable_requests(
        self, conversation_id: str
    ) -> tuple[PendingRequest, ...]:
        with self._connect() as connection:
            self._active_conversation_row(connection, conversation_id)
            rows = connection.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ? AND role = 'user'
                    AND processing_status IN ('failed', 'interrupted')
                ORDER BY append_order
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._pending_request_from_row(row) for row in rows)

    def save_confirmed_fact(
        self, conversation_id: str, body: str
    ) -> ConfirmedFact:
        now = self._now()
        fact = ConfirmedFact(uuid4().hex, conversation_id, body, now)
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            connection.execute(
                """
                INSERT INTO confirmed_facts(
                    id, conversation_id, encrypted_body, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    fact.id,
                    conversation_id,
                    self._encrypt_text(body),
                    self._format_time(now),
                ),
            )
        return fact

    def list_confirmed_facts(
        self, conversation_id: str
    ) -> tuple[ConfirmedFact, ...]:
        with self._connect() as connection:
            self._active_conversation_row(connection, conversation_id)
            rows = connection.execute(
                """
                SELECT * FROM confirmed_facts
                WHERE conversation_id = ?
                ORDER BY created_at, id
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._confirmed_fact_from_row(row) for row in rows)

    def save_context_summary(
        self,
        conversation_id: str,
        body: str,
        *,
        start_message_id: str,
        end_message_id: str,
        context_version: int,
        expected_message_revisions: tuple[tuple[str, int], ...] | None = None,
    ) -> ContextSummary:
        now = self._now()
        summary = ContextSummary(
            uuid4().hex,
            conversation_id,
            body,
            start_message_id,
            end_message_id,
            context_version,
            now,
        )
        with self._connect() as connection:
            self._begin_write(connection)
            conversation = self._active_conversation_row(connection, conversation_id)
            if context_version != conversation["context_version"]:
                raise ValueError("Context summary version is stale")
            try:
                start_message = self._message_row(
                    connection, conversation_id, start_message_id
                )
                end_message = self._message_row(
                    connection, conversation_id, end_message_id
                )
            except KeyError:
                if expected_message_revisions is not None:
                    raise ValueError(
                        "Messages changed during summarization"
                    ) from None
                raise
            if expected_message_revisions is not None:
                lower, upper = sorted(
                    (start_message["append_order"], end_message["append_order"])
                )
                current_revisions = tuple(
                    (row["id"], row["content_revision"])
                    for row in connection.execute(
                        """
                        SELECT id, content_revision FROM messages
                        WHERE conversation_id = ? AND append_order BETWEEN ? AND ?
                        ORDER BY append_order
                        """,
                        (conversation_id, lower, upper),
                    ).fetchall()
                )
                if current_revisions != expected_message_revisions:
                    raise ValueError("Messages changed during summarization")
            connection.execute(
                """
                INSERT INTO context_summaries(
                    id, conversation_id, encrypted_body, start_message_id,
                    end_message_id, context_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.id,
                    conversation_id,
                    self._encrypt_text(body),
                    start_message_id,
                    end_message_id,
                    context_version,
                    self._format_time(now),
                ),
            )
        return summary

    def list_context_summaries(
        self, conversation_id: str
    ) -> tuple[ContextSummary, ...]:
        with self._connect() as connection:
            self._active_conversation_row(connection, conversation_id)
            rows = connection.execute(
                """
                SELECT * FROM context_summaries
                WHERE conversation_id = ?
                ORDER BY created_at, id
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._context_summary_from_row(row) for row in rows)

    def save_attachment(
        self,
        conversation_id: str,
        attachment_id: str,
        encrypted_path: str | Path,
        encrypted_data_key: bytes,
    ) -> Attachment:
        now = self._now()
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            connection.execute(
                """
                INSERT INTO attachments(
                    id, conversation_id, encrypted_path,
                    encrypted_data_key, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    conversation_id,
                    self._encrypt_text(str(encrypted_path)),
                    encrypted_data_key,
                    self._format_time(now),
                ),
            )
        return Attachment(
            attachment_id,
            conversation_id,
            Path(encrypted_path),
            encrypted_data_key,
            None,
            now,
        )

    def get_attachment(
        self, conversation_id: str, attachment_id: str
    ) -> Attachment:
        with self._connect() as connection:
            self._active_conversation_row(connection, conversation_id)
            row = self._attachment_row(connection, conversation_id, attachment_id)
        return self._attachment_from_row(row)

    def list_attachments(
        self, conversation_id: str
    ) -> tuple[Attachment, ...]:
        with self._connect() as connection:
            self._active_conversation_row(connection, conversation_id)
            rows = connection.execute(
                """
                SELECT attachments.*, corrected_ocr_texts.encrypted_text
                FROM attachments
                LEFT JOIN corrected_ocr_texts
                    ON corrected_ocr_texts.attachment_id = attachments.id
                    AND corrected_ocr_texts.conversation_id = attachments.conversation_id
                WHERE attachments.conversation_id = ?
                ORDER BY attachments.created_at, attachments.id
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._attachment_from_row(row) for row in rows)

    def list_attachment_texts(
        self, conversation_id: str
    ) -> tuple[Attachment, ...]:
        with self._connect() as connection:
            self._active_conversation_row(connection, conversation_id)
            rows = connection.execute(
                """
                SELECT attachments.*, corrected_ocr_texts.encrypted_text
                FROM attachments
                JOIN corrected_ocr_texts
                    ON corrected_ocr_texts.attachment_id = attachments.id
                    AND corrected_ocr_texts.conversation_id = attachments.conversation_id
                WHERE attachments.conversation_id = ?
                ORDER BY attachments.created_at, attachments.id
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._attachment_from_row(row) for row in rows)

    def load_context_snapshot(
        self, conversation_id: str
    ) -> ConversationContextSnapshot:
        with self._connect() as connection:
            connection.execute("BEGIN")
            conversation_row = self._active_conversation_row(
                connection, conversation_id
            )
            message_rows = connection.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ?
                ORDER BY append_order
                """,
                (conversation_id,),
            ).fetchall()
            fact_rows = connection.execute(
                """
                SELECT * FROM confirmed_facts
                WHERE conversation_id = ?
                ORDER BY created_at, id
                """,
                (conversation_id,),
            ).fetchall()
            summary_rows = connection.execute(
                """
                SELECT * FROM context_summaries
                WHERE conversation_id = ?
                ORDER BY created_at, id
                """,
                (conversation_id,),
            ).fetchall()
            attachment_rows = connection.execute(
                """
                SELECT attachments.*, corrected_ocr_texts.encrypted_text
                FROM attachments
                JOIN corrected_ocr_texts
                    ON corrected_ocr_texts.attachment_id = attachments.id
                    AND corrected_ocr_texts.conversation_id = attachments.conversation_id
                WHERE attachments.conversation_id = ?
                ORDER BY attachments.created_at, attachments.id
                """,
                (conversation_id,),
            ).fetchall()
            return ConversationContextSnapshot(
                conversation=self._conversation_from_row(conversation_row),
                messages=tuple(self._message_from_row(row) for row in message_rows),
                confirmed_facts=tuple(
                    self._confirmed_fact_from_row(row) for row in fact_rows
                ),
                context_summaries=tuple(
                    self._context_summary_from_row(row) for row in summary_rows
                ),
                attachment_texts=tuple(
                    self._attachment_from_row(row) for row in attachment_rows
                ),
            )

    def save_corrected_text(
        self,
        conversation_id: str,
        attachment_id: str,
        corrected_text: str,
    ) -> Attachment:
        now = self._now()
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            self._attachment_row(connection, conversation_id, attachment_id)
            connection.execute(
                """
                INSERT INTO corrected_ocr_texts(
                    attachment_id, conversation_id, encrypted_text, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(attachment_id) DO UPDATE SET
                    encrypted_text = excluded.encrypted_text,
                    created_at = excluded.created_at
                WHERE corrected_ocr_texts.conversation_id = excluded.conversation_id
                """,
                (
                    attachment_id,
                    conversation_id,
                    self._encrypt_text(corrected_text),
                    self._format_time(now),
                ),
            )
            row = self._attachment_row(connection, conversation_id, attachment_id)
        return self._attachment_from_row(row)

    def save_reply_card(
        self,
        conversation_id: str,
        suggestion: AdviceSuggestion,
    ) -> ReplyCard:
        now = self._now()
        payload = self._serialize_reply_card(suggestion)
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            connection.execute(
                """
                INSERT INTO reply_cards(
                    id, conversation_id, encrypted_payload, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    suggestion.suggestion_id,
                    conversation_id,
                    self._encrypt_text(payload),
                    self._format_time(now),
                ),
            )
        return ReplyCard(
            suggestion.suggestion_id,
            conversation_id,
            suggestion,
            now,
        )

    def list_reply_cards(
        self,
        conversation_id: str,
    ) -> tuple[ReplyCard, ...]:
        with self._connect() as connection:
            self._active_conversation_row(connection, conversation_id)
            rows = connection.execute(
                """
                SELECT * FROM reply_cards
                WHERE conversation_id = ?
                ORDER BY created_at, id
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._reply_card_from_row(row) for row in rows)

    def list_cleanup_jobs(
        self, conversation_id: str, kind: str
    ) -> tuple[CleanupJob, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM cleanup_jobs
                WHERE conversation_id = ? AND kind = ? AND status = 'pending'
                ORDER BY created_at, id
                """,
                (conversation_id, kind),
            ).fetchall()
        return tuple(
            CleanupJob(
                id=row["id"],
                conversation_id=row["conversation_id"],
                kind=row["kind"],
                payload=self._decrypt_text(row["encrypted_payload"]),
                created_at=self._parse_time(row["created_at"]),
            )
            for row in rows
        )

    def list_pending_cleanup_conversation_ids(self, kind: str) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT conversation_id FROM cleanup_jobs
                WHERE kind = ? AND status = 'pending'
                ORDER BY conversation_id
                """,
                (kind,),
            ).fetchall()
        return tuple(row["conversation_id"] for row in rows)

    def complete_cleanup_job(self, conversation_id: str, job_id: str) -> None:
        now = self._now()
        with self._connect() as connection:
            self._begin_write(connection)
            updated = connection.execute(
                """
                UPDATE cleanup_jobs
                SET status = 'completed', completed_at = ?
                WHERE id = ? AND conversation_id = ? AND status = 'pending'
                """,
                (self._format_time(now), job_id, conversation_id),
            )
            if updated.rowcount == 0:
                row = connection.execute(
                    """
                    SELECT 1 FROM cleanup_jobs
                    WHERE id = ? AND conversation_id = ?
                    """,
                    (job_id, conversation_id),
                ).fetchone()
                if row is None:
                    raise KeyError(job_id)

    def delete_conversation(self, conversation_id: str) -> None:
        now = self._now()
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            self._queue_attachment_cleanup(connection, conversation_id, now)
            self._queue_cleanup_job(
                connection,
                conversation_id,
                "delete_learning_candidates",
                conversation_id,
                now,
            )
            for table_name in (
                "corrected_ocr_texts",
                "corrected_ocr_text",
                "attachment_texts",
                "document_usages",
                "generations",
                "reply_cards",
                "attachments",
                "context_summaries",
                "confirmed_facts",
                "messages",
            ):
                self._delete_scoped_rows_if_present(
                    connection, table_name, conversation_id
                )
            formatted_now = self._format_time(now)
            connection.execute(
                """
                UPDATE conversations
                SET encrypted_title = ?, status = 'deleted',
                    context_version = context_version + 1,
                    updated_at = ?, deleted_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (
                    self._encrypt_text(""),
                    formatted_now,
                    formatted_now,
                    conversation_id,
                ),
            )

    def _set_request_status(
        self,
        conversation_id: str,
        request_id: str,
        status: str,
        *,
        model_metadata: Any | None = None,
    ) -> PendingRequest:
        metadata_text = self._serialize_metadata(model_metadata)
        with self._connect() as connection:
            self._begin_write(connection)
            self._active_conversation_row(connection, conversation_id)
            row = self._request_row(connection, conversation_id, request_id)
            if row["processing_status"] == "completed":
                return self._pending_request_from_row(row)
            encrypted_metadata = row["encrypted_model_metadata"]
            if model_metadata is not None:
                encrypted_metadata = self._encrypt_text(metadata_text or "")
            connection.execute(
                """
                UPDATE messages
                SET processing_status = ?, encrypted_model_metadata = ?
                WHERE id = ? AND conversation_id = ?
                """,
                (status, encrypted_metadata, row["id"], conversation_id),
            )
            updated = self._request_row(connection, conversation_id, request_id)
        return self._pending_request_from_row(updated)

    def _insert_message(
        self, connection: sqlite3.Connection, message: Message
    ) -> None:
        encrypted_metadata = (
            self._encrypt_text(message.model_metadata)
            if message.model_metadata is not None
            else None
        )
        append_order = connection.execute(
            """
            SELECT COALESCE(MAX(append_order), 0) + 1
            FROM messages WHERE conversation_id = ?
            """,
            (message.conversation_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO messages(
                id, conversation_id, role, kind, encrypted_body,
                request_id, in_reply_to_request_id, processing_status,
                encrypted_model_metadata, created_at, append_order, content_revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                message.id,
                message.conversation_id,
                message.role,
                message.kind,
                self._encrypt_text(message.body),
                message.request_id,
                message.in_reply_to_request_id,
                message.processing_status,
                encrypted_metadata,
                self._format_time(message.created_at),
                append_order,
            ),
        )

    def _ensure_message_columns(
        self, connection: sqlite3.Connection
    ) -> None:
        columns = self._table_columns(connection, "messages")
        if "append_order" not in columns:
            connection.execute("ALTER TABLE messages ADD COLUMN append_order INTEGER")
        if "content_revision" not in columns:
            connection.execute(
                """
                ALTER TABLE messages
                ADD COLUMN content_revision INTEGER NOT NULL DEFAULT 1
                """
            )
        rows = connection.execute(
            """
            SELECT rowid, conversation_id FROM messages
            WHERE append_order IS NULL
            ORDER BY rowid
            """
        ).fetchall()
        next_orders = {
            row["conversation_id"]: row["next_order"]
            for row in connection.execute(
                """
                SELECT conversation_id, COALESCE(MAX(append_order), 0) + 1 AS next_order
                FROM messages GROUP BY conversation_id
                """
            ).fetchall()
        }
        for row in rows:
            conversation_id = row["conversation_id"]
            append_order = next_orders.get(conversation_id, 1)
            connection.execute(
                "UPDATE messages SET append_order = ? WHERE rowid = ?",
                (append_order, row["rowid"]),
            )
            next_orders[conversation_id] = append_order + 1

    def _message_is_covered_by_current_summary(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        append_order: int,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM context_summaries AS summary
            JOIN conversations AS conversation
                ON conversation.id = summary.conversation_id
            JOIN messages AS first_message
                ON first_message.id = summary.start_message_id
                AND first_message.conversation_id = summary.conversation_id
            JOIN messages AS last_message
                ON last_message.id = summary.end_message_id
                AND last_message.conversation_id = summary.conversation_id
            WHERE summary.conversation_id = ?
                AND summary.context_version = conversation.context_version
                AND ? BETWEEN MIN(first_message.append_order, last_message.append_order)
                    AND MAX(first_message.append_order, last_message.append_order)
            LIMIT 1
            """,
            (conversation_id, append_order),
        ).fetchone()
        return row is not None

    def _touch_after_message_change(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        now: datetime,
        invalidates_summary: bool,
    ) -> None:
        if invalidates_summary:
            connection.execute(
                """
                UPDATE conversations
                SET context_version = context_version + 1, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (self._format_time(now), conversation_id),
            )
            return
        self._touch_conversation(connection, conversation_id, now)

    def _active_conversation_row(
        self, connection: sqlite3.Connection, conversation_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM conversations
            WHERE id = ? AND deleted_at IS NULL
            """,
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return row

    def _request_row(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        request_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ? AND role = 'user' AND request_id = ?
            """,
            (conversation_id, request_id),
        ).fetchone()
        if row is None:
            raise KeyError(request_id)
        return row

    def _message_row(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        message_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ? AND id = ?
            """,
            (conversation_id, message_id),
        ).fetchone()
        if row is None:
            raise KeyError(message_id)
        return row

    def _attachment_row(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        attachment_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT attachments.*, corrected_ocr_texts.encrypted_text
            FROM attachments
            LEFT JOIN corrected_ocr_texts
                ON corrected_ocr_texts.attachment_id = attachments.id
                AND corrected_ocr_texts.conversation_id = attachments.conversation_id
            WHERE attachments.conversation_id = ? AND attachments.id = ?
            """,
            (conversation_id, attachment_id),
        ).fetchone()
        if row is None:
            raise KeyError(attachment_id)
        return row

    def _touch_conversation(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        now: datetime,
    ) -> None:
        connection.execute(
            """
            UPDATE conversations SET updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (self._format_time(now), conversation_id),
        )

    def _queue_attachment_cleanup(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        now: datetime,
    ) -> None:
        columns = self._table_columns(connection, "attachments")
        if "conversation_id" not in columns:
            return
        path_column = next(
            (
                name
                for name in ("encrypted_path", "path", "file_path")
                if name in columns
            ),
            None,
        )
        if path_column is None:
            return
        rows = connection.execute(
            f'SELECT "{path_column}" FROM attachments WHERE conversation_id = ?',
            (conversation_id,),
        ).fetchall()
        for row in rows:
            payload = row[0]
            if isinstance(payload, bytes) and payload[:1] == b"\x01":
                encrypted_payload = payload
            else:
                encrypted_payload = self._cipher.encrypt(str(payload).encode("utf-8"))
            connection.execute(
                """
                INSERT INTO cleanup_jobs(
                    id, conversation_id, kind, encrypted_payload,
                    status, created_at, completed_at
                ) VALUES (?, ?, 'delete_attachment', ?, 'pending', ?, NULL)
                """,
                (uuid4().hex, conversation_id, encrypted_payload, self._format_time(now)),
            )

    def _queue_cleanup_job(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        kind: str,
        payload: str,
        now: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO cleanup_jobs(
                id, conversation_id, kind, encrypted_payload,
                status, created_at, completed_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, NULL)
            """,
            (
                uuid4().hex,
                conversation_id,
                kind,
                self._encrypt_text(payload),
                self._format_time(now),
            ),
        )

    def _delete_scoped_rows_if_present(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        conversation_id: str,
    ) -> None:
        if "conversation_id" not in self._table_columns(connection, table_name):
            return
        connection.execute(
            f'DELETE FROM "{table_name}" WHERE conversation_id = ?',
            (conversation_id,),
        )

    @staticmethod
    def _table_columns(
        connection: sqlite3.Connection, table_name: str
    ) -> set[str]:
        return {
            row[1]
            for row in connection.execute(
                f'PRAGMA table_info("{table_name}")'
            ).fetchall()
        }

    def _conversation_from_row(self, row: sqlite3.Row) -> Conversation:
        return Conversation(
            id=row["id"],
            title=self._decrypt_text(row["encrypted_title"]),
            status=row["status"],
            context_version=row["context_version"],
            created_at=self._parse_time(row["created_at"]),
            updated_at=self._parse_time(row["updated_at"]),
        )

    def _message_from_row(self, row: sqlite3.Row) -> Message:
        encrypted_metadata = row["encrypted_model_metadata"]
        return Message(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            kind=row["kind"],
            body=self._decrypt_text(row["encrypted_body"]),
            request_id=row["request_id"],
            in_reply_to_request_id=row["in_reply_to_request_id"],
            processing_status=row["processing_status"],
            created_at=self._parse_time(row["created_at"]),
            model_metadata=(
                self._decrypt_text(encrypted_metadata)
                if encrypted_metadata is not None
                else None
            ),
            content_revision=row["content_revision"],
        )

    def _pending_request_from_row(self, row: sqlite3.Row) -> PendingRequest:
        message = self._message_from_row(row)
        if message.request_id is None:
            raise ValueError("Pending request has no request ID")
        return PendingRequest(
            conversation_id=message.conversation_id,
            request_id=message.request_id,
            message_id=message.id,
            body=message.body,
            processing_status=message.processing_status,
            created_at=message.created_at,
            model_metadata=message.model_metadata,
        )

    def _confirmed_fact_from_row(self, row: sqlite3.Row) -> ConfirmedFact:
        return ConfirmedFact(
            id=row["id"],
            conversation_id=row["conversation_id"],
            body=self._decrypt_text(row["encrypted_body"]),
            created_at=self._parse_time(row["created_at"]),
        )

    def _context_summary_from_row(self, row: sqlite3.Row) -> ContextSummary:
        return ContextSummary(
            id=row["id"],
            conversation_id=row["conversation_id"],
            body=self._decrypt_text(row["encrypted_body"]),
            start_message_id=row["start_message_id"],
            end_message_id=row["end_message_id"],
            context_version=row["context_version"],
            created_at=self._parse_time(row["created_at"]),
        )

    def _attachment_from_row(self, row: sqlite3.Row) -> Attachment:
        encrypted_text = row["encrypted_text"]
        return Attachment(
            id=row["id"],
            conversation_id=row["conversation_id"],
            encrypted_path=Path(self._decrypt_text(row["encrypted_path"])),
            encrypted_data_key=row["encrypted_data_key"],
            corrected_text=(
                self._decrypt_text(encrypted_text)
                if encrypted_text is not None
                else None
            ),
            created_at=self._parse_time(row["created_at"]),
        )

    def _reply_card_from_row(self, row: sqlite3.Row) -> ReplyCard:
        payload = json.loads(self._decrypt_text(row["encrypted_payload"]))
        suggestion = AdviceSuggestion(
            suggestion_id=row["id"],
            concern_summary=payload["concern_summary"],
            wechat_reply=payload["wechat_reply"],
            facts=tuple(
                SearchResult(
                    knowledge_type=KnowledgeType(fact["knowledge_type"]),
                    document_name=fact["document_name"],
                    locator=fact["locator"],
                    evidence=fact["evidence"],
                    score=float(fact["score"]),
                    source_tier=fact["source_tier"],
                    authority=fact["authority"],
                )
                for fact in payload["facts"]
            ),
            risk=RiskAssessment(
                level=RiskLevel(payload["risk"]["level"]),
                warnings=tuple(payload["risk"]["warnings"]),
                transfer_status=TransferStatus(
                    payload["risk"]["transfer_status"]
                ),
            ),
        )
        return ReplyCard(
            id=row["id"],
            conversation_id=row["conversation_id"],
            suggestion=suggestion,
            created_at=self._parse_time(row["created_at"]),
        )

    @staticmethod
    def _serialize_reply_card(suggestion: AdviceSuggestion) -> str:
        return json.dumps(
            {
                "concern_summary": suggestion.concern_summary,
                "wechat_reply": suggestion.wechat_reply,
                "facts": [
                    {
                        "knowledge_type": fact.knowledge_type.value,
                        "document_name": fact.document_name,
                        "locator": fact.locator,
                        "evidence": fact.evidence,
                        "score": fact.score,
                        "source_tier": fact.source_tier,
                        "authority": fact.authority,
                    }
                    for fact in suggestion.facts
                ],
                "risk": {
                    "level": suggestion.risk.level.value,
                    "warnings": list(suggestion.risk.warnings),
                    "transfer_status": suggestion.risk.transfer_status.value,
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _encrypt_text(self, value: str) -> bytes:
        return self._cipher.encrypt(value.encode("utf-8"))

    def _decrypt_text(self, value: bytes) -> str:
        return self._cipher.decrypt(value).decode("utf-8")

    def _now(self) -> datetime:
        return self._clock()

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.fromisoformat(value)

    @staticmethod
    def _serialize_metadata(value: Any | None) -> str | None:
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return json.dumps(value, ensure_ascii=False)
