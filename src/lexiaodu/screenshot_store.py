from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .chat_repository import ConversationRepository, ScreenshotAttachment
from .local_crypto import DataCipher


_VERSION = b"\x01"


class ScreenshotCorrupt(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScreenshotPayload:
    data: bytes
    mime_type: str
    width: int
    height: int


class ScreenshotStore:
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

    def save(
        self,
        conversation_id: str,
        message_id: str,
        data: bytes,
        mime_type: str,
        width: int,
        height: int,
    ) -> ScreenshotAttachment:
        if (
            not data
            or mime_type not in {"image/png", "image/jpeg", "image/webp"}
            or width < 1
            or height < 1
        ):
            raise ValueError("截图数据无效")
        attachment_id = uuid4().hex
        path = self._root / f"{attachment_id}.bin"
        data_key = os.urandom(32)
        nonce = os.urandom(12)
        payload = _VERSION + nonce + AESGCM(data_key).encrypt(
            nonce, data, _VERSION
        )
        self._atomic_write(path, payload)
        try:
            return self._repository.save_screenshot_attachment(
                conversation_id,
                message_id,
                attachment_id,
                path,
                self._cipher.encrypt(data_key),
                mime_type,
                width,
                height,
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def load_for_message(
        self, conversation_id: str, message_id: str
    ) -> ScreenshotPayload | None:
        attachment = self._repository.get_screenshot_for_message(
            conversation_id, message_id
        )
        if attachment is None:
            return None
        payload = attachment.encrypted_path.read_bytes()
        if len(payload) < 14 or payload[:1] != _VERSION:
            raise ScreenshotCorrupt("截图无法解密")
        try:
            data = AESGCM(self._cipher.decrypt(attachment.encrypted_data_key)).decrypt(
                payload[1:13], payload[13:], _VERSION
            )
        except (InvalidTag, ValueError) as exc:
            raise ScreenshotCorrupt("截图无法解密") from exc
        return ScreenshotPayload(
            data, attachment.mime_type, attachment.width, attachment.height
        )

    def remove_for_conversation(self, conversation_id: str) -> None:
        root = self._root.resolve()
        files: list[tuple[Path, bytes]] = []
        for attachment in self._repository.list_screenshots(conversation_id):
            path = attachment.encrypted_path.resolve()
            if path.parent != root:
                raise ScreenshotCorrupt("截图路径无效")
            files.append((path, path.read_bytes()))
        removed: list[tuple[Path, bytes]] = []
        try:
            for path, ciphertext in files:
                path.unlink()
                removed.append((path, ciphertext))
        except OSError:
            for path, ciphertext in removed:
                self._atomic_write(path, ciphertext)
            raise

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._root,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
