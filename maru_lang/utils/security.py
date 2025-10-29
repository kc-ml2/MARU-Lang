import base64
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from fastapi import HTTPException, status
from pydantic import ValidationError
from maru_lang.core.settings import settings


def generate_anonymized_key(
    login_id: str,
    company_id: int,
    salt: str = settings.SALT
) -> str:
    # 입력값과 솔트를 조합하여 비식별 키 생성
    raw_data = f"{login_id}:{company_id}:{salt}"
    return hashlib.sha256(raw_data.encode()).hexdigest()


def create_jwt_token(
    data: dict,
    expires_delta: timedelta
) -> tuple[str, datetime]:
    """JWT Access Token을 생성하여 리턴"""
    expires_at = datetime.now(timezone.utc)
    expires_at += expires_delta
    to_encode = data.copy()
    to_encode.update({"exp": expires_at})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM)
    return encoded_jwt, expires_at


def decode_token(token: str) -> dict | None:
    """토큰을 디코딩해서 payload 리턴"""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM])
        return payload
    except (jwt.ExpiredSignatureError, jwt.JWTError, ValidationError) as e:
        # print(f"Token decode error: {e}")
        return None


def get_key_spec(key: str):
    key_bytes = key.encode('utf-8')
    return key_bytes


def aes256_decrypt(target_str: str) -> str:
    try:
        # Base64로 인코딩된 암호화된 문자열을 디코딩합니다.
        decoded_data = base64.b64decode(target_str)

        # AES cipher를 ECB 모드로 초기화합니다.
        cipher = Cipher(algorithms.AES(get_key_spec(settings.SECRET_KEY)),
                        modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()

        # AES 복호화를 수행합니다.
        decrypted_data = decryptor.update(decoded_data) + decryptor.finalize()

        # PKCS5 패딩 제거
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        unpadded_data = unpadder.update(decrypted_data) + unpadder.finalize()

        return unpadded_data.decode('utf-8')

    except Exception as e:
        raise Exception(f"Error during decryption: {str(e)}")


def aes256_encrypt(plain_text: str) -> str:
    try:
        # 평문을 UTF-8로 인코딩하여 바이트로 변환합니다.
        plain_text_bytes = plain_text.encode('utf-8')

        # PKCS7 패딩을 적용합니다.
        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        padded_data = padder.update(plain_text_bytes) + padder.finalize()

        # AES cipher를 ECB 모드로 초기화합니다.
        cipher = Cipher(algorithms.AES(get_key_spec(settings.SECRET_KEY)),
                        modes.ECB(), backend=default_backend())
        encryptor = cipher.encryptor()

        # AES 암호화를 수행합니다.
        encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

        # 암호화된 데이터를 Base64로 인코딩합니다.
        encrypted_base64_data = base64.b64encode(encrypted_data)

        # 최종적으로 암호화된 문자열을 반환합니다.
        return encrypted_base64_data.decode('utf-8')

    except Exception as e:
        raise Exception(f"Error during encryption: {str(e)}")