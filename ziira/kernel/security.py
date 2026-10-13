"""Password hashing, signed access tokens, random secrets, and credential encryption.

Passwords are hashed with scrypt. Access tokens are short-lived, HMAC-signed JSON:
`<base64 payload>.<base64 signature>`. Refresh tokens and API keys are random secrets
stored only as SHA-256 hashes. Tenant database credentials in the master database are
encrypted with Fernet (AES + HMAC) using a key derived from ZIIRA_CREDENTIALS_KEY.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ziira.kernel.config import get_settings
from ziira.kernel.errors import Unauthorized, ValidationFailed

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
MAX_PASSWORD_LENGTH = 1024        # longer ones are refused rather than hashed (no use as a way to burn CPU)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    """Return a salted scrypt hash, e.g. `scrypt$16384$8$1$<salt>$<hash>`."""
    if len(password) < 8:
        raise ValidationFailed("Password must be at least 8 characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValidationFailed(f"Password can be at most {MAX_PASSWORD_LENGTH} characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """True if the password matches the stored hash. Takes similar time when there is no hash."""
    if len(password) > MAX_PASSWORD_LENGTH:
        return False                  # cannot be a real password (see hash_password); do not spend time hashing it
    if not stored:
        # Spend the same effort so response time does not reveal whether the user exists.
        hashlib.scrypt(password.encode(), salt=b"0" * 16, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
        return False
    try:
        _, n, r, p, salt, digest = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, _unb64(digest))


# --------------------------------------------------------------------------- secrets
def new_secret() -> str:
    """A random URL-safe secret (256 bits)."""
    return secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    """SHA-256 of a refresh token or API key, as stored in the database."""
    return hashlib.sha256(secret.encode()).hexdigest()


# --------------------------------------------------------------------------- access tokens
def _signature(body: str) -> str:
    key = get_settings().secret_key.encode()
    return _b64(hmac.new(key, body.encode(), hashlib.sha256).digest())


def sign_token(payload: dict[str, Any], minutes: int) -> str:
    """Sign a payload that expires after `minutes`."""
    body = _b64(json.dumps({**payload, "exp": int(time.time()) + minutes * 60}).encode())
    return f"{body}.{_signature(body)}"


def read_token(token: str) -> dict[str, Any]:
    """Check the signature and expiry and return the payload. Raises Unauthorized."""
    try:
        body, signature = token.split(".")
    except ValueError:
        raise Unauthorized("Malformed token") from None
    if not hmac.compare_digest(signature, _signature(body)):
        raise Unauthorized("Invalid token")
    payload: dict[str, Any] = json.loads(_unb64(body))
    if payload.get("exp", 0) < time.time():
        raise Unauthorized("Token expired; refresh it or sign in again")
    return payload


# --------------------------------------------------------------------------- signed values
def sign_value(value: str) -> str:
    """A signature only this platform can make for `value` (for callback URLs, so a guessed id is useless)."""
    return hmac.new(get_settings().secret_key.encode(), f"value:{value}".encode(), hashlib.sha256).hexdigest()[:40]


def verify_value(value: str, signature: str) -> bool:
    """True if `signature` is the signature of `value`."""
    return hmac.compare_digest(sign_value(value), signature)


# --------------------------------------------------------------------------- credential encryption
@lru_cache
def _fernet(key: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def encrypt(plain: str) -> str:
    """Encrypt a secret (e.g. a database connection string) for storage."""
    return _fernet(get_settings().credentials_key).encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a value made by `encrypt`. Raises RuntimeError if the key is wrong."""
    try:
        return _fernet(get_settings().credentials_key).decrypt(token.encode()).decode()
    except InvalidToken:
        raise RuntimeError("Cannot decrypt stored credentials: check ZIIRA_CREDENTIALS_KEY") from None
