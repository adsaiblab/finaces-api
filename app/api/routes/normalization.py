from app.core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from typing import List
import logging
import uuid as uuid_mod

from app.db.database import get_db
from app.services.normalization_service import process_normalization
from app.schemas.normalization_schema import FinancialStatementNormalizedSchema
from app.exceptions.finaces_exceptions import FinaCESBaseException

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cases",
    tags=["Normalization Workflow"]
)

@router.post("/{case_id}/normalize", response_model=List[FinancialStatementNormalizedSchema])
async def api_normalize_case(case_id: UUID, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Starts the asynchronous normalization calculation for a given folder.
    The calculation is delegated to pure Engines without API I/O blocking.
    """
    try:
        normalized_statements = await process_normalization(case_id=case_id, db=db)
        return normalized_statements
        
    except FinaCESBaseException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected internal crash while processing Case UUID {case_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during normalization."
        )


@router.get("/{case_id}/normalized-financials")
async def get_normalized_financials(case_id: str, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Returns normalized financial statements for a case."""
    from app.db.models import FinancialStatementNormalized, FinancialStatementRaw
    raw_ids = await db.execute(
        select(FinancialStatementRaw.id).where(FinancialStatementRaw.case_id == uuid_mod.UUID(case_id))
    )
    raw_id_list = [r[0] for r in raw_ids.fetchall()]
    if not raw_id_list:
        return []
    result = await db.execute(
        select(FinancialStatementNormalized).where(
            FinancialStatementNormalized.raw_statement_id.in_(raw_id_list)
        )
    )
    return result.scalars().all()
