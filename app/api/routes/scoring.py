from app.core.security import get_current_user
from fastapi import APIRouter, Depends, Request
from fastapi_limiter.depends import RateLimiter
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

@router.post(
    "/{case_id}/score",
    response_model=ScorecardOutputSchema,
    dependencies=[
        # Scoring triggers the full ML pipeline (XGBoost + LightGBM + SHAP).
        # 3 runs/60s is generous for legitimate use while blocking abuse.
        # NOTE: RateLimiter keys on client IP — ensure X-Forwarded-For is
        # trusted behind reverse proxy (Phase 3 infra config).
        Depends(RateLimiter(times=3, seconds=60)),
    ],
)
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
    await assert_case_status(case_id=case_id, allowed_statuses=["RATIOS_COMPUTED"], db=db)
    scorecard_result = await process_scoring(case_id=case_id, db=db)
    return scorecard_result


@router.get(
    "/{case_id}/score",
    response_model=ScorecardOutputSchema,
    summary="Get existing scorecard",
    description="Retrieves the latest calculated scorecard for a case without triggering a new calculation."
)
async def api_get_scoring(
    case_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Fetch already computed results from database.
    Returns 404 if no scorecard exists yet.
    """
    from app.services.scoring_service import get_existing_scorecard
    from fastapi import HTTPException

    scorecard = await get_existing_scorecard(case_id=case_id, db=db)
    if not scorecard:
        raise HTTPException(
            status_code=404, 
            detail="No scorecard found for this case. Please compute it first."
        )
    return scorecard