"""Pure rules of the slack namespace: the link code's alphabet, its shape on
the wire, and its digest. Values in, values out."""

import hashlib
import secrets

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
"""No 0, O, 1, I, or L: a code is read off one screen and typed into another."""

CODE_LENGTH = 8


def new_link_code() -> str:
    """A fresh code, shown as two groups of four: `ABCD-EFGH`. Forty bits of
    randomness, which is plenty for something that works once and for
    minutes."""
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def normalized_code(typed: str) -> str:
    """What a person typed, as the code it means: case, spaces, and the dash
    do not matter."""
    return "".join(ch for ch in typed.upper() if ch.isalnum())


def code_digest(typed: str) -> str:
    """The SHA-256 digest of the normalized code: the only form stored."""
    return hashlib.sha256(normalized_code(typed).encode()).hexdigest()
