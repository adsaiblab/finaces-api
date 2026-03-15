from app.core.security import get_current_user
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db.database import get_db
from app.services.scoring_service import process_scoring
from app.services.case_service import assert_case_status
from app.schemas.scoring_schema import ScorecardOutputSchema

router = APIRouter(
    prefix="/cases",
    tags=["Scoring Workflow"]
)

@router.post("/{case_id}/score", response_model=ScorecardOutputSchema)
async def api_compute_scoring(case_id: UUID, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Runs the async scoring pipeline to produce the final MCC-Grade Scorecard.
    Contains zero business logic — all exceptions bubble up to global exception handlers.
    """
    await assert_case_status(case_id=case_id, allowed_statuses=["DRAFT", "IN_ANALYSIS", "SCORING"], db=db)
    # Relay all exception hooks up to Global Handler definitions logic implicitly.
    scorecard_result = await process_scoring(case_id=case_id, db=db)
    return scorecard_result
