from app.core.security import get_current_user
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from decimal import Decimal
from fastapi_limiter.depends import RateLimiter
from sqlalchemy import select
import uuid as uuid_mod

from app.db.database import get_db
from app.services.stress_service import process_stress_simulation
from app.schemas.stress_schema import StressScenarioInputSchema, StressResultSchema, MacroShockInput, MacroShockResult, StressDecision

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


@router.post("/{case_id}/stress/macro")
async def run_macro_shock(case_id: str, payload: MacroShockInput, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Run macro shock stress test."""
    # Placeholder — actual engine call would go here
    return MacroShockResult(
        scenario_name=payload.scenario_name,
        solvency_status=StressDecision.SOLVENT,
        minimum_cash_position=Decimal("0.0"),
    )


@router.get("/{case_id}/stress")
async def get_stress_results(case_id: str, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Returns all stress test results for a case."""
    from app.db.models import StressScenario
    result = await db.execute(
        select(StressScenario).where(StressScenario.case_id == uuid_mod.UUID(case_id))
    )
    return result.scalars().all()
