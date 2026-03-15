"""
app/api/routes/system.py — System and engine info
FinaCES V1.2 — Async Migration Sprint 3 (Real-time DB metrics & Async endpoints)
"""

from app.core.security import get_current_user
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.database import get_db

router = APIRouter(tags=["System"])

# Engines are pure functions in memory, so they are statutorily "ACTIVE" if the API is running.
ACTUAL_ENGINES = [
    {"id": "e1", "name": "NormalizationEngine", "status": "ACTIVE"},
    {"id": "e2", "name": "RatiosEngine",        "status": "ACTIVE"},
    {"id": "e3", "name": "ScoringEngine",       "status": "ACTIVE"},
    {"id": "e4", "name": "StressEngine",        "status": "ACTIVE"},
    {"id": "e5", "name": "GateEngine",          "status": "ACTIVE"},
    {"id": "e6", "name": "ComparisonEngine",    "status": "ACTIVE"},
]

@router.get("/system/engines")
async def api_get_engines(current_user: dict = Depends(get_current_user)):
    """Returns the list and status of evaluation engines."""
    return ACTUAL_ENGINES

@router.get("/system/db")
async def api_get_db_info(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Returns real database information directly from PostgreSQL."""
    try:
        # Retrieving the exact PostgreSQL version
        version_query = await db.execute(text("SELECT version();"))
        db_version = version_query.scalar()

        # Retrieving the actual size of the database
        size_query = await db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()));"))
        db_size = size_query.scalar()

        return {
            "engine":            db_version,
            "orm":               "SQLAlchemy 2.0 (asyncpg)",
            "storage":           db_size,
            "status":            "ONLINE",
        }
    except Exception as e:
        return {
            "engine":            "Unknown",
            "orm":               "SQLAlchemy 2.0 (asyncpg)",
            "storage":           "Unknown",
            "status":            "OFFLINE or ERROR",
        }
