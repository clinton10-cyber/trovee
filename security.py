"""Password hashing using hashlib.pbkdf2_hmac (stdlib only, no external deps).
This is a well-established, secure approach (NIST-recommended) when iteration
count is high enough; 260,000 rounds of SHA-256 matches Django's historical default.
"""

import hashlib
import secrets

PBKDF2_ITERATIONS = 260_000


def hash_password(plain_password: str) -> tuple[str, str]:
    """Returns (password_hash_hex, salt_hex)."""
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return derived.hex(), salt


def verify_password(plain_password: str, password_hash: str, salt: str) -> bool:
    derived = hashlib.pbkdf2_hmac(
        "sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return secrets.compare_digest(derived.hex(), password_hash)
