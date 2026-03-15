from app.core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException, status
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
        await assert_case_status(case_id=case_id, allowed_statuses=["DRAFT", "IN_ANALYSIS", "SCORING"], db=db)
        ratio_sets = await process_ratios(case_id=case_id, db=db)
        return ratio_sets
        
    except FinaCESBaseException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected internal crash while computing ratios for Case UUID {case_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during ratio computation."
        )
