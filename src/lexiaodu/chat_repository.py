from __future__ import annotations

import sqlite3
from collections.abc import Callable
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
    content_revision: int = 1


@dataclass(frozen=True, slots=True)
class PendingRequest:
    conversation_id: str
    request_id: str
    message_id: str
    body: str
    processing_status: str
    created_at: datetime
    model_metadata: str | None = None


class ConversationRepository:
    """Encrypted local storage for conversations and messages only."""

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
                    request_id TEXT,
                    in_reply_to_request_id TEXT,
                    processing_status TEXT NOT NULL,
                    encrypted_model_metadata BLOB,
                    created_at TEXT NOT NULL,
                    append_order INTEGER,
                    content_revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE UNIQUE INDEX IF NOT EXISTS messages_request_owner
                    ON messages(conversation_id, request_id)
                    WHERE request_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS messages_assistant_reply
                    ON messages(conversation_id, in_reply_to_request_id)
                    WHERE role = 'assistant' AND in_reply_to_request_id IS NOT NULL;
                """
            )
            self._ensure_message_columns(connection)
            self._remove_legacy_content(connection)
            connection.execute(
                """
                UPDATE messages SET processing_status = 'interrupted'
                WHERE role = 'user'
                    AND processing_status IN ('pending', 'processing')
                """
            )

    def _remove_legacy_content(self, connection: sqlite3.Connection) -> None:
        for table_name in (
            "corrected_ocr_texts",
            "attachments",
            "reply_cards",
            "cleanup_jobs",
            "context_summaries",
            "confirmed_facts",
        ):
            connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        connection.execute("DELETE FROM messages WHERE kind = 'screenshot'")

    def _ensure_message_columns(self, connection: sqlite3.Connection) -> None:
        columns = {
            row[1]
            for row in connection.execute('PRAGMA table_info("messages")').fetchall()
        }
        if "append_order" not in columns:
            connection.execute("ALTER TABLE messages ADD COLUMN append_order INTEGER")
        if "content_revision" not in columns:
            connection.execute(
                "ALTER TABLE messages ADD COLUMN content_revision INTEGER NOT NULL DEFAULT 1"
            )
        rows = connection.execute(
            """
            SELECT rowid, conversation_id FROM messages
            WHERE append_order IS NULL ORDER BY rowid
            """
        ).fetchall()
        next_order: dict[str, int] = {}
        for row in rows:
            conversation_id = row["conversation_id"]
            order = next_order.get(conversation_id)
            if order is None:
                order = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(append_order), 0) + 1
                        FROM messages
                        WHERE conversation_id = ? AND append_order IS NOT NULL
                        """,
                        (conversation_id,),
                    ).fetchone()[0]
                )
            connection.execute(
                "UPDATE messages SET append_order = ? WHERE rowid = ?",
                (order, row["rowid"]),
            )
            next_order[conversation_id] = order + 1

    def create_conversation(self, title: str) -> Conversation:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("会话标题不能为空")
        now = self._clock()
        conversation = Conversation(
            id=uuid4().hex,
            title=clean_title,
            status="active",
            context_version=1,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations(
                    id, encrypted_title, status, context_version,
                    created_at, updated_at, deleted_at
                ) VALUES (?, ?, 'active', 1, ?, ?, NULL)
                """,
                (
                    conversation.id,
                    self._encrypt(clean_title),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return conversation

    def get_conversation(self, conversation_id: str) -> Conversation:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ? AND deleted_at IS NULL",
                (conversation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return self._conversation(row)

    def list_conversations(self) -> tuple[Conversation, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversations
                WHERE deleted_at IS NULL
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        return tuple(self._conversation(row) for row in rows)

    def search_conversations(self, query: str) -> tuple[Conversation, ...]:
        needle = query.strip().casefold()
        if not needle:
            return self.list_conversations()
        matches: list[Conversation] = []
        for conversation in self.list_conversations():
            if needle in conversation.title.casefold() or any(
                needle in message.body.casefold()
                for message in self.list_messages(conversation.id)
            ):
                matches.append(conversation)
        return tuple(matches)

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("会话标题不能为空")
        now = self._clock()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE conversations
                SET encrypted_title = ?, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (self._encrypt(clean_title), now.isoformat(), conversation_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(conversation_id)
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(conversation_id)

    def append_user_message(
        self,
        conversation_id: str,
        body: str,
        *,
        request_id: str,
        kind: str = "text",
        model_metadata: Any | None = None,
    ) -> Message:
        clean_body = body.strip()
        if not clean_body:
            raise ValueError("消息不能为空")
        message = Message(
            id=uuid4().hex,
            conversation_id=conversation_id,
            role="user",
            kind=kind,
            body=clean_body,
            request_id=request_id,
            in_reply_to_request_id=None,
            processing_status="pending",
            created_at=self._clock(),
            model_metadata=self._metadata_text(model_metadata),
        )
        with self._connect() as connection:
            self._require_conversation(connection, conversation_id)
            self._insert_message(connection, message)
            self._touch(connection, conversation_id, message.created_at)
        return message

    def append_assistant_message(
        self,
        conversation_id: str,
        body: str,
        *,
        in_reply_to_request_id: str,
        model_metadata: Any | None = None,
    ) -> Message:
        clean_body = body.strip()
        if not clean_body:
            raise ValueError("消息不能为空")
        now = self._clock()
        with self._connect() as connection:
            self._require_conversation(connection, conversation_id)
            existing = connection.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ? AND role = 'assistant'
                    AND in_reply_to_request_id = ?
                """,
                (conversation_id, in_reply_to_request_id),
            ).fetchone()
            if existing is not None:
                return self._message(existing)
            request = self._request_row(
                connection,
                conversation_id,
                in_reply_to_request_id,
            )
            message = Message(
                id=uuid4().hex,
                conversation_id=conversation_id,
                role="assistant",
                kind="text",
                body=clean_body,
                request_id=None,
                in_reply_to_request_id=in_reply_to_request_id,
                processing_status="completed",
                created_at=now,
                model_metadata=self._metadata_text(model_metadata),
            )
            self._insert_message(connection, message)
            connection.execute(
                "UPDATE messages SET processing_status = 'completed' WHERE id = ?",
                (request["id"],),
            )
            self._touch(connection, conversation_id, now)
        return message

    def list_messages(self, conversation_id: str) -> tuple[Message, ...]:
        with self._connect() as connection:
            self._require_conversation(connection, conversation_id)
            rows = connection.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ?
                ORDER BY append_order, created_at, id
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._message(row) for row in rows)

    def mark_request_processing(
        self,
        conversation_id: str,
        request_id: str,
        model_metadata: Any | None = None,
    ) -> PendingRequest:
        return self._set_request_status(
            conversation_id,
            request_id,
            "processing",
            model_metadata,
        )

    def mark_request_failed(
        self,
        conversation_id: str,
        request_id: str,
        model_metadata: Any | None = None,
    ) -> PendingRequest:
        return self._set_request_status(
            conversation_id,
            request_id,
            "failed",
            model_metadata,
        )

    def list_retryable_requests(
        self,
        conversation_id: str,
    ) -> tuple[PendingRequest, ...]:
        with self._connect() as connection:
            self._require_conversation(connection, conversation_id)
            rows = connection.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ? AND role = 'user'
                    AND processing_status IN ('failed', 'interrupted')
                ORDER BY append_order, created_at, id
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._pending(row) for row in rows)

    def _set_request_status(
        self,
        conversation_id: str,
        request_id: str,
        status: str,
        model_metadata: Any | None,
    ) -> PendingRequest:
        with self._connect() as connection:
            self._require_conversation(connection, conversation_id)
            row = self._request_row(connection, conversation_id, request_id)
            if row["processing_status"] == "completed":
                return self._pending(row)
            encrypted_metadata = row["encrypted_model_metadata"]
            if model_metadata is not None:
                encrypted_metadata = self._encrypt(self._metadata_text(model_metadata) or "")
            connection.execute(
                """
                UPDATE messages
                SET processing_status = ?, encrypted_model_metadata = ?
                WHERE id = ?
                """,
                (status, encrypted_metadata, row["id"]),
            )
            updated = connection.execute(
                "SELECT * FROM messages WHERE id = ?",
                (row["id"],),
            ).fetchone()
        return self._pending(updated)

    def _insert_message(
        self,
        connection: sqlite3.Connection,
        message: Message,
    ) -> None:
        order = int(
            connection.execute(
                """
                SELECT COALESCE(MAX(append_order), 0) + 1
                FROM messages WHERE conversation_id = ?
                """,
                (message.conversation_id,),
            ).fetchone()[0]
        )
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
                self._encrypt(message.body),
                message.request_id,
                message.in_reply_to_request_id,
                message.processing_status,
                self._encrypt(message.model_metadata)
                if message.model_metadata is not None
                else None,
                message.created_at.isoformat(),
                order,
            ),
        )

    def _require_conversation(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
    ) -> None:
        row = connection.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND deleted_at IS NULL",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(conversation_id)

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

    def _touch(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        now: datetime,
    ) -> None:
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now.isoformat(), conversation_id),
        )

    def _conversation(self, row: sqlite3.Row) -> Conversation:
        return Conversation(
            id=row["id"],
            title=self._decrypt(row["encrypted_title"]),
            status=row["status"],
            context_version=int(row["context_version"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _message(self, row: sqlite3.Row) -> Message:
        metadata = row["encrypted_model_metadata"]
        return Message(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            kind=row["kind"],
            body=self._decrypt(row["encrypted_body"]),
            request_id=row["request_id"],
            in_reply_to_request_id=row["in_reply_to_request_id"],
            processing_status=row["processing_status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            model_metadata=self._decrypt(metadata) if metadata is not None else None,
            content_revision=int(row["content_revision"]),
        )

    def _pending(self, row: sqlite3.Row) -> PendingRequest:
        message = self._message(row)
        if message.request_id is None:
            raise ValueError("请求消息缺少 request_id")
        return PendingRequest(
            conversation_id=message.conversation_id,
            request_id=message.request_id,
            message_id=message.id,
            body=message.body,
            processing_status=message.processing_status,
            created_at=message.created_at,
            model_metadata=message.model_metadata,
        )

    def _encrypt(self, value: str) -> bytes:
        return self._cipher.encrypt(value.encode("utf-8"))

    def _decrypt(self, value: bytes) -> str:
        return self._cipher.decrypt(value).decode("utf-8")

    @staticmethod
    def _metadata_text(value: Any | None) -> str | None:
        if value is None or isinstance(value, str):
            return value
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True)
