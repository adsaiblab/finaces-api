from app.core.security import get_current_user
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db.database import get_db
from app.services.expert_service import submit_expert_review
from app.schemas.expert_schema import ExpertReviewInputSchema, ExpertReviewOutputSchema
from app.core.security import RequireRole

router = APIRouter(
    prefix="/cases",
    tags=["Experts"]
)

_EXPERT_ROLES = RequireRole(["ADMIN", "SENIOR_FIDUCIARY", "LEAD_ANALYST"])


@router.post("/{case_id}/experts/review", response_model=ExpertReviewOutputSchema)
async def api_submit_expert_review(
    case_id: UUID,
    payload: ExpertReviewInputSchema,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(_EXPERT_ROLES)
):
    """
    Submits the analyst's qualitative opinion and final credit decision.

    Prerequisites: The case must have a computed Scorecard.
    Allowed decisions: `APPROVED`, `REJECTED`, `ESCALATED`.
    Restricted to: ADMIN, SENIOR_FIDUCIARY, LEAD_ANALYST roles.
    """
    return await submit_expert_review(case_id=case_id, payload=payload, db=db)
