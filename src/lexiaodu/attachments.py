from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

from lexiaodu.conversations import Attachment, ConversationRepository
from lexiaodu.local_crypto import DataCipher


_FORMAT_VERSION = b"\x01"
_NONCE_BYTES = 12
_DATA_KEY_BYTES = 32
_CORRUPT_MESSAGE = "附件无法解码"


class AttachmentCorrupt(ValueError):
    """Raised when an encrypted attachment cannot be authenticated or decoded."""


def encrypt_attachment_payload(data_key: bytes, raw: bytes) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    return _FORMAT_VERSION + nonce + AESGCM(data_key).encrypt(
        nonce, raw, _FORMAT_VERSION
    )


def decrypt_attachment_payload(data_key: bytes, payload: bytes) -> bytes:
    if len(payload) < 14 or payload[:1] != _FORMAT_VERSION:
        raise AttachmentCorrupt(_CORRUPT_MESSAGE)
    try:
        return AESGCM(data_key).decrypt(
            payload[1:13], payload[13:], _FORMAT_VERSION
        )
    except (InvalidTag, ValueError) as exc:
        raise AttachmentCorrupt(_CORRUPT_MESSAGE) from exc


class AttachmentStore:
    def __init__(
        self,
        root: str | Path,
        repository: ConversationRepository,
        cipher: DataCipher,
    ) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._repository = repository
        self._cipher = cipher

    def save_image(self, conversation_id: str, image: QImage) -> Attachment:
        raw = self._png_bytes(image)
        attachment_id = uuid4().hex
        encrypted_path = self._root / f"{attachment_id}.bin"
        data_key = os.urandom(_DATA_KEY_BYTES)
        payload = encrypt_attachment_payload(data_key, raw)
        encrypted_data_key = self._cipher.encrypt(data_key)

        self._atomic_write(encrypted_path, payload)
        try:
            return self._repository.save_attachment(
                conversation_id,
                attachment_id,
                encrypted_path,
                encrypted_data_key,
            )
        except BaseException:
            encrypted_path.unlink(missing_ok=True)
            raise

    def load_image(self, conversation_id: str, attachment_id: str) -> QImage:
        record = self._repository.get_attachment(conversation_id, attachment_id)
        data_key = self._cipher.decrypt(record.encrypted_data_key)
        payload = record.encrypted_path.read_bytes()
        raw = decrypt_attachment_payload(data_key, payload)
        image = QImage.fromData(raw, "PNG")
        if image.isNull():
            raise AttachmentCorrupt(_CORRUPT_MESSAGE)
        return image

    def save_corrected_text(
        self,
        conversation_id: str,
        attachment_id: str,
        corrected_text: str,
    ) -> Attachment:
        return self._repository.save_corrected_text(
            conversation_id, attachment_id, corrected_text
        )

    def list_for_conversation(
        self, conversation_id: str
    ) -> tuple[Attachment, ...]:
        return self._repository.list_attachments(conversation_id)

    def run_cleanup_jobs(self, conversation_id: str) -> int:
        completed = 0
        root = self._root.resolve()
        for job in self._repository.list_cleanup_jobs(
            conversation_id, "delete_attachment"
        ):
            encrypted_path = Path(job.payload).resolve()
            if encrypted_path.parent != root:
                raise AttachmentCorrupt(_CORRUPT_MESSAGE)
            encrypted_path.unlink(missing_ok=True)
            self._repository.complete_cleanup_job(conversation_id, job.id)
            completed += 1
        return completed

    @staticmethod
    def _png_bytes(image: QImage) -> bytes:
        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise AttachmentCorrupt(_CORRUPT_MESSAGE)
        try:
            if image.isNull() or not image.save(buffer, "PNG"):
                raise AttachmentCorrupt(_CORRUPT_MESSAGE)
            return bytes(buffer.data())
        finally:
            buffer.close()

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._root,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(payload)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
