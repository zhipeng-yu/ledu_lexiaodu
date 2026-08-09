from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from lexiaodu.attachments import AttachmentStore
from lexiaodu.conversations import ConversationRepository
from lexiaodu.local_crypto import DataCipher


@pytest.fixture
def cipher() -> DataCipher:
    return DataCipher(b"a" * 32)


@pytest.fixture
def repository(tmp_path: Path, cipher: DataCipher) -> ConversationRepository:
    return ConversationRepository(tmp_path / "conversations.sqlite3", cipher)


def sample_image() -> QImage:
    image = QImage(3, 2, QImage.Format.Format_RGB32)
    image.fill(QColor(12, 34, 56))
    return image


def test_encrypted_image_lifecycle_is_conversation_scoped_and_restart_safe(
    tmp_path: Path,
    repository: ConversationRepository,
    cipher: DataCipher,
) -> None:
    root = tmp_path / "attachments"
    first = repository.create_conversation("first")
    second = repository.create_conversation("second")
    store = AttachmentStore(root, repository, cipher)

    attachment = store.save_image(first.id, sample_image())
    attachment = store.save_corrected_text(
        first.id,
        attachment.id,
        "CORRECTED-OCR-UNIQUE-SENTINEL",
    )

    encrypted_files = tuple(root.iterdir())
    assert len(encrypted_files) == 1
    encrypted_file = encrypted_files[0]
    assert encrypted_file.name == f"{attachment.id}.bin"
    assert len(attachment.id) == 32
    assert all(character in "0123456789abcdef" for character in attachment.id)
    assert encrypted_file.suffix == ".bin"
    raw = encrypted_file.read_bytes()
    assert b"\x89PNG\r\n\x1a\n" not in raw
    assert b"CORRECTED-OCR-UNIQUE-SENTINEL" not in raw

    with pytest.raises(KeyError):
        store.load_image(second.id, attachment.id)

    reopened_repository = ConversationRepository(
        tmp_path / "conversations.sqlite3", cipher
    )
    reopened_store = AttachmentStore(root, reopened_repository, cipher)
    loaded = reopened_store.load_image(first.id, attachment.id)

    assert loaded.size() == QSize(3, 2)
    assert loaded.pixelColor(1, 1) == QColor(12, 34, 56)
    assert reopened_store.list_for_conversation(first.id) == (attachment,)

    reopened_repository.delete_conversation(first.id)

    assert reopened_store.run_cleanup_jobs() == 1
    assert reopened_store.run_cleanup_jobs() == 0
    assert not encrypted_file.exists()


def test_each_attachment_uses_an_independent_random_data_key(
    tmp_path: Path,
    repository: ConversationRepository,
    cipher: DataCipher,
) -> None:
    conversation = repository.create_conversation("keys")
    store = AttachmentStore(tmp_path / "attachments", repository, cipher)

    first = store.save_image(conversation.id, sample_image())
    second = store.save_image(conversation.id, sample_image())

    first_key = cipher.decrypt(first.encrypted_data_key)
    second_key = cipher.decrypt(second.encrypted_data_key)
    assert len(first_key) == len(second_key) == 32
    assert first_key != second_key
    assert first.encrypted_path.read_bytes() != second.encrypted_path.read_bytes()


def test_failed_metadata_insert_removes_the_new_encrypted_file(
    tmp_path: Path,
    repository: ConversationRepository,
    cipher: DataCipher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = repository.create_conversation("rollback")
    root = tmp_path / "attachments"
    store = AttachmentStore(root, repository, cipher)

    def fail_insert(*args: object, **kwargs: object) -> None:
        raise RuntimeError("metadata insert failed")

    monkeypatch.setattr(repository, "save_attachment", fail_insert)

    with pytest.raises(RuntimeError, match="metadata insert failed"):
        store.save_image(conversation.id, sample_image())

    assert tuple(root.iterdir()) == ()
