import base64
import hashlib
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


def make_source_fingerprint_for_file(file_path: str, size: int, mtime_ns: int) -> str:
    """
    Generate a fingerprint that captures changes to file contents and location.

    Args:
        file_path: Full file path (used to distinguish same files in different locations).
        size: File size in bytes.
        mtime_ns: Modification time in nanoseconds.

    Returns:
        str: 32-character SHA256 hash.

    Note:
        The full file path is included to allow the same file to exist in different
        directories as separate documents. This handles cases where:
        - Files are copied to multiple locations
        - Folder names are changed (creating a new document context)
        - Backup or versioned copies exist in different paths
    """
    raw = f"{file_path.lower()}|{size}|{mtime_ns}"
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
