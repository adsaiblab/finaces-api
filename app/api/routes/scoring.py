from app.core.security import get_current_user
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db.database import get_db
from app.services.scoring_service import process_scoring
from app.services.case_service import assert_case_status
from app.schemas.scoring_schema import ScorecardOutputSchema
from app.core.audit import data_access_sensitive

router = APIRouter(
    prefix="/cases",
    tags=["Scoring Workflow"]
)

@router.post("/{case_id}/score", response_model=ScorecardOutputSchema)
async def api_compute_scoring(
    request: Request,
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Runs the async scoring pipeline to produce the final MCC-Grade Scorecard.
    Contains zero business logic — all exceptions bubble up to global exception handlers.
    Emits data.access.sensitive audit event before processing (spec §8.6).
    """
    data_access_sensitive(
        user_email=current_user.get("sub", "unknown"),
        path=request.url.path,
        case_id=str(case_id),
    )
    await assert_case_status(case_id=case_id, allowed_statuses=["DRAFT", "IN_ANALYSIS", "SCORING"], db=db)
    scorecard_result = await process_scoring(case_id=case_id, db=db)
    return scorecard_result
