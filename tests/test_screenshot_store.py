from pathlib import Path

import pytest

from lexiaodu.chat_repository import ConversationRepository
from lexiaodu.local_crypto import DataCipher
from lexiaodu.screenshot_store import ScreenshotCorrupt, ScreenshotStore


PNG_SENTINEL = b"\x89PNG\r\n\x1a\nPRIVATE-CHAT-SENTINEL"


def test_screenshot_is_encrypted_scoped_restart_safe_and_deleted(tmp_path: Path) -> None:
    cipher = DataCipher(b"s" * 32)
    database = tmp_path / "chat.sqlite3"
    repository = ConversationRepository(database, cipher)
    first = repository.create_conversation("first")
    second = repository.create_conversation("second")
    message = repository.append_user_message(
        first.id, "聊天截图", request_id="request-1", kind="image"
    )
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)

    attachment = store.save(
        first.id, message.id, PNG_SENTINEL, "image/png", 1080, 12000
    )

    assert attachment.encrypted_path.suffix == ".bin"
    assert PNG_SENTINEL not in attachment.encrypted_path.read_bytes()
    assert cipher.decrypt(attachment.encrypted_data_key) not in database.read_bytes()
    assert store.load_for_message(first.id, message.id).data == PNG_SENTINEL
    assert store.load_for_message(second.id, message.id) is None

    reopened = ConversationRepository(database, cipher)
    reopened_store = ScreenshotStore(tmp_path / "chat-images", reopened, cipher)
    assert reopened_store.load_for_message(first.id, message.id).height == 12000

    reopened_store.delete_conversation(first.id)
    assert not attachment.encrypted_path.exists()


def test_tampered_screenshot_fails_authentication(tmp_path: Path) -> None:
    cipher = DataCipher(b"t" * 32)
    repository = ConversationRepository(tmp_path / "chat.sqlite3", cipher)
    conversation = repository.create_conversation("tamper")
    message = repository.append_user_message(
        conversation.id, "聊天截图", request_id="request", kind="image"
    )
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)
    attachment = store.save(
        conversation.id, message.id, PNG_SENTINEL, "image/png", 10, 20
    )
    attachment.encrypted_path.write_bytes(
        attachment.encrypted_path.read_bytes()[:-1] + b"x"
    )

    with pytest.raises(ScreenshotCorrupt, match="截图无法解密"):
        store.load_for_message(conversation.id, message.id)


def test_repository_failure_removes_new_encrypted_file(tmp_path: Path) -> None:
    cipher = DataCipher(b"f" * 32)
    repository = ConversationRepository(tmp_path / "chat.sqlite3", cipher)
    conversation = repository.create_conversation("rollback")
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)

    with pytest.raises(KeyError):
        store.save(
            conversation.id,
            "missing-message",
            PNG_SENTINEL,
            "image/png",
            10,
            20,
        )

    assert tuple((tmp_path / "chat-images").iterdir()) == ()


def test_delete_failure_restores_previously_removed_ciphertext(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cipher = DataCipher(b"r" * 32)
    repository = ConversationRepository(tmp_path / "chat.sqlite3", cipher)
    conversation = repository.create_conversation("rollback")
    first_message = repository.append_user_message(
        conversation.id, "first", request_id="first", kind="image"
    )
    second_message = repository.append_user_message(
        conversation.id, "second", request_id="second", kind="image"
    )
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)
    first = store.save(
        conversation.id, first_message.id, b"first", "image/png", 1, 1
    )
    second = store.save(
        conversation.id, second_message.id, b"second", "image/png", 1, 1
    )
    first, second = repository.list_screenshots(conversation.id)
    first_ciphertext = first.encrypted_path.read_bytes()
    second_ciphertext = second.encrypted_path.read_bytes()
    original_unlink = Path.unlink

    def fail_second_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path == second.encrypted_path:
            raise OSError("locked")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_second_unlink)

    with pytest.raises(OSError, match="locked"):
        store.remove_for_conversation(conversation.id)

    assert first.encrypted_path.read_bytes() == first_ciphertext
    assert second.encrypted_path.read_bytes() == second_ciphertext
    assert [attachment.id for attachment in repository.list_screenshots(conversation.id)] == [
        first.id,
        second.id,
    ]
    assert repository.get_conversation(conversation.id).id == conversation.id


def test_delete_conversation_accepts_an_already_missing_ciphertext(
    tmp_path: Path,
) -> None:
    cipher = DataCipher(b"m" * 32)
    repository = ConversationRepository(tmp_path / "chat.sqlite3", cipher)
    conversation = repository.create_conversation("already missing")
    message = repository.append_user_message(
        conversation.id, "image", request_id="request", kind="image"
    )
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)
    attachment = store.save(
        conversation.id, message.id, b"image", "image/png", 1, 1
    )
    attachment.encrypted_path.unlink()

    store.delete_conversation(conversation.id)

    assert repository.list_conversations() == ()


def test_delete_conversation_rejects_corrupt_ciphertext(tmp_path: Path) -> None:
    cipher = DataCipher(b"c" * 32)
    repository = ConversationRepository(tmp_path / "chat.sqlite3", cipher)
    conversation = repository.create_conversation("corrupt")
    message = repository.append_user_message(
        conversation.id, "image", request_id="request", kind="image"
    )
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)
    attachment = store.save(
        conversation.id, message.id, b"image", "image/png", 1, 1
    )
    expected_conversation = repository.get_conversation(conversation.id)
    attachment.encrypted_path.write_bytes(b"corrupt")

    with pytest.raises(ScreenshotCorrupt, match="截图无法解密"):
        store.delete_conversation(conversation.id)

    assert repository.get_conversation(conversation.id) == expected_conversation
    assert attachment.encrypted_path.read_bytes() == b"corrupt"
