"""Password hashing and signed session tokens for the optional built-in
authentication (see SECURITY.md and the design spec).

Standard library only: scrypt, hmac, secrets, base64, json.
"""

import hashlib
import hmac
import json
import math
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_DKLEN = 32

_SESSION_MAX_AGE = 30 * 24 * 3600
_CLOCK_SKEW = 60


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, maxmem=_SCRYPT_MAXMEM, dklen=_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, dk_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
        if not expected:
            return False
    except (ValueError, AttributeError):
        return False
    try:
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=salt,
            n=int(n), r=int(r), p=int(p), maxmem=_SCRYPT_MAXMEM, dklen=len(expected),
        )
    except (ValueError, OverflowError, TypeError):
        return False
    return hmac.compare_digest(dk, expected)


def _b64(raw: bytes) -> str:
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    return urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: str, payload: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), payload.encode("ascii"),
                         hashlib.sha256).digest())


def make_session_token(secret: str, cred_version: int, *, now: int | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = _b64(json.dumps({"iat": issued, "v": int(cred_version)},
                              separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_sign(secret, payload)}"


def parse_session_token(token: str, secret: str, cred_version: int, *,
                        max_age: int = _SESSION_MAX_AGE, now: int | None = None) -> bool:
    try:
        payload, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(secret, payload)):
            return False
        data = json.loads(_unb64(payload))
        iat = int(data["iat"])
        version = int(data["v"])
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeEncodeError):
        return False
    if version != int(cred_version):
        return False
    age = int(now if now is not None else time.time()) - iat
    return -_CLOCK_SKEW <= age <= max_age
