from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from lexiaodu.local_crypto import DataCipher, DecryptionError


class RecordingTestProtector:
    def __init__(self) -> None:
        self.last_plaintext: bytes | None = None

    def protect(self, value: bytes) -> bytes:
        self.last_plaintext = value
        return b"test-envelope:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        assert value.startswith(b"test-envelope:")
        return value.removeprefix(b"test-envelope:")[::-1]


class BarrierTestProtector(RecordingTestProtector):
    def __init__(self, barrier: Barrier) -> None:
        super().__init__()
        self._barrier = barrier

    def protect(self, value: bytes) -> bytes:
        protected = super().protect(value)
        self._barrier.wait(timeout=5)
        return protected


def test_cipher_reopens_without_writing_plaintext_key(tmp_path) -> None:
    key_path = tmp_path / "chat.key"
    protector = RecordingTestProtector()
    first = DataCipher.open(key_path, protector)
    encrypted = first.encrypt("铏氭瀯瀹堕暱-13900000000".encode())
    second = DataCipher.open(key_path, protector)

    assert second.decrypt(encrypted).decode() == "铏氭瀯瀹堕暱-13900000000"
    assert b"13900000000" not in encrypted
    assert protector.last_plaintext is not None
    assert protector.last_plaintext not in key_path.read_bytes()


def test_cipher_rejects_tampered_ciphertext(tmp_path) -> None:
    cipher = DataCipher.open(tmp_path / "chat.key", RecordingTestProtector())
    encrypted = cipher.encrypt(b"parent-private-message")
    tampered = encrypted[:-1] + bytes([encrypted[-1] ^ 1])

    with pytest.raises(DecryptionError):
        cipher.decrypt(tampered)


def test_concurrent_first_open_uses_the_single_published_key(tmp_path) -> None:
    key_path = tmp_path / "chat.key"
    protector = BarrierTestProtector(Barrier(2))

    with ThreadPoolExecutor(max_workers=2) as executor:
        ciphers = tuple(
            executor.map(lambda _: DataCipher.open(key_path, protector), range(2))
        )

    reopened = DataCipher.open(key_path, protector)
    payloads = tuple(
        cipher.encrypt(f"fabricated-payload-{index}".encode())
        for index, cipher in enumerate(ciphers)
    )

    for cipher in (*ciphers, reopened):
        assert tuple(cipher.decrypt(payload) for payload in payloads) == (
            b"fabricated-payload-0",
            b"fabricated-payload-1",
        )
