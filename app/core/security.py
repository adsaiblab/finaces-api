"""
app/core/security.py — P0-04 Fix: FastAPI authentication / authorization dependency.

Exposes:
  - `get_current_user`: FastAPI dependency used to protect /api/v1 routes.
  - Crypto helpers: `verify_password`, `get_password_hash`, `create_access_token`.
  - `RequireRole`: RBAC dependency.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Crypto helpers ─────────────────────────────────────────────────────────────
# Strict setup: bcrypt only to avoid passlib deprecation warnings on Python 3.12+
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# ── FastAPI Security Scheme ────────────────────────────────────────────────────
_bearer_scheme = HTTPBearer(auto_error=True)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing authentication token.",
    headers={"WWW-Authenticate": "Bearer"},
)

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    """
    FastAPI dependency — validates the Bearer JWT token on every protected route.

    Raises:
        HTTPException 401 – if token is absent, invalid, or expired.
    """
    if credentials is None:
        logger.warning("Request without Authorization header blocked by security layer.")
        raise _CREDENTIALS_EXCEPTION

    token = credentials.credentials

    # ── JWT validation ────────────────────────────────────────────
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": True},
        )
        subject: Optional[str] = payload.get("sub")
        if not subject:
            raise _CREDENTIALS_EXCEPTION
        return {"sub": subject, "role": payload.get("role", "ANALYST")}
    except jwt.ExpiredSignatureError:
        logger.warning("Expired JWT token rejected.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Expired token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as e:
        logger.warning(f"Invalid JWT token rejected: {e}")
        raise _CREDENTIALS_EXCEPTION

class RequireRole:
    """
    Dependency to enforce Role-Based Access Control (RBAC).
    Usage: Depends(RequireRole(["ADMIN", "SENIOR_FIDUCIARY"]))
    """
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: dict = Depends(get_current_user)) -> dict:
        user_role = current_user.get("role", "ANALYST")
        if user_role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Required roles: {self.allowed_roles}"
            )
        return current_user