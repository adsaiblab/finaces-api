"""
app/api/routes/cases.py — Evaluation case CRUD operations.
Sprint 2B: Lean Router — all business logic is in case_service.py.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user, RequireRole
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.db.models import EvaluationCase, Bidder
from app.services.case_service import create_evaluation_case, transition_status, STATUS_LABELS
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cases",
    tags=["Cases"]
)


# ─────────────────────────────────────────────────────────────────
# Request Schemas
# ─────────────────────────────────────────────────────────────────

class ConsortiumMemberCreate(BaseModel):
    case_id: str
    bidder_id: Optional[str] = None
    role: str
    participation_pct: float


class CaseCreate(BaseModel):
    case_type: str = "SINGLE"
    market_reference: str
    market_label: str
    contract_value: float = 0.0
    contract_currency: str = "USD"
    contract_duration_months: int = 12
    notes: str = ""
    # SINGLE
    bidder_id: Optional[str] = None
    bidder_name: Optional[str] = None
    legal_form: Optional[str] = "SA"
    registration_number: Optional[str] = ""
    country: Optional[str] = ""
    sector: Optional[str] = "AUTRE"
    contact_email: Optional[str] = ""
    # CONSORTIUM
    consortium_name: Optional[str] = None
    jv_type: Optional[str] = "JOINT_AND_SEVERAL"
    members: Optional[List[ConsortiumMemberCreate]] = None


class StatusTransition(BaseModel):
    new_status: str


class RecommendationUpdate(BaseModel):
    recommendation: str


class ConclusionUpdate(BaseModel):
    conclusion: str


# ─────────────────────────────────────────────────────────────────
# Response Schemas
# ─────────────────────────────────────────────────────────────────

class CaseStatusResponse(BaseModel):
    status: str


class EvaluationCaseOut(BaseModel):
    id: str
    case_type: str
    market_reference: Optional[str] = None
    status: str
    recommendation: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class EvaluationCaseDetailOut(BaseModel):
    id: str
    case_type: str
    bidder_id: Optional[str] = None
    consortium_id: Optional[str] = None
    market_reference: Optional[str] = None
    contract_value: Optional[float] = None
    contract_currency: Optional[str] = None
    contract_duration_months: Optional[int] = None
    status: str
    recommendation: Optional[str] = None
    analyst_notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.get("/bidders")
async def api_list_bidders(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Lists all bidders."""
    result = await db.execute(select(Bidder).order_by(Bidder.name))
    bidders = result.scalars().all()
    return [
        {
            "id": str(b.id),
            "name": b.name,
            "country": b.country or "N/A",
            "legal_form": b.legal_form,
            "registration_number": b.registration_number,
            "sector": b.sector,
            "contact_email": b.contact_email,
        }
        for b in bidders
    ]


@router.get("/single")
async def api_list_single_cases(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Lists SINGLE cases (for consortium member selection)."""
    result = await db.execute(
        select(EvaluationCase)
        .where(EvaluationCase.case_type == "SINGLE")
        .options(selectinload(EvaluationCase.bidder))
        .order_by(EvaluationCase.updated_at.desc())
    )
    cases = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "bidder_id": str(c.bidder_id) if c.bidder_id else None,
            "label": f"{c.market_reference or 'N/A'} — {c.bidder.name if c.bidder else ''}",
        }
        for c in cases
    ]


@router.get("", response_model=List[EvaluationCaseOut])
async def api_list_cases(
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lists cases with optional filters."""
    stmt = select(EvaluationCase)
    if status:
        stmt = stmt.where(EvaluationCase.status == status)
    if search:
        stmt = stmt.where(EvaluationCase.market_reference.ilike(f"%{search}%"))
    stmt = stmt.order_by(EvaluationCase.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("")
async def api_create_case(body: CaseCreate, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Creates a new evaluation case (SINGLE or CONSORTIUM).
    All business logic is delegated to `case_service.create_evaluation_case`.
    """
    case_id = await create_evaluation_case(
        case_type=body.case_type,
        market_reference=body.market_reference,
        market_label=body.market_label,
        contract_value=body.contract_value,
        contract_currency=body.contract_currency,
        contract_duration_months=body.contract_duration_months,
        notes=body.notes,
        db=db,
        # SINGLE
        bidder_id=body.bidder_id,
        bidder_name=body.bidder_name,
        legal_form=body.legal_form,
        registration_number=body.registration_number,
        country=body.country,
        sector=body.sector,
        contact_email=body.contact_email,
        # CONSORTIUM
        consortium_name=body.consortium_name,
        jv_type=body.jv_type,
        members=body.members,
        user_id=current_user.get("sub", "SYSTEM"), # <-- FIX P1-AUDIT-07
    )
    return {"case_id": case_id}


@router.get("/{case_id}", response_model=EvaluationCaseDetailOut)
async def api_get_case(case_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Returns a complete case profile."""
    result = await db.execute(
        select(EvaluationCase).where(EvaluationCase.id == case_id)
    )
    case = result.scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return EvaluationCaseDetailOut.model_validate(case)


@router.get("/{case_id}/status", response_model=CaseStatusResponse)
async def api_get_case_status(case_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Returns only the case status."""
    result = await db.execute(
        select(EvaluationCase).where(EvaluationCase.id == case_id)
    )
    case = result.scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseStatusResponse(status=str(case.status))


@router.patch("/{case_id}/status")
async def api_transition_status(
    case_id: uuid.UUID,
    body: StatusTransition,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Applies a status transition via the state machine.
    Guard validation is delegated to `transition_status` in case_service.
    """
    case = await transition_status(
        case_id=case_id, # FIX P1-1 : Strict UUID typing
        new_status=body.new_status,
        db=db,
        user_id=current_user.get("sub", "SYSTEM"),
    )
    return {
        "status": "ok",
        "case_id": str(case_id),
        "new_status": case.status,
        "new_status_label": STATUS_LABELS.get(str(case.status), str(case.status)),
    }


@router.post("/{case_id}/status")
async def api_transition_status_post(
    case_id: uuid.UUID,
    body: StatusTransition,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    POST alias for status transition (backward compatibility).
    Prefer PATCH for new clients.
    """
    case = await transition_status(
        case_id=case_id, # FIX P1-1 : Strict UUID typing
        new_status=body.new_status,
        db=db,
        user_id=current_user.get("sub", "SYSTEM"),
    )
    return {
        "status": "ok",
        "new_status": case.status,
        "new_status_label": STATUS_LABELS.get(str(case.status), str(case.status)),
    }


@router.post("/{case_id}/recommendation")
async def api_update_recommendation(
    case_id: uuid.UUID,
    body: RecommendationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(RequireRole(["ADMIN", "SENIOR_FIDUCIARY"])),
):
    """Updates the fiduciary recommendation."""
    from app.services.case_service import update_recommendation
    await update_recommendation(
        case_id=case_id,
        recommendation=body.recommendation,
        db=db,
        user_id=current_user.get("sub", "SYSTEM")
    )
    return {"status": "ok"}


@router.patch("/{case_id}/conclusion")
async def api_save_conclusion(
    case_id: uuid.UUID,
    body: ConclusionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(RequireRole(["ADMIN", "SENIOR_FIDUCIARY"])),
):
    """Persists the board's conclusion in analyst_notes."""
    from app.services.case_service import update_conclusion
    await update_conclusion(
        case_id=case_id,
        conclusion=body.conclusion,
        db=db,
        user_id=current_user.get("sub", "SYSTEM")
    )
    logger.info(f"Conclusion saved for case {str(case_id)} ({len(body.conclusion)} chars).")
    return {"status": "ok", "case_id": str(case_id), "conclusion_length": len(body.conclusion)}
