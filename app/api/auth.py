from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_limiter.depends import RateLimiter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.db.models import User
from app.core.security import verify_password, create_access_token
from app.exceptions.finaces_exceptions import AuthenticationError
from app.core.security import get_current_user

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post(
    "/login",
    dependencies=[
        # NOTE: RateLimiter keys on client IP. Behind a reverse proxy,
        # ensure X-Forwarded-For is forwarded and trusted (Phase 3 infra config).
        Depends(RateLimiter(times=5, seconds=60)),
    ],
)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    # Try fetching user
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalars().first()

    # Authenticate
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise AuthenticationError(message="Incorrect email or password")
    
    if not user.is_active:
        raise AuthenticationError(message="Inactive user")

    # Create JWT
    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role.value}
    )
    
    return {"access_token": access_token, "token_type": "bearer"}
