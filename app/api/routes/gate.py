from fastapi import APIRouter, Depends, Body
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.core.security import get_current_user
from app.db.database import get_db
from app.services.gate_service import process_gate_evaluation
from app.services.case_service import assert_case_status
from app.schemas.gate_schema import GateDecisionSchema

router = APIRouter(
    prefix="/cases",
    tags=["Gate Evaluation"]
)

@router.post("/{case_id}/gate/evaluate", response_model=GateDecisionSchema)
async def api_compute_gate(
    case_id: UUID, 
    body: dict = Body(None),
    db: AsyncSession = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    """
    Orchestrates the evaluation of the Gate (institutional knock-out).
    Verifies documentary compliance, Due Diligence, and financial bottom-up.
    Returns an asynchronous decision interceptable to Scoring.
    """
    await assert_case_status(case_id=case_id, allowed_statuses=["DRAFT", "PENDING_GATE", "IN_ANALYSIS", "SCORING"], db=db)
    decision = await process_gate_evaluation(case_id=case_id, db=db)
    return decision
