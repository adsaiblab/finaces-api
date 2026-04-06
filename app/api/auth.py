from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_limiter.depends import RateLimiter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.db.models import User
from app.core.security import verify_password, create_access_token
from app.exceptions.finaces_exceptions import AuthenticationError
from app.core.security import get_current_user
from app.core.audit import auth_login_success, auth_login_failure

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.get("/csrf-token")
async def get_csrf_token():
    """Endpoint to bootstrap XSRF-TOKEN cookie for non-browser clients."""
    return {"status": "ok"}

@router.post(
    "/login",
    dependencies=[
        # NOTE: RateLimiter keys on client IP. Behind a reverse proxy,
        # ensure X-Forwarded-For is forwarded and trusted (Phase 3 infra config).
        Depends(RateLimiter(times=5, seconds=60)),
    ],
)
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"

    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalars().first()

    # ── Branch 1: unknown user ────────────────────────────────────────────────
    # Timing attack mitigation: call verify_password() with a dummy hash even
    # when the user doesn't exist, so the response time is indistinguishable
    # from a valid user + wrong password case (bcrypt ~100 ms in both paths).
    # The dummy hash is intentionally invalid — bcrypt will return False after
    # running its full work factor.
    if not user:
        auth_login_failure(
            attempted_email=form_data.username,
            ip=client_ip,
            reason="user_not_found",
        )
        verify_password("dummy", "$2b$12$eImiTXuWVxfM37uY4JANjQ==")  # constant-time dummy
        raise AuthenticationError(message="Incorrect email or password")

    # ── Branch 2: wrong password ──────────────────────────────────────────────
    if not verify_password(form_data.password, user.hashed_password):
        auth_login_failure(
            attempted_email=form_data.username,
            ip=client_ip,
            reason="invalid_password",
        )
        raise AuthenticationError(message="Incorrect email or password")

    # ── Branch 3: inactive user ───────────────────────────────────────────────
    if not user.is_active:
        auth_login_failure(
            attempted_email=form_data.username,
            ip=client_ip,
            reason="inactive_user",
        )
        raise AuthenticationError(message="Inactive user")

    # ── Success ───────────────────────────────────────────────────────────────
    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role.value}
    )
    auth_login_success(user_email=user.email, ip=client_ip)
    return {"access_token": access_token, "token_type": "bearer"}
