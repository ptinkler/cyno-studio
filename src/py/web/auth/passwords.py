"""Password hashing for local (email + password) admin accounts.

    stored = Fernet(pepper key).encrypt( argon2id( NFKC(password) ) )   # the salt is inside the argon2 string

The password goes straight into argon2id (after Unicode normalisation, so the same password typed on any
keyboard is the same bytes). The pepper (PASSWORD_PEPPER) is a server-only secret that encrypts the finished
argon2 string: a copy of the database alone holds only ciphertext, so offline guessing can't even start.
Set the pepper once and never change it.
"""

from __future__ import annotations

import base64
import hashlib
import os
import unicodedata
from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

_hasher = PasswordHasher()


def _pepper() -> bytes:
    """PASSWORD_PEPPER, else derived from SESSION_SECRET, else a dev fallback."""
    explicit = os.getenv("PASSWORD_PEPPER", "").strip()
    if explicit:
        return explicit.encode()
    session_secret = os.getenv("SESSION_SECRET", "").strip()
    return session_secret.encode() if session_secret else b"dev"


def _cipher() -> Fernet:
    """The cipher that wraps a finished argon2 string, keyed from the pepper."""
    key = hashlib.sha256(b"cyno-password-pepper-v2\x00" + _pepper()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _typed(password: str) -> bytes:
    """The password as it is typed, Unicode-normalised (NFKC) and encoded for argon2."""
    return unicodedata.normalize("NFKC", password).encode("utf-8")


def hash_password(password: str) -> str:
    """A storable hash: the password's argon2id hash (unique salt inside), encrypted with the pepper."""
    return _cipher().encrypt(_hasher.hash(_typed(password)).encode()).decode()


def _argon2_of(stored_hash: str) -> str | None:
    """The argon2 string inside a stored hash (None when it isn't ours or the pepper differs)."""
    try:
        return _cipher().decrypt(stored_hash.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Whether `password` matches the stored hash.

    False (never raises) for a missing hash, a wrong password, a wrong pepper, or a malformed/foreign hash string.
    """
    argon2_hash = _argon2_of(stored_hash) if stored_hash else None
    if argon2_hash is None:
        return False
    try:
        return _hasher.verify(argon2_hash, _typed(password))
    except (VerificationError, InvalidHashError):  # a mismatch
        return False


@cache
def _stand_in_hash() -> str:
    return hash_password("not any account's password")


def spend_verification_time(password: str) -> None:
    """Do the work of checking a password for an account that doesn't exist.

    A missing account would otherwise answer as fast as a hash check is slow, and the difference
    says which emails have accounts.
    """
    verify_password(_stand_in_hash(), password)


def needs_rehash(stored_hash: str) -> bool:
    """Whether a stored hash was made with weaker-than-current argon2 params.

    The caller can then transparently upgrade it on the next successful login.
    """
    argon2_hash = _argon2_of(stored_hash)
    if argon2_hash is None:
        return False
    try:
        return _hasher.check_needs_rehash(argon2_hash)
    except InvalidHashError:
        return False
