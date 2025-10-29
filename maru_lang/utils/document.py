import base64
import hashlib
import os
import sys
import time
import random
import uuid


def new_ulid() -> str:
    """
    Generate a time-sortable identifier.

    - Use ``uuid.uuid7`` when available (Python 3.12+).
    - Otherwise, fall back to a ULID-style implementation.
    """
    # Detect uuid7 support at runtime
    if hasattr(uuid, 'uuid7'):
        return str(uuid.uuid7())

    # ULID fallback implementation
    # Format: 26 characters (10 timestamp + 16 randomness)
    timestamp_ms = int(time.time() * 1000)
    randomness = random.getrandbits(80)

    # Crockford's Base32 alphabet
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

    # Encode timestamp (10 characters)
    ts_encoded = ""
    ts = timestamp_ms
    for _ in range(10):
        ts_encoded = alphabet[ts & 0x1F] + ts_encoded
        ts >>= 5

    # Encode randomness (16 characters)
    rand_encoded = ""
    rand = randomness
    for _ in range(16):
        rand_encoded = alphabet[rand & 0x1F] + rand_encoded
        rand >>= 5

    return ts_encoded + rand_encoded


def canonicalize_text(s: str) -> str:
    return " ".join((s or "").split()).lower()


def make_source_fingerprint_for_file(filename: str, size: int, mtime_ns: int) -> str:
    """
    Generate a fingerprint that captures changes to file contents.

    Args:
        filename: File name without the path component.
        size: File size in bytes.
        mtime_ns: Modification time in nanoseconds.

    Returns:
        str: 32-character SHA256 hash.

    Note:
        The filesystem path is excluded so the fingerprint remains stable when
        files move between directories. Documents are identified by
        ``file_path`` while the fingerprint captures content changes only.
    """
    raw = f"{filename.lower()}|{size}|{mtime_ns}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]  # 128bit

def make_chunk_uid(document_id: str, number: int, content: str) -> str:
    raw = f"{document_id}|{number}|{canonicalize_text(content)}"
    d = hashlib.sha256(raw.encode()).digest()
    return base64.b32encode(d).decode("ascii").rstrip("=").lower()[:26]


def make_embed_id(chunk_uid: str, model_name: str, dim: int, normalize_ver: str, pooling: str, lang_hint: str | None = None) -> str:
    raw = "|".join([chunk_uid, model_name, str(
        dim), normalize_ver, pooling, lang_hint or ""])
    d = hashlib.sha256(raw.encode()).digest()
    return base64.b32encode(d).decode("ascii").rstrip("=").lower()[:26]
