"""
app/services/case_service.py — Business orchestration for evaluation cases.
Sprint 2B: Clean Architecture + State Machine + Audit Trail.
"""

import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.db.models import (
    EvaluationCase,
    Bidder,
    Consortium,
    ConsortiumMember,
    FinancialStatementNormalized,
    FinancialStatementRaw,
    RatioSet,
    GateResult,
    Scorecard,
    ConsortiumResult,
    ExpertReview,
    MCCGradeReport,
)
from app.services.audit_service import log_event

# ════════════════════════════════════════════════════════════════
# SYSTEM CONSTANTS
# ════════════════════════════════════════════════════════════════

SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")

# ════════════════════════════════════════════════════════════════
# STATE MACHINE — Constants (ADR-05)
# ════════════════════════════════════════════════════════════════

VALID_TRANSITIONS: dict[str, list[str]] = {
    "DRAFT":              ["PENDING_GATE", "FINANCIAL_INPUT", "ARCHIVED"],
    "PENDING_GATE":       ["FINANCIAL_INPUT", "ARCHIVED"],
    "FINANCIAL_INPUT":    ["NORMALIZATION_DONE"],
    "NORMALIZATION_DONE": ["RATIOS_COMPUTED"],
    "RATIOS_COMPUTED":    ["SCORING_DONE"],
    "SCORING_DONE":       ["STRESS_DONE"],
    "STRESS_DONE":        ["EXPERT_REVIEWED"],
    "EXPERT_REVIEWED":    ["CLOSED"],
    "CLOSED":             ["ARCHIVED"],
    "ARCHIVED":           [],
}

STATUS_LABELS: dict[str, str] = {
    "DRAFT":              "Draft",
    "PENDING_GATE":       "Pending Gate",
    "FINANCIAL_INPUT":    "Financial Input",
    "NORMALIZATION_DONE": "Normalization Done",
    "RATIOS_COMPUTED":    "Ratios Computed",
    "SCORING_DONE":       "Scoring Done",
    "STRESS_DONE":        "Stress Done",
    "EXPERT_REVIEWED":    "Expert Reviewed",
    "CLOSED":             "Closed",
    "ARCHIVED":           "Archived",
}

RECOMMENDATION_LABELS: dict[str, str] = {
    "ACCEPT":             "✅ Acceptance",
    "CONDITIONAL_ACCEPT": "⚠️ Conditional Acceptance",
    "REJECT_RECOMMENDED": "❌ Rejection Recommended",
}


# ════════════════════════════════════════════════════════════════
# INVALIDATION PIPELINE IRB
# ════════════════════════════════════════════════════════════════

async def invalidate_case_pipeline(case_id: uuid.UUID, db: AsyncSession) -> None:
    """
    Purges all calculated results related to a case.

    Called BEFORE any commit modifying FinancialStatementRaw to ensure
    calculation consistency (Basel II/III compliance, audit traceability).

    Deletion order respecting FK constraints:
        ExpertReview / ConsortiumResult → Scorecard → GateResult → RatioSet → Normalized
    """
    logger.warning(f"[IRB] Invalidating full pipeline for case {case_id}…")

    await db.execute(delete(ExpertReview).where(ExpertReview.case_id == case_id))
    await db.execute(delete(ConsortiumResult).where(ConsortiumResult.case_id == case_id))
    await db.execute(delete(Scorecard).where(Scorecard.case_id == case_id))
    await db.execute(delete(GateResult).where(GateResult.case_id == case_id))
    await db.execute(delete(RatioSet).where(RatioSet.case_id == case_id))
    await db.execute(delete(MCCGradeReport).where(MCCGradeReport.case_id == case_id))

    # FinancialStatementNormalized has no direct case_id — join via raw
    raw_ids_result = await db.execute(
        select(FinancialStatementRaw.id).where(FinancialStatementRaw.case_id == case_id)
    )
    raw_ids = [row[0] for row in raw_ids_result.fetchall()]
    if raw_ids:
        await db.execute(
            delete(FinancialStatementNormalized).where(
                FinancialStatementNormalized.raw_statement_id.in_(raw_ids)
            )
        )

    await db.flush()
    await log_event(
        db=db,
        event_type="PIPELINE_INVALIDATED",
        entity_type="EvaluationCase",
        entity_id=str(case_id),
        case_id=str(case_id),
        description="Downstream calculation pipeline invalidated due to source data modification.",
    )
    logger.info(f"[IRB] Pipeline invalidated for case {case_id}.")


# ════════════════════════════════════════════════════════════════
# STATE MACHINE — transition_status
# ════════════════════════════════════════════════════════════════

async def transition_status(
    case_id:    uuid.UUID,
    new_status: str,
    db:         AsyncSession,
    user_id:    uuid.UUID = SYSTEM_USER_ID,
) -> EvaluationCase:
    """
    Applies a status transition while validating business guards.

    Guard 1: The transition must exist in VALID_TRANSITIONS.
    → Raises HTTPException 400 if invalid.

    Returns the updated EvaluationCase ORM object.
    """
    result = await db.execute(
        select(EvaluationCase).where(EvaluationCase.id == case_id)
    )
    case = result.scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")

    old_status = case.status.value if hasattr(case.status, 'value') else str(case.status)
    allowed = VALID_TRANSITIONS.get(old_status, [])

    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid transition: {old_status} → {new_status}. "
                f"Authorized transitions from '{old_status}': {allowed}"
            ),
        )

    case.status = new_status
    case.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(case)

    # Audit trail
    await log_event(
        db=db,
        event_type="CASE_STATUS_CHANGED",
        entity_type="EvaluationCase",
        entity_id=str(case_id),
        case_id=str(case_id),
        description=f"Status changed from {old_status} to {new_status}",
        old_value={"status": old_status},
        new_value={"status": new_status},
        user_id=user_id,
    )

    logger.info(f"Case {case_id} transitioned: {old_status} → {new_status}")
    return case


async def assert_case_status(
    case_id: uuid.UUID,
    allowed_statuses: list[str],
    db: AsyncSession,
) -> EvaluationCase:
    """
    Guard (P1-03): Ensures a case exists and is in one of the allowed statuses.
    Raises 404 if not found, 400 if status is not authorized.
    """
    result = await db.execute(select(EvaluationCase).where(EvaluationCase.id == case_id))
    case = result.scalars().first()

    if not case:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found.")

    current_status = case.status.value if hasattr(case.status, 'value') else str(case.status)
    if current_status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Action not allowed: Case {case_id} is in status '{current_status}'. "
                f"Required status: {allowed_statuses}"
            ),
        )

    return case


# ════════════════════════════════════════════════════════════════
# CASE CREATION — create_evaluation_case
# ════════════════════════════════════════════════════════════════

async def create_evaluation_case(
    *,
    case_type: str,
    market_reference: str,
    market_label: str,
    contract_value: float,
    contract_currency: str,
    contract_duration_months: int,
    notes: str,
    db: AsyncSession,
    # SINGLE fields
    bidder_id: Optional[str] = None,
    bidder_name: Optional[str] = None,
    legal_form: Optional[str] = None,
    registration_number: Optional[str] = None,
    country: Optional[str] = None,
    sector: Optional[str] = None,
    contact_email: Optional[str] = None,
    # CONSORTIUM fields
    consortium_name: Optional[str] = None,
    jv_type: Optional[str] = None,
    members: Optional[list] = None,
    # Actor
    user_id: uuid.UUID = SYSTEM_USER_ID,
) -> str:
    """
    Pure Service — Creates an evaluation case (SINGLE or CONSORTIUM).
    Returns the created case_id (str).
    Emits a CASE_CREATED event in the audit trail.
    """
    # ── SINGLE ────────────────────────────────────────────────────
    if case_type == "SINGLE":
        resolved_bidder_id: Optional[uuid.UUID] = None

        if bidder_id:
            resolved_bidder_id = uuid.UUID(bidder_id)
            res = await db.execute(select(Bidder).where(Bidder.id == resolved_bidder_id))
            existing = res.scalars().first()
            if existing:
                if bidder_name:
                    existing.name = bidder_name.strip()
                if legal_form:
                    existing.legal_form = legal_form
                if registration_number:
                    existing.registration_number = registration_number.strip() or None
                if country:
                    existing.country = country.strip() or None
                if sector:
                    existing.sector = sector
                if contact_email:
                    existing.contact_email = contact_email.strip() or None
                existing.updated_at = datetime.now(timezone.utc)

        elif bidder_name:
            new_bidder = Bidder(
                name=bidder_name.strip(),
                legal_form=legal_form,
                registration_number=(registration_number or "").strip() or None,
                country=(country or "").strip() or None,
                sector=sector,
                contact_email=(contact_email or "").strip() or None,
            )
            db.add(new_bidder)
            await db.flush()
            resolved_bidder_id = new_bidder.id
        else:
            raise HTTPException(
                status_code=400,
                detail="bidder_id or bidder_name required for SINGLE cases.",
            )

        new_case = EvaluationCase(
            case_type="SINGLE",
            market_reference=market_reference,
            market_object=market_label,
            contract_value=Decimal(str(contract_value)) if contract_value > 0 else None,
            contract_currency=contract_currency,
            contract_duration_months=contract_duration_months,
            bidder_id=resolved_bidder_id,
            analyst_notes=notes or None,
        )
        db.add(new_case)
        await db.commit()
        await db.refresh(new_case)

        logger.info(f"Case SINGLE created: {new_case.id} (bidder={resolved_bidder_id})")

        # Audit — Mission 2
        await log_event(
            db=db,
            event_type="CASE_CREATED",
            entity_type="EvaluationCase",
            entity_id=str(new_case.id),
            case_id=str(new_case.id),
            description=f"SINGLE case created — market reference: {market_reference}",
            new_value={"status": "DRAFT", "case_type": "SINGLE", "bidder_id": str(resolved_bidder_id)},
            user_id=user_id,
        )

        return str(new_case.id)

    # ── CONSORTIUM ────────────────────────────────────────────────
    elif case_type == "CONSORTIUM":
        if not consortium_name:
            raise HTTPException(status_code=400, detail="Consortium name required.")

        new_consortium = Consortium(
            name=consortium_name.strip(),
            jv_type=jv_type,
            market_reference=market_reference.strip(),
        )
        db.add(new_consortium)
        await db.flush()

        if members:
            for m in members:
                db.add(ConsortiumMember(
                    consortium_id=new_consortium.id,
                    bidder_id=uuid.UUID(m.bidder_id) if m.bidder_id else None,
                    individual_case_id=uuid.UUID(m.case_id) if m.case_id else None,
                    role=m.role,
                    participation_pct=Decimal(str(m.participation_pct)),
                ))
        await db.flush()

        new_case = EvaluationCase(
            case_type="CONSORTIUM",
            market_reference=market_reference,
            market_object=market_label,
            contract_value=Decimal(str(contract_value)) if contract_value > 0 else None,
            contract_currency=contract_currency,
            contract_duration_months=contract_duration_months,
            consortium_id=new_consortium.id,
            analyst_notes=notes or None,
        )
        db.add(new_case)
        await db.commit()
        await db.refresh(new_case)

        logger.info(f"Case CONSORTIUM created: {new_case.id} (consortium={new_consortium.id})")

        # Audit — Mission 2
        await log_event(
            db=db,
            event_type="CASE_CREATED",
            entity_type="EvaluationCase",
            entity_id=str(new_case.id),
            case_id=str(new_case.id),
            description=f"CONSORTIUM case created — market reference: {market_reference}",
            new_value={"status": "DRAFT", "case_type": "CONSORTIUM", "consortium_id": str(new_consortium.id)},
            user_id=user_id,
        )

        return str(new_case.id)

    # ── LOTS ────────────────────────────────────────────────────
    elif case_type == "LOTS":
        if not consortium_name:
            raise HTTPException(status_code=400, detail="Consortium name required for LOTS cases.")

        new_consortium = Consortium(
            name=consortium_name.strip(),
            jv_type=jv_type,
            market_reference=market_reference.strip(),
        )
        db.add(new_consortium)
        await db.flush()

        if members:
            for m in members:
                db.add(ConsortiumMember(
                    consortium_id=new_consortium.id,
                    bidder_id=uuid.UUID(m.bidder_id) if m.bidder_id else None,
                    individual_case_id=uuid.UUID(m.case_id) if m.case_id else None,
                    role=m.role,
                    participation_pct=Decimal(str(m.participation_pct)),
                ))
        await db.flush()

        new_case = EvaluationCase(
            case_type="LOTS",
            market_reference=market_reference,
            market_object=market_label,
            contract_value=Decimal(str(contract_value)) if contract_value > 0 else None,
            contract_currency=contract_currency,
            contract_duration_months=contract_duration_months,
            consortium_id=new_consortium.id,
            analyst_notes=notes or None,
        )
        db.add(new_case)
        await db.commit()
        await db.refresh(new_case)

        logger.info(f"Case LOTS created: {new_case.id} (consortium={new_consortium.id})")

        await log_event(
            db=db,
            event_type="CASE_CREATED",
            entity_type="EvaluationCase",
            entity_id=str(new_case.id),
            case_id=str(new_case.id),
            description=f"LOTS case created — market reference: {market_reference}",
            new_value={"status": "DRAFT", "case_type": "LOTS", "consortium_id": str(new_consortium.id)},
            user_id=user_id,
        )

        return str(new_case.id)

    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid case_type. Accepted values: SINGLE | CONSORTIUM | LOTS",
        )

# ════════════════════════════════════════════════════════════════
# RECOMMENDATION & CONCLUSION (ACID) - FIX P0-2
# ════════════════════════════════════════════════════════════════

async def update_recommendation(
    case_id: uuid.UUID,
    recommendation: str,
    db: AsyncSession,
    user_id: uuid.UUID = SYSTEM_USER_ID
) -> EvaluationCase:
    result = await db.execute(select(EvaluationCase).where(EvaluationCase.id == case_id))
    case = result.scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # <-- AJOUT P0 (State Machine Guard)
    current_status = case.status.value if hasattr(case.status, 'value') else str(case.status)
    if current_status in ["CLOSED", "ARCHIVED"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Operation forbidden. Case is locked in status: {case.status}"
        )

    case.recommendation = recommendation
    case.updated_at = datetime.now(timezone.utc)
    await db.commit()

    await log_event(
        db=db,
        event_type="RECOMMENDATION_UPDATED",
        entity_type="EvaluationCase",
        entity_id=str(case_id),
        case_id=str(case_id),
        description="Fiduciary recommendation updated.",
        user_id=user_id,
        new_value={"recommendation": recommendation},
    )
    return case

async def update_conclusion(
    case_id: uuid.UUID,
    conclusion: str,
    db: AsyncSession,
    user_id: uuid.UUID = SYSTEM_USER_ID
) -> EvaluationCase:
    result = await db.execute(select(EvaluationCase).where(EvaluationCase.id == case_id))
    case = result.scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # <-- AJOUT P0 (State Machine Guard)
    current_status = case.status.value if hasattr(case.status, 'value') else str(case.status)
    if current_status in ["CLOSED", "ARCHIVED"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Operation forbidden. Case is locked in status: {case.status}"
        )

    case.analyst_notes = conclusion
    case.updated_at = datetime.now(timezone.utc)
    await db.commit()

    await log_event(
        db=db,
        event_type="CONCLUSION_UPDATED",
        entity_type="EvaluationCase",
        entity_id=str(case_id),
        case_id=str(case_id),
        description="Analyst conclusion notes updated.",
        user_id=user_id,
    )
    return case
