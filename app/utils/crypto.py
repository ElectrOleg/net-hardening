"""Encryption utilities for database fields."""

import base64
import hashlib

from cryptography.fernet import Fernet
from sqlalchemy.types import Text, TypeDecorator

from app.config import settings


class EncryptedText(TypeDecorator):
    """Transparently encrypts and decrypts text fields using Fernet.

    Derives key from settings.SECRET_KEY. Falls back to raw text on
    decryption failures (e.g. if key changes or database has legacy data).
    """

    impl = Text
    cache_ok = True

    def _get_fernet(self) -> Fernet:
        # Derive a 32-byte key from settings.SECRET_KEY
        key_hash = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(key_hash)
        return Fernet(key)

    def process_bind_param(self, value, dialect) -> str | None:
        if value is None:
            return None
        f = self._get_fernet()
        return f.encrypt(value.encode("utf-8")).decode("utf-8")

    def process_result_value(self, value, dialect) -> str | None:
        if value is None:
            return None
        f = self._get_fernet()
        try:
            return f.decrypt(value.encode("utf-8")).decode("utf-8")
        except Exception:
            # Fallback for unencrypted legacy data or changed keys
            return value
