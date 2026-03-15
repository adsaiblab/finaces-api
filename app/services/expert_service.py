import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db.models import ExpertReview, Scorecard
from app.schemas.expert_schema import ExpertReviewInputSchema, ExpertReviewOutputSchema
from app.exceptions.finaces_exceptions import MissingFinancialDataError
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)


async def submit_expert_review(
    case_id: UUID,
    payload: ExpertReviewInputSchema,
    db: AsyncSession
) -> ExpertReviewOutputSchema:
    """
    Async Orchestrator (Expert Review):
    1. Verifies that a Scorecard exists — non-negotiable business prerequisite.
    2. Creates and persists the ExpertReview.
    3. Returns the output schema hydrated from the ORM.
    """
    logger.info(f"Submitting expert review for case {case_id}")

    # 1. Prerequisite: Mandatory Scorecard
    res = await db.execute(
        select(Scorecard)
        .where(Scorecard.case_id == case_id)
        .order_by(desc(Scorecard.computed_at))
        .limit(1)
    )
    scorecard = res.scalars().first()

    if not scorecard:
        raise MissingFinancialDataError(
            f"No validated Scorecard found for case {case_id}. "
            "Expert review can only be submitted after the Scoring stage."
        )

    # 2. ExpertReview Creation
    review = ExpertReview(
        case_id=case_id,
        analyst_id=payload.analyst_id,
        qualitative_notes=payload.qualitative_notes,
        manual_risk_override=payload.manual_risk_override,
        final_decision=payload.final_decision,
    )

    db.add(review)
    await db.commit()
    await db.refresh(review)

    # ─ Audit Trail (MCC-Grade Compliance) ─────────────────────
    await log_event(
        db=db,
        event_type="EXPERT_REVIEW_SUBMITTED",
        entity_type="ExpertReview",
        entity_id=str(review.id),
        case_id=str(case_id),
        description=f"Expert review submitted by analyst {payload.analyst_id} with final decision: {payload.final_decision}"
    )

    return ExpertReviewOutputSchema.model_validate(review)
