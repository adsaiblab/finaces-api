from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

from app.core.config import settings

# Database URL is sourced exclusively from settings (environment variable), never hardcoded.
DATABASE_URL = settings.DATABASE_URL

# Create the async engine with explicitly requested pool parameters
engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=15,
    echo=False,  # Set to True for debugging SQL queries
)

# Create an async session maker
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to yield an async database session for API routes.
    Includes explicit rollback on error to guarantee ACID compliance (P0-07).
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
