import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from decimal import Decimal

from app.db.models import RatioSet, Scorecard, GateResult
from app.schemas.scoring_schema import ScorecardInputSchema, ScorecardOutputSchema
from app.schemas.ratio_schema import RatioSetSchema
from app.engines.scoring_engine import compute_pure_scorecard
from app.engines.ratio_to_score_engine import convert_ratios_to_scores
from app.exceptions.finaces_exceptions import MissingFinancialDataError
from app.services.policy_service import get_active_policy
from app.services.audit_service import log_event

async def process_scoring(case_id: UUID, db: AsyncSession) -> ScorecardOutputSchema:
    """
    Async Orchestrator (Scoring):
    1. Fetches the most recent RatioSet via selectinload (P0-02 Fix).
    2. Converts raw ratios to normalized 0-5 scores via convert_ratios_to_scores (P0-01 Fix).
    3. Hydrates ScorecardInputSchema with actual scores and Gate flags.
    4. Calls the pure engine compute_pure_scorecard.
    5. Upserts the Scorecard ORM by populating all pillar fields (P0-10 Fix).
    """
    logger.info(f"Starting async Scoring Engine orchestration for case {case_id}")

    # 1. P0-02: Fetch RatioSet with eager loading to avoid MissingGreenlet
    stmt = (
        select(RatioSet)
        .options(selectinload(RatioSet.normalized_statement))
        .where(RatioSet.case_id == case_id)
        .order_by(desc(RatioSet.fiscal_year))
        .limit(1)
    )
    result = await db.execute(stmt)
    ratio_set_orm = result.scalars().first()

    if not ratio_set_orm:
        logger.warning(f"Engine blocked: No RatioSet calculated yet for case {case_id}")
        raise MissingFinancialDataError(
            f"Unable to score case {case_id}. No financial ratios generated yet."
        )

    # Safe extraction of contract value from eagerly loaded statement
    norm_statement = ratio_set_orm.normalized_statement
    contract_value_extracted = norm_statement.revenue if norm_statement and norm_statement.revenue else Decimal("0.0")

    # 1.5 Fetch Gate Result
    stmt_gate = select(GateResult).where(GateResult.case_id == case_id)
    res_gate = await db.execute(stmt_gate)
    gate_orm = res_gate.scalars().first()

    if not gate_orm:
        logger.warning(f"Engine blocked: GateResult missing for scoring {case_id}")
        raise MissingFinancialDataError(
            f"Unable to process scoring for case {case_id}: Gate evaluation not found. Please execute Gate workflow first."
        )

    # 2. P0-01: Build RatioSetSchema and convert raw ratios → normalized 0-5 scores
    policy = await get_active_policy(db)

    ratio_schema = RatioSetSchema(
        id=ratio_set_orm.id,
        case_id=ratio_set_orm.case_id,
        fiscal_year=ratio_set_orm.fiscal_year,
        normalized_statement_id=ratio_set_orm.normalized_statement_id,
        current_ratio=ratio_set_orm.current_ratio,
        quick_ratio=ratio_set_orm.quick_ratio,
        cash_ratio=ratio_set_orm.cash_ratio,
        working_capital=ratio_set_orm.working_capital,
        debt_to_equity=ratio_set_orm.debt_to_equity,
        financial_autonomy=ratio_set_orm.financial_autonomy,
        gearing=ratio_set_orm.gearing,
        interest_coverage=ratio_set_orm.interest_coverage,
        net_margin=ratio_set_orm.net_margin,
        ebitda_margin=ratio_set_orm.ebitda_margin,
        operating_margin=ratio_set_orm.operating_margin,
        roa=ratio_set_orm.roa,
        roe=ratio_set_orm.roe,
        dso_days=ratio_set_orm.dso_days,
        dpo_days=ratio_set_orm.dpo_days,
        dio_days=ratio_set_orm.dio_days,
        cash_conversion_cycle=ratio_set_orm.cash_conversion_cycle,
        working_capital_requirement=ratio_set_orm.working_capital_requirement,
        working_capital_requirement_pct_revenue=ratio_set_orm.working_capital_requirement_pct_revenue,
        cash_flow_capacity=ratio_set_orm.cash_flow_capacity,
        cash_flow_capacity_margin_pct=ratio_set_orm.cash_flow_capacity_margin_pct,
        debt_repayment_years=ratio_set_orm.debt_repayment_years,
        negative_equity=ratio_set_orm.negative_equity,
        negative_operating_cash_flow=ratio_set_orm.negative_operating_cash_flow,
        z_score_altman=ratio_set_orm.z_score_altman,
        z_score_zone=ratio_set_orm.z_score_zone,
    )

    pillar_scores = convert_ratios_to_scores(ratios=ratio_schema, policy=policy)

    # 3. Hydrate ScorecardInputSchema with real 0-5 scores
    inputs = ScorecardInputSchema(
        liquidity_score=pillar_scores["liquidity_score"],
        solvency_score=pillar_scores["solvency_score"],
        profitability_score=pillar_scores["profitability_score"],
        capacity_score=pillar_scores["capacity_score"],
        quality_score=Decimal(str(gate_orm.reliability_score)) if gate_orm.reliability_score is not None else Decimal("0.0"),
        is_gate_blocking=gate_orm.is_gate_blocking,
        gate_blocking_reasons=gate_orm.blocking_reasons_json or [],
        has_negative_equity=bool(ratio_set_orm.negative_equity == 1),
        contract_value=contract_value_extracted,
    )

    # 4. Pure Engine
    try:
        scorecard_out = compute_pure_scorecard(inputs=inputs, policy=policy, overrides=[])
    except Exception as e:
        logger.error(f"Pure scoring computation crash for case {case_id}: {str(e)}")
        raise

    # 5. P0-03 + P0-10: Upsert with correct field assignments
    # P0-03: overrides_applied is already a list[dict] from the engine — no double .model_dump()
    overrides_json = scorecard_out.overrides_applied if scorecard_out.overrides_applied else []

    existing_result = await db.execute(select(Scorecard).where(Scorecard.case_id == case_id))
    existing_scorecard = existing_result.scalars().first()

    if existing_scorecard:
        # P0-10: Populate all pillar score fields
        existing_scorecard.score_liquidity = pillar_scores["liquidity_score"]
        existing_scorecard.score_solvency = pillar_scores["solvency_score"]
        existing_scorecard.score_profitability = pillar_scores["profitability_score"]
        existing_scorecard.score_capacity = pillar_scores["capacity_score"]
        existing_scorecard.score_quality = inputs.quality_score
        existing_scorecard.score_global = scorecard_out.system_calculated_score
        existing_scorecard.risk_class = scorecard_out.system_risk_class
        existing_scorecard.overrides_applied_json = overrides_json
        target_scorecard = existing_scorecard
    else:
        new_scorecard = Scorecard(
            case_id=case_id,
            # P0-10: Persist all individual pillar scores
            score_liquidity=pillar_scores["liquidity_score"],
            score_solvency=pillar_scores["solvency_score"],
            score_profitability=pillar_scores["profitability_score"],
            score_capacity=pillar_scores["capacity_score"],
            score_quality=inputs.quality_score,
            score_global=scorecard_out.system_calculated_score,
            risk_class=scorecard_out.system_risk_class,
            overrides_applied_json=overrides_json,  # P0-03: no double dump
        )
        db.add(new_scorecard)
        target_scorecard = new_scorecard

    await db.commit()
    await db.refresh(target_scorecard)
    
    # ─ Audit Trail (MCC-Grade Compliance) ─────────────────────
    await log_event(
        db=db,
        event_type="SCORECARD_GENERATED",
        entity_type="Scorecard",
        entity_id=str(target_scorecard.id),
        case_id=str(case_id),
        description=f"Scorecard generated automatically with global score {target_scorecard.score_global}"
    )

    return scorecard_out
