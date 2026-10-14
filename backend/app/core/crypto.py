"""Symmetric encryption for the credential vault (see docs/adr/0006)."""

import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.core.errors import ServiceUnavailableError


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().credentials_key.get_secret_value()
    if not key:
        raise ServiceUnavailableError("CREDENTIALS_KEY is not configured on this server")
    return Fernet(key.encode())


def encrypt_json(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> dict[str, Any]:
    try:
        return dict(json.loads(_fernet().decrypt(token.encode())))
    except InvalidToken as exc:
        raise ServiceUnavailableError("Stored credential could not be decrypted") from exc
