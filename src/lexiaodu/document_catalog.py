from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from .local_crypto import DataCipher


SUPPORTED_FORMATS = frozenset({"pdf", "docx", "pptx", "xlsx"})


class DocumentCatalogError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    id: str
    path: Path
    display_name: str
    format: str
    tags: tuple[str, ...]
    sha256: str
    size_bytes: int
    allow_upload: bool


class DocumentCatalog:
    def __init__(
        self,
        database_path: Path,
        cipher: DataCipher,
        *,
        allowed_roots: tuple[Path, ...],
    ) -> None:
        if not allowed_roots:
            raise DocumentCatalogError("至少需要一个允许目录")
        self._database_path = Path(database_path)
        self._cipher = cipher
        try:
            self._allowed_roots = tuple(
                Path(root).resolve(strict=True) for root in allowed_roots
            )
        except OSError as exc:
            raise DocumentCatalogError("允许目录不存在") from exc
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    encrypted_path BLOB NOT NULL,
                    encrypted_display_name BLOB NOT NULL,
                    format TEXT NOT NULL,
                    encrypted_tags BLOB NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    allow_upload INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )

    def register(
        self,
        path: Path,
        *,
        tags: tuple[str, ...],
        allow_upload: bool = False,
    ) -> DocumentRecord:
        resolved = self._resolve_allowed_file(path)
        format = resolved.suffix.casefold().lstrip(".")
        if format not in SUPPORTED_FORMATS:
            raise DocumentCatalogError("不支持该原文档格式")
        normalized_tags = tuple(
            dict.fromkeys(tag.strip() for tag in tags if tag.strip())
        )
        if not normalized_tags:
            raise DocumentCatalogError("至少需要一个筛选标签")
        record = DocumentRecord(
            id=str(uuid.uuid4()),
            path=resolved,
            display_name=resolved.name,
            format=format,
            tags=normalized_tags,
            sha256=hash_file(resolved),
            size_bytes=resolved.stat().st_size,
            allow_upload=bool(allow_upload),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    id, encrypted_path, encrypted_display_name, format,
                    encrypted_tags, sha256, size_bytes, allow_upload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    self._encrypt(str(record.path)),
                    self._encrypt(record.display_name),
                    record.format,
                    self._encrypt(json.dumps(record.tags, ensure_ascii=False)),
                    record.sha256,
                    record.size_bytes,
                    int(record.allow_upload),
                ),
            )
        return record

    def list_active(self) -> tuple[DocumentRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, encrypted_path, encrypted_display_name, format,
                       encrypted_tags, sha256, size_bytes, allow_upload
                FROM documents WHERE active = 1 ORDER BY id
                """
            ).fetchall()
        return tuple(
            DocumentRecord(
                id=row[0],
                path=Path(self._decrypt(row[1])),
                display_name=self._decrypt(row[2]),
                format=row[3],
                tags=tuple(json.loads(self._decrypt(row[4]))),
                sha256=row[5],
                size_bytes=row[6],
                allow_upload=bool(row[7]),
            )
            for row in rows
        )

    def _resolve_allowed_file(self, path: Path) -> Path:
        try:
            resolved = Path(path).resolve(strict=True)
        except OSError as exc:
            raise DocumentCatalogError("原文档不存在") from exc
        if not resolved.is_file() or not any(
            resolved.is_relative_to(root) for root in self._allowed_roots
        ):
            raise DocumentCatalogError("原文档不在允许目录内")
        return resolved

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)

    def _encrypt(self, value: str) -> bytes:
        return self._cipher.encrypt(value.encode("utf-8"))

    def _decrypt(self, value: bytes) -> str:
        return self._cipher.decrypt(value).decode("utf-8")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
