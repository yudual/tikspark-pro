from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings


ENCRYPTED_PREFIX = "fernet:"


class SecretService:
    def __init__(self) -> None:
        settings = get_settings()
        key_path = Path(settings.secret_key_path)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            key = key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            key_path.write_bytes(key)
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        if value.startswith(ENCRYPTED_PREFIX):
            return value
        token = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        return f"{ENCRYPTED_PREFIX}{token}"

    def decrypt(self, value: str) -> str:
        if not value.startswith(ENCRYPTED_PREFIX):
            return value
        token = value.removeprefix(ENCRYPTED_PREFIX).encode("ascii")
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Stored credential cannot be decrypted with the local secret key.") from exc


@lru_cache
def get_secret_service() -> SecretService:
    return SecretService()
