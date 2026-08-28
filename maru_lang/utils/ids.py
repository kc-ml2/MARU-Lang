"""Time-sortable identifiers."""
import secrets
import time
import uuid


def new_ulid() -> str:
    if hasattr(uuid, "uuid7"):
        return str(uuid.uuid7())

    timestamp_ms = int(time.time() * 1000)
    randomness = secrets.randbits(80)
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

    timestamp = ""
    for _ in range(10):
        timestamp = alphabet[timestamp_ms & 0x1F] + timestamp
        timestamp_ms >>= 5

    random_part = ""
    for _ in range(16):
        random_part = alphabet[randomness & 0x1F] + random_part
        randomness >>= 5

    return timestamp + random_part
