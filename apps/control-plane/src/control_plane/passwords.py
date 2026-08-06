from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, candidate: str) -> bool:
    try:
        _hasher.verify(stored_hash, candidate)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return True


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


DUMMY_HASH = _hasher.hash("dummy")
