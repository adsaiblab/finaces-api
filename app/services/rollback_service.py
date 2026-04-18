"""
app/services/rollback_service.py — Secure workflow rollback for ADMIN/SENIOR_FIDUCIARY.
Allows resetting a case to a prior status with targeted cascade deletion.
CLOSED and ARCHIVED cases are immutable.
"""

import uuid
import logging
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.db.models import (
    EvaluationCase,
    FinancialStatementRaw,
    FinancialStatementNormalized,
    RatioSet,
    GateResult,
    Scorecard,
    ExpertReview,
    ConsortiumResult,
    MCCGradeReport,
)
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

# Ordre des statuts dans le workflow
STATUS_ORDER = [
    "DRAFT",
    "PENDING_GATE",
    "FINANCIAL_INPUT",
    "NORMALIZATION_DONE",
    "RATIOS_COMPUTED",
    "SCORING_DONE",
    "STRESS_DONE",
    "EXPERT_REVIEWED",
    "CLOSED",
    "ARCHIVED",
]

# Statuts intouchables — jamais rollbackables
IMMUTABLE_STATUSES = {"CLOSED", "ARCHIVED"}

# Ce qu'on supprime selon la cible du rollback
# Clé = statut cible → on supprime TOUT ce qui a été calculé APRÈS ce statut
DELETION_MAP = {
    "FINANCIAL_INPUT": [
        "FinancialStatementNormalized",
        "RatioSet",
        "GateResult",
        "Scorecard",
        "ExpertReview",
        "ConsortiumResult",
        "MCCGradeReport",
    ],
    "NORMALIZATION_DONE": [
        "RatioSet",
        "Scorecard",
        "ExpertReview",
        "ConsortiumResult",
        "MCCGradeReport",
    ],
    "RATIOS_COMPUTED": [
        "Scorecard",
        "ExpertReview",
        "ConsortiumResult",
        "MCCGradeReport",
    ],
    "SCORING_DONE": [
        "ExpertReview",
        "ConsortiumResult",
        "MCCGradeReport",
    ],
    "STRESS_DONE": [
        "ExpertReview",
        "MCCGradeReport",
    ],
    "PENDING_GATE": [
        "FinancialStatementNormalized",
        "RatioSet",
        "GateResult",
        "Scorecard",
        "ExpertReview",
        "ConsortiumResult",
        "MCCGradeReport",
    ],
    "DRAFT": [
        "FinancialStatementNormalized",
        "RatioSet",
        "GateResult",
        "Scorecard",
        "ExpertReview",
        "ConsortiumResult",
        "MCCGradeReport",
    ],
}

MODEL_MAP = {
    "FinancialStatementNormalized": FinancialStatementNormalized,
    "RatioSet": RatioSet,
    "GateResult": GateResult,
    "Scorecard": Scorecard,
    "ExpertReview": ExpertReview,
    "ConsortiumResult": ConsortiumResult,
    "MCCGradeReport": MCCGradeReport,
}


async def rollback_case_to_status(
    case_id: uuid.UUID,
    target_status: str,
    reason: str,
    db: AsyncSession,
    user_id: uuid.UUID,
) -> EvaluationCase:
    """
    Resets a case to a prior workflow status with targeted cascade deletion.

    Rules:
    - CLOSED and ARCHIVED are immutable.
    - target_status must be strictly before current status in STATUS_ORDER.
    - All data computed after target_status is deleted.
    - The operation is fully logged in the audit trail.
    """
    result = await db.execute(select(EvaluationCase).where(EvaluationCase.id == case_id))
    case = result.scalars().first()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")

    current_status = case.status.value if hasattr(case.status, "value") else str(case.status)

    # Guard 1 — dossier verrouillé
    if current_status in IMMUTABLE_STATUSES:
        raise HTTPException(
            status_code=403,
            detail=f"Case {case_id} is locked (status: {current_status}). Rollback forbidden.",
        )

    # Guard 2 — statut cible valide
    if target_status not in STATUS_ORDER:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown target status: {target_status}. Valid: {STATUS_ORDER}",
        )

    # Guard 3 — cible doit être en arrière du statut actuel
    current_idx = STATUS_ORDER.index(current_status)
    target_idx = STATUS_ORDER.index(target_status)
    if target_idx >= current_idx:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Rollback target '{target_status}' must be before current status '{current_status}'."
            ),
        )

    # Guard 4 — raison obligatoire
    if not reason or len(reason.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="A reason of at least 10 characters is required for rollback.",
        )

    logger.warning(
        f"[ROLLBACK] Case {case_id}: {current_status} → {target_status} | reason: {reason} | user: {user_id}"
    )

    # ── Cascade deletion ──────────────────────────────────────────
    tables_to_delete = DELETION_MAP.get(target_status, [])

    for table_name in tables_to_delete:
        model = MODEL_MAP.get(table_name)
        if model is None:
            continue

        # FinancialStatementNormalized n'a pas de case_id direct — join via raw
        if model is FinancialStatementNormalized:
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
        else:
            await db.execute(delete(model).where(model.case_id == case_id))

    await db.flush()

    # ── Status update ─────────────────────────────────────────────
    case.status = target_status
    case.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(case)

    # ── Audit trail ───────────────────────────────────────────────
    await log_event(
        db=db,
        event_type="CASE_ROLLBACK",
        entity_type="EvaluationCase",
        entity_id=str(case_id),
        case_id=str(case_id),
        description=f"Workflow rollback: {current_status} → {target_status}. Reason: {reason}",
        old_value={"status": current_status},
        new_value={"status": target_status, "deleted_tables": tables_to_delete},
        user_id=user_id,
    )

    logger.info(f"[ROLLBACK] Case {case_id} successfully reset to {target_status}.")
    return case