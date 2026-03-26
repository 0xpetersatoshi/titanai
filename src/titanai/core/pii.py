import hashlib
import hmac
import re

from titanai.core.config import get_settings

_WHITESPACE = re.compile(r"\s+")


def _get_key() -> bytes:
    return get_settings().pii_secret_key.encode()


def hash_email(plaintext: str) -> str:
    normalized = plaintext.strip().lower()
    return hmac.new(_get_key(), normalized.encode(), hashlib.sha256).hexdigest()


def hash_name(plaintext: str) -> str:
    normalized = _WHITESPACE.sub(" ", plaintext.strip()).lower()
    return hmac.new(_get_key(), normalized.encode(), hashlib.sha256).hexdigest()
