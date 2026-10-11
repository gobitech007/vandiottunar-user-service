import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime) -> datetime:
    """SQLite drops tzinfo; treat naive datetimes as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def generate_otp() -> str:
    length = get_settings().otp_length
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_otp(phone: str, code: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def otp_matches(phone: str, code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(phone, code), code_hash)


def _encode(payload: dict, minutes: int) -> str:
    s = get_settings()
    now = utcnow()
    payload = {**payload, "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])


def create_access_token(user_id: str, role: str) -> str:
    return _encode({"sub": user_id, "role": role, "typ": "access"}, get_settings().access_token_minutes)


def create_file_token(document_id: str) -> str:
    """Short-lived token so an <img src> can load a private document without an auth header."""
    return _encode({"sub": document_id, "typ": "file"}, get_settings().file_token_minutes)
