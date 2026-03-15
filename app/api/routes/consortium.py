from app.core.security import get_current_user
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db.database import get_db
from app.services.consortium_service import process_consortium_evaluation
from app.schemas.consortium_schema import ConsortiumScorecardOutput

router = APIRouter(
    prefix="/cases",
    tags=["Consortium"]
)

@router.post("/{case_id}/consortium/calculate", response_model=ConsortiumScorecardOutput)
async def api_compute_consortium(case_id: UUID, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Orchestrates the overall evaluation of a group (Consortium).
    Aggregates member scores and calculates risk discount and mutual synergies.
    """
    decision = await process_consortium_evaluation(case_id=case_id, db=db)
    return decision
