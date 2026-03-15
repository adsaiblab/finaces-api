"""
app/api/routes/comparison.py — Comparaison et Benchmarking
FinaCES V1.2 — Async Migration Sprint 2B
"""

import logging
from typing import List, Optional

from app.core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi_limiter.depends import RateLimiter

from app.db.database import get_db
from app.services.comparison_service import (
    compare_temporal,
    compare_by_market,
    compute_sector_benchmark,
    save_comparison_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Comparison"])


class ComparisonSessionCreate(BaseModel):
    market_ref: str
    name:       str
    case_ids:   List[str]


@router.get("/cases/{case_id}/comparison/temporal", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def api_compare_temporal(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Analyzes the temporal evolution of the ratios of a file."""
    result = await compare_temporal(case_id=case_id, db=db)
    return result


@router.get("/cases/{case_id}/comparison/benchmark", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def api_compute_benchmark(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Compares the candidate's ratios to sector benchmarks."""
    result = await compute_sector_benchmark(case_id=case_id, db=db)
    return result


@router.get("/comparison/market/{market_ref}", dependencies=[Depends(RateLimiter(times=2, seconds=60))])
async def api_compare_market(
    market_ref: str,
    db:         AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Compares all bidders in the same market (Risk Ranking)."""
    result = await compare_by_market(market_ref=market_ref, db=db)
    return result


@router.post("/comparison/sessions", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def api_save_session(
    body: ComparisonSessionCreate,
    db:   AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Saves a comparison session for a group of candidates."""
    session_id = await save_comparison_session(
        market_ref=body.market_ref,
        name=body.name,
        case_ids=body.case_ids,
        db=db,
    )
    return {"status": "ok", "session_id": session_id}
