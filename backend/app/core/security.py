"""口令哈希与 JWT 签发/校验。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.config import settings

_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(raw: str) -> str:
    return _pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return _pwd_context.verify(raw, hashed)
    except ValueError:
        # 哈希串损坏时视为校验失败，不要让异常冒到接口层
        return False


def create_access_token(subject: str, role: str, extra: dict | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expire, "iat": datetime.now(timezone.utc)}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """解码失败抛 jwt 异常，由调用方转成 401。"""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def mask_key(key: str) -> str:
    """API Key 掩码：只保留前 4 后 4，供后台展示。"""
    if not key:
        return ""
    if len(key) <= 10:
        return key[:2] + "*" * max(len(key) - 2, 0)
    return f"{key[:4]}{'*' * 8}{key[-4:]}"
