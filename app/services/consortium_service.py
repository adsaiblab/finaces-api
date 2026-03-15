import logging
from uuid import UUID
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from app.db.models import EvaluationCase, ConsortiumMember, Scorecard, ConsortiumResult
from app.schemas.consortium_schema import ConsortiumInputSchema, ConsortiumMemberInput, ConsortiumScorecardOutput
from app.engines.consortium_engine import compute_consortium_scorecard
from app.exceptions.finaces_exceptions import MissingFinancialDataError
from app.schemas.policy_schema import PolicyConfigurationSchema
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

async def _get_active_policy(db: AsyncSession) -> PolicyConfigurationSchema:
    """Mock Service for Policy Engine"""
    return PolicyConfigurationSchema(version_id="mock_active_policy_v2")

async def process_consortium_evaluation(case_id: UUID, db: AsyncSession) -> ConsortiumScorecardOutput:
    """
    Async Orchestrator (Consortium Validation):
    1. Retrieves the parent Case and validates its Consortium type.
    2. Retrieves all Consortium members (ConsortiumMember).
    3. For each member, extracts the latest validated `Scorecard`.
    4. Compile members according to ConsortiumInputSchema.
    5. Executes the pure Consortium engine (`compute_consortium_scorecard`).
    6. Persists the `ConsortiumResult` in the DB and commits.
    """
    logger.info(f"Starting async Consortium Evaluation for case {case_id}")

    # 1. Obtain parent case
    stmt_case = (
        select(EvaluationCase)
        .options(selectinload(EvaluationCase.consortium))
        .where(EvaluationCase.id == case_id)
    )
    res_case = await db.execute(stmt_case)
    parent_case = res_case.scalars().first()

    if not parent_case:
        raise ValueError(f"Case {case_id} not found.")
        
    if not parent_case.consortium_id:
        raise ValueError(f"Case {case_id} is not a Consortium case (missing consortium_id).")

    # 2. Retrieve consortium members
    stmt_members = (
        select(ConsortiumMember)
        .options(selectinload(ConsortiumMember.bidder))
        .where(ConsortiumMember.consortium_id == parent_case.consortium_id)
    )
    res_members = await db.execute(stmt_members)
    members_orm = res_members.scalars().all()

    if not members_orm:
        raise ValueError(f"Consortium {parent_case.consortium_id} has no members attached.")

    member_inputs = []

    # 3. Retrieve and verify individual scorecards
    for member in members_orm:
        if not member.individual_case_id:
            logger.warning(f"Consortium member {member.id} has no individual_case_id bound.")
            raise MissingFinancialDataError(f"Scorecard missing for consortium member {member.id} (no individual_case_id).")

        stmt_scorecard = (
            select(Scorecard)
            .where(Scorecard.case_id == member.individual_case_id)
            .order_by(desc(Scorecard.computed_at))
            .limit(1)
        )
        res_scorecard = await db.execute(stmt_scorecard)
        scorecard_orm = res_scorecard.scalars().first()

        if not scorecard_orm:
            logger.warning(f"Engine blocked: Missing Scorecard for member {member.id} within case {member.individual_case_id}")
            raise MissingFinancialDataError(f"Scorecard missing for consortium member {member.id}")

        member_inputs.append(
            ConsortiumMemberInput(
                bidder_id=str(member.bidder_id),
                bidder_name=member.bidder.name if member.bidder else "Unknown Bidder",
                role=member.role,
                participation_pct=member.participation_pct,
                score_global=scorecard_orm.score_global or Decimal("0.0"),
                score_liquidity=scorecard_orm.score_liquidity,
                score_solvency=scorecard_orm.score_solvency,
                score_profitability=scorecard_orm.score_profitability,
                score_capacity=scorecard_orm.score_capacity,
                final_risk_class=scorecard_orm.risk_class.name if scorecard_orm.risk_class else "UNKNOWN",
                stress_60d_result="N/A" # Mocked static due to lacking stress engine bindings
            )
        )

    # 4. Construct Engine Schema
    jv_type_val = parent_case.consortium.jv_type.name if parent_case.consortium and parent_case.consortium.jv_type else "UNKNOWN"
    
    consortium_input = ConsortiumInputSchema(
        consortium_id=str(parent_case.consortium_id),
        jv_type=jv_type_val,
        members=member_inputs
    )

    policy = await _get_active_policy(db)

    # 5. Injection to Pure Engine
    try:
        consortium_out = compute_consortium_scorecard(consortium_input=consortium_input, policy=policy)
    except Exception as e:
        logger.error(f"Computation pure consortium math crash on case {case_id}: {str(e)}")
        raise

    # 6. Upsert Result in ConsortiumResult
    stmt_result = select(ConsortiumResult).where(ConsortiumResult.case_id == case_id)
    res_result = await db.execute(stmt_result)
    existing_result = res_result.scalars().first()

    if existing_result:
        existing_result.jv_type = consortium_out.jv_type
        existing_result.aggregation_method = consortium_out.aggregation_method
        existing_result.weighted_score = consortium_out.weighted_score
        existing_result.synergy_index = consortium_out.synergy_index
        existing_result.synergy_bonus = consortium_out.synergy_bonus
        existing_result.base_risk_class = consortium_out.base_risk_class
        existing_result.final_risk_class = consortium_out.final_risk_class
        existing_result.weak_link_triggered = consortium_out.weak_link_triggered
        existing_result.weak_link_member = consortium_out.weak_link_member
        existing_result.leader_blocking = consortium_out.leader_blocking
        existing_result.leader_override = consortium_out.leader_override
        existing_result.aggregated_stress = consortium_out.aggregated_stress
        existing_result.members_json = consortium_out.members
        existing_result.mitigations_suggested_json = consortium_out.mitigations_suggested
        target_result = existing_result
    else:
        new_result = ConsortiumResult(
            case_id=case_id,
            consortium_id=parent_case.consortium_id,
            jv_type=consortium_out.jv_type,
            aggregation_method=consortium_out.aggregation_method,
            weighted_score=consortium_out.weighted_score,
            synergy_index=consortium_out.synergy_index,
            synergy_bonus=consortium_out.synergy_bonus,
            base_risk_class=consortium_out.base_risk_class,
            final_risk_class=consortium_out.final_risk_class,
            weak_link_triggered=consortium_out.weak_link_triggered,
            weak_link_member=consortium_out.weak_link_member,
            leader_blocking=consortium_out.leader_blocking,
            leader_override=consortium_out.leader_override,
            aggregated_stress=consortium_out.aggregated_stress,
            members_json=consortium_out.members,
            mitigations_suggested_json=consortium_out.mitigations_suggested
        )
        db.add(new_result)
        target_result = new_result

    await db.commit()
    await db.refresh(target_result)

    # ─ Audit Trail (MCC-Grade Compliance) ─────────────────────
    await log_event(
        db=db,
        event_type="CONSORTIUM_EVALUATED",
        entity_type="ConsortiumResult",
        entity_id=str(target_result.id),
        case_id=str(case_id),
        description=f"Consortium evaluated. Synergy index: {consortium_out.synergy_index}"
    )

    return consortium_out
