from app.core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List
import logging

from app.db.database import get_db
from app.services.ratio_service import process_ratios
from app.schemas.ratio_schema import RatioSetSchema
from app.services.case_service import assert_case_status
from app.exceptions.finaces_exceptions import FinaCESBaseException

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cases",
    tags=["Ratios Workflow"]
)

@router.post("/{case_id}/ratios/compute", response_model=List[RatioSetSchema])
async def api_compute_ratios(case_id: UUID, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Launches asynchronous analytical computation of Financial Ratios for a given case.
    The computation is delegated via the Service bus to pure Engines (Z-Score included).
    """
    try:
        from app.services.workflow_guards import assert_gate_passed
        await assert_gate_passed(case_id=case_id, db=db)

        await assert_case_status(case_id=case_id, allowed_statuses=["FINANCIAL_INPUT", "NORMALIZATION_DONE", "RATIOS_COMPUTED"], db=db)
        ratio_sets = await process_ratios(case_id=case_id, db=db)
        return ratio_sets
        
    except (FinaCESBaseException, HTTPException):
        raise
    except Exception as e:
        logger.exception(f"Unexpected internal crash while computing ratios for Case UUID {case_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during ratio computation."
        )


@router.get("/ratios/benchmarks")
async def get_benchmarks(sector: str = Query("DEFAULT"), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Returns benchmark ranges by sector."""
    from app.services.policy_service import get_active_policy
    policy = await get_active_policy(db)
    benchmarks = policy.sector_benchmarks.get(sector, policy.sector_benchmarks.get("DEFAULT", {}))
    return benchmarks
