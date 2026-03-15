from app.core.security import get_current_user
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from fastapi_limiter.depends import RateLimiter

from app.db.database import get_db
from app.services.stress_service import process_stress_simulation
from app.schemas.stress_schema import StressScenarioInputSchema, StressResultSchema

router = APIRouter(
    prefix="/cases",
    tags=["Stress Test"]
)

@router.post("/{case_id}/stress/run", response_model=StressResultSchema, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def api_run_stress_simulation(
    case_id: UUID,
    payload: StressScenarioInputSchema,
    db: AsyncSession = Depends(get_db)
, current_user: dict = Depends(get_current_user)):
    """
    Runs a Stress simulation on an existing folder.

    The engine applies payload shocks to the basic normalized financial statements,
    re-executes the complete pipeline (Ratios → Gate → Scoring) on ​​the stressed data,
    and returns the comparative results persistently in `stress_scenarios`.
    """
    result = await process_stress_simulation(case_id=case_id, payload=payload, db=db)
    return result
