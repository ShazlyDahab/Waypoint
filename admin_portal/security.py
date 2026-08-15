"""
Credential encryption at rest — Fernet (symmetric, authenticated encryption
from the `cryptography` package). This is disclosure protection, not real
access control: anyone with filesystem access to this host can read the
keyfile and decrypt everything, same as any local secret store with no
OS-level vault behind it. There's no auth system in this app to hang a KMS
off of, so this is the simplest thing that's actually safe rather than
storing passwords in plain text.

Key resolution order:
  1. OPS_CONSOLE_SECRET_KEY env var, if set (for deployments that inject
     secrets externally rather than storing a keyfile on disk).
  2. PROJECT_ROOT/.secrets/ops_console.key, generated on first run with
     0600 permissions. .secrets/ is gitignored.

Decrypted passwords must never be serialized into an HTTP response — only
used server-side to build an RTSP URL or test a connection. Every API
response that touches a credential returns {id, label, username} at most.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = PROJECT_ROOT / ".secrets"
KEY_FILE = SECRETS_DIR / "ops_console.key"

_fernet = None


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("OPS_CONSOLE_SECRET_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key

    if KEY_FILE.is_file():
        return KEY_FILE.read_bytes()

    SECRETS_DIR.mkdir(exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt_password(plaintext: str) -> bytes:
    return _get_fernet().encrypt(plaintext.encode())


def decrypt_password(ciphertext: bytes) -> str:
    try:
        return _get_fernet().decrypt(bytes(ciphertext)).decode()
    except InvalidToken as e:
        raise ValueError("Could not decrypt this credential — wrong key, or the key changed.") from e
