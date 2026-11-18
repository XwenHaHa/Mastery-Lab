"""API Key 本地加密存储。

策略（按优先级）：
1. Windows DPAPI（CryptProtectData）：由操作系统按当前 Windows 用户加密，
   密文只能在同一台机器的同一用户下解开，不需要我们自己管理主密钥。
2. Windows 加密失败时拒绝保存；非 Windows 使用 Fernet + 本地主密钥文件
   （data/secrets/master.key，权限收紧，仅当前用户可读）。

写入数据库的密文带方案前缀，形如 ``dpapi:v1:<base64>`` / ``fernet:v1:<token>``，
因此更换方案或迁移时可识别并给出明确错误，而不是静默损坏。
"""

from __future__ import annotations

import base64
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

from ..core.config import settings


class SecretError(RuntimeError):
    """加解密失败（例如换机器/换用户后 DPAPI 无法解开）。"""


DPAPI_PREFIX = "dpapi:v1:"
FERNET_PREFIX = "fernet:v1:"


# --------------------------------------------------------------------------
# Windows DPAPI
# --------------------------------------------------------------------------
class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob_from_bytes(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _blob_to_bytes(blob: _DataBlob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def _dpapi_crypt(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    input_blob = _blob_from_bytes(data)
    output_blob = _DataBlob()
    description = ctypes.c_wchar_p("Mastery Lab 模型密钥")

    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            description,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )

    if not ok:
        error_code = ctypes.get_last_error()
        raise SecretError(f"Windows DPAPI 调用失败（错误码 {error_code}）")

    try:
        return _blob_to_bytes(output_blob)
    finally:
        kernel32.LocalFree(output_blob.pbData)


# --------------------------------------------------------------------------
# Fernet 回退方案
# --------------------------------------------------------------------------
def _fernet_key_path() -> Path:
    return settings.secrets_dir / "master.key"


def _load_fernet():
    from cryptography.fernet import Fernet

    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    key_path = _fernet_key_path()
    if not key_path.exists():
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    return Fernet(key_path.read_bytes())


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------
def active_scheme() -> str:
    """当前生效的加密方案，用于在接口里向用户说明密钥保护方式。"""
    return "windows-dpapi" if _dpapi_available() else "fernet-local-key"


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        raise SecretError("没有可加密的内容")

    raw = plaintext.encode("utf-8")
    if _dpapi_available():
        return DPAPI_PREFIX + base64.b64encode(_dpapi_crypt(raw, True)).decode("ascii")

    token = _load_fernet().encrypt(raw)
    return FERNET_PREFIX + token.decode("ascii")


def decrypt_secret(cipher_text: str) -> str:
    if not cipher_text:
        raise SecretError("没有可解密的内容")

    if cipher_text.startswith(DPAPI_PREFIX):
        if not _dpapi_available():
            raise SecretError("该密钥由 Windows DPAPI 加密，只能在原 Windows 用户下解密")
        blob = base64.b64decode(cipher_text[len(DPAPI_PREFIX) :])
        try:
            return _dpapi_crypt(blob, False).decode("utf-8")
        except SecretError as exc:
            raise SecretError("密钥解密失败，请重新填写该配置的 API Key") from exc

    if cipher_text.startswith(FERNET_PREFIX):
        try:
            return _load_fernet().decrypt(cipher_text[len(FERNET_PREFIX) :].encode("ascii")).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 - 统一转成业务可读错误
            raise SecretError("密钥解密失败，请重新填写该配置的 API Key") from exc

    raise SecretError("无法识别的密钥存储格式")


def mask_secret(plaintext: str) -> str:
    """Write-only credential indicator, independent of length or value."""
    return "****" if plaintext else ""
