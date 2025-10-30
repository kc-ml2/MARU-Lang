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
from maru_lang.configs.system_config import get_system_config

config = get_system_config()


def generate_anonymized_key(
    login_id: str,
    company_id: int,
    salt: str = None
) -> str:
    if salt is None:
        salt = config.auth.salt
    # Combine the inputs with the salt to build a deterministic anonymized key
    raw_data = f"{login_id}:{company_id}:{salt}"
    return hashlib.sha256(raw_data.encode()).hexdigest()


def create_jwt_token(
    data: dict,
    expires_delta: timedelta
) -> tuple[str, datetime]:
    """Create a JWT access token and return it with its expiry."""
    expires_at = datetime.now(timezone.utc)
    expires_at += expires_delta
    to_encode = data.copy()
    to_encode.update({"exp": expires_at})
    encoded_jwt = jwt.encode(
        to_encode,
        config.auth.secret_key,
        algorithm=config.auth.algorithm)
    return encoded_jwt, expires_at


def decode_token(token: str) -> dict | None:
    """Decode a JWT token and return its payload."""
    try:
        payload = jwt.decode(
            token,
            config.auth.secret_key,
            algorithms=[config.auth.algorithm])
        return payload
    except (jwt.ExpiredSignatureError, jwt.JWTError, ValidationError) as e:
        # print(f"Token decode error: {e}")
        return None


def get_key_spec(key: str):
    key_bytes = key.encode('utf-8')
    return key_bytes


def aes256_decrypt(target_str: str) -> str:
    try:
        # Decode the Base64-encoded cipher text
        decoded_data = base64.b64decode(target_str)

        # Initialize the AES cipher in ECB mode
        cipher = Cipher(algorithms.AES(get_key_spec(config.auth.secret_key)),
                        modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()

        # Perform AES decryption
        decrypted_data = decryptor.update(decoded_data) + decryptor.finalize()

        # Remove PKCS7 padding
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        unpadded_data = unpadder.update(decrypted_data) + unpadder.finalize()

        return unpadded_data.decode('utf-8')

    except Exception as e:
        raise Exception(f"Error during decryption: {str(e)}")


def aes256_encrypt(plain_text: str) -> str:
    try:
        # Convert the plain text to bytes
        plain_text_bytes = plain_text.encode('utf-8')

        # Apply PKCS7 padding
        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        padded_data = padder.update(plain_text_bytes) + padder.finalize()

        # Initialize the AES cipher in ECB mode
        cipher = Cipher(algorithms.AES(get_key_spec(config.auth.secret_key)),
                        modes.ECB(), backend=default_backend())
        encryptor = cipher.encryptor()

        # Perform AES encryption
        encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

        # Encode the ciphertext using Base64
        encrypted_base64_data = base64.b64encode(encrypted_data)

        # Return the encrypted string
        return encrypted_base64_data.decode('utf-8')

    except Exception as e:
        raise Exception(f"Error during encryption: {str(e)}")