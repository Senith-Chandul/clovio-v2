import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models import User

# scrypt from the standard library: 32 MiB of memory per hash. Passwords are for dev and demo accounts only.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1


def _scrypt(password: str, salt: bytes, n: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=SCRYPT_R, p=SCRYPT_P, maxmem=2**26)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${SCRYPT_N}${salt.hex()}${_scrypt(password, salt, SCRYPT_N).hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        scheme, n, salt, digest = (stored or "").split("$")
        if scheme != "scrypt":
            return False
        actual = _scrypt(password, bytes.fromhex(salt), int(n))
    except ValueError:  # no password set, or a malformed hash
        return False
    return hmac.compare_digest(actual, bytes.fromhex(digest))


def create_token(user_id: uuid.UUID) -> str:
    expires = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expires}, settings.SECRET_KEY, algorithm="HS256")


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Sign in again: your session is missing or has expired.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=["HS256"])
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    if user is None:
        raise unauthorized
    return user
