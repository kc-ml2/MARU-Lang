import base64
import hashlib
import os
import sys
import time
import random
import uuid


def new_ulid() -> str:
    """
    시간순 정렬 가능한 ID 생성
    - uuid.uuid7 사용 가능하면 사용 (Python 3.12+)
    - 아니면 ULID 형식 직접 구현
    """
    # uuid7이 사용 가능한지 런타임에 체크
    if hasattr(uuid, 'uuid7'):
        return str(uuid.uuid7())

    # ULID 구현 (fallback)
    # 형식: 26자 (타임스탬프 10자 + 랜덤 16자)
    timestamp_ms = int(time.time() * 1000)
    randomness = random.getrandbits(80)

    # Crockford's Base32 알파벳
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

    # 타임스탬프 인코딩 (10자)
    ts_encoded = ""
    ts = timestamp_ms
    for _ in range(10):
        ts_encoded = alphabet[ts & 0x1F] + ts_encoded
        ts >>= 5

    # 랜덤 부분 인코딩 (16자)
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
    파일 내용 변경 감지를 위한 fingerprint 생성

    Args:
        filename: 파일 이름 (경로 제외)
        size: 파일 크기 (bytes)
        mtime_ns: 수정 시간 (nanoseconds)

    Returns:
        str: SHA256 해시 (32자)

    Note:
        경로(path)는 포함하지 않음 - 폴더 이동에 강건하게 하기 위함
        Document는 file_path로 식별하고, fingerprint는 내용 변경만 감지
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
