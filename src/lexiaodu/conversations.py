from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from lexiaodu.local_crypto import DataCipher


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
                    created_at TEXT NOT NULL
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
                """
            )
            connection.execute(
                """
                UPDATE messages
                SET processing_status = 'interrupted'
                WHERE role = 'user' AND processing_status = 'processing'
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
                ORDER BY created_at, id
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._message_from_row(row) for row in rows)

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
                ORDER BY created_at, id
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
            self._message_row(connection, conversation_id, start_message_id)
            self._message_row(connection, conversation_id, end_message_id)
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
        connection.execute(
            """
            INSERT INTO messages(
                id, conversation_id, role, kind, encrypted_body,
                request_id, in_reply_to_request_id, processing_status,
                encrypted_model_metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )

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
