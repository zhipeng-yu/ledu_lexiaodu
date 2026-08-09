from __future__ import annotations

import ctypes
import os
import sys
import tempfile
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_FORMAT_VERSION = b"\x01"
_NONCE_BYTES = 12
_MASTER_KEY_BYTES = 32
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DecryptionError(ValueError):
    """Raised when encrypted local data cannot be authenticated."""


class LocalEncryptionUnavailable(RuntimeError):
    """Raised when the operating system cannot protect a local key."""


class KeyProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...

    def unprotect(self, value: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class WindowsDpapiKeyProtector:
    """Protects key material with the current Windows user's DPAPI profile."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise LocalEncryptionUnavailable(
                "Windows DPAPI is required for local encryption"
            )

        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_wchar_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = ctypes.c_int
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = ctypes.c_int
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    @staticmethod
    def _blob(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(value)
        return (
            _DataBlob(
                len(value),
                ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
            ),
            buffer,
        )

    def protect(self, value: bytes) -> bytes:
        input_blob, input_buffer = self._blob(value)
        output_blob = _DataBlob()
        if not self._crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self._kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
            del input_buffer

    def unprotect(self, value: bytes) -> bytes:
        input_blob, input_buffer = self._blob(value)
        output_blob = _DataBlob()
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        ):
            raise LocalEncryptionUnavailable("Unable to open the local encryption key")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self._kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
            del input_buffer


class DataCipher:
    def __init__(self, key: bytes) -> None:
        self._aes = AESGCM(key)

    @classmethod
    def open(
        cls, key_path: Path, key_protector: KeyProtector | None = None
    ) -> DataCipher:
        protector = key_protector or WindowsDpapiKeyProtector()
        key_path = Path(key_path)
        if key_path.exists():
            key = protector.unprotect(key_path.read_bytes())
        else:
            key = os.urandom(_MASTER_KEY_BYTES)
            cls._write_protected_key(key_path, protector.protect(key))
        if len(key) != _MASTER_KEY_BYTES:
            raise LocalEncryptionUnavailable("The local encryption key is invalid")
        return cls(key)

    @staticmethod
    def _write_protected_key(key_path: Path, protected_key: bytes) -> None:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=key_path.parent,
                prefix=f".{key_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temp_path = Path(temporary_file.name)
                temporary_file.write(protected_key)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temp_path, key_path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def encrypt(self, value: bytes) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return _FORMAT_VERSION + nonce + self._aes.encrypt(
            nonce, value, _FORMAT_VERSION
        )

    def decrypt(self, value: bytes) -> bytes:
        if len(value) < 14 or value[:1] != _FORMAT_VERSION:
            raise DecryptionError("Unsupported or corrupted local encrypted data")
        try:
            return self._aes.decrypt(value[1:13], value[13:], _FORMAT_VERSION)
        except InvalidTag as exc:
            raise DecryptionError("Local encrypted data authentication failed") from exc
