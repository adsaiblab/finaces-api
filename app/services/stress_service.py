import logging
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import EvaluationCase, FinancialStatementNormalized, FinancialStatementRaw, StressScenario, DocumentEvidence, DueDiligenceCheck
from app.schemas.stress_schema import StressScenarioInputSchema, StressResultSchema, StressDecision
from app.schemas.scoring_schema import ScorecardInputSchema
from app.schemas.normalization_schema import FinancialStatementNormalizedSchema
from app.schemas.gate_schema import DocumentEvidenceSchema, DueDiligenceCheckSchema
from app.schemas.policy_schema import PolicyConfigurationSchema

from app.engines.stress_engine import compute_stress_capacity
from app.engines.gate_engine import evaluate_gate
from app.engines.scoring_engine import compute_pure_scorecard
from app.exceptions.finaces_exceptions import MissingFinancialDataError, EngineComputationError
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

# Standard stress scenarios included in the risk policy
DEFAULT_SCENARIOS = [
    {"name": "S1_BASE", "delay_days": 0, "cost_overrun": 0.0, "ca_shock": 0.0},
    {"name": "S2_RETARD_60", "delay_days": 60, "cost_overrun": 0.05, "ca_shock": 0.0},
    {"name": "S3_RETARD_90", "delay_days": 90, "cost_overrun": 0.10, "ca_shock": -0.10},
]

async def _get_active_policy(db: AsyncSession) -> PolicyConfigurationSchema:
    return PolicyConfigurationSchema(version_id="mock_active_policy_v2")

async def process_stress_simulation(case_id: UUID, payload: StressScenarioInputSchema, db: AsyncSession) -> StressResultSchema:
    """
    Asynchronous Orchestrator (Stress Test):
    1. Retrieves the basic Case, FinancialStatementNormalized, documents and DD checks.
    2. Starts the pure `compute_stress_capacity` engine.
    3. Re-evaluates the Gate with the impacted data (simulated negative_equity).
    4. Recalculates the score under stressed conditions via `compute_pure_scorecard`.
    5. Persist the scenario in `stress_scenarios`.
    """
    logger.info(f"Starting Stress Simulation on case {case_id}")

    # 1. Case Check
    res_case = await db.execute(select(EvaluationCase).where(EvaluationCase.id == case_id))
    case_orm = res_case.scalars().first()
    if not case_orm:
        raise ValueError(f"Case {case_id} not found.")

    # 2. Retrieving the most recent FinancialStatementNormalized
    res_fs = await db.execute(
        select(FinancialStatementNormalized)
        .join(FinancialStatementNormalized.raw_statement)
        .where(FinancialStatementRaw.case_id == case_id)
        .order_by(FinancialStatementNormalized.created_at.desc())
        .limit(1)
    )
    orig_fs_orm = res_fs.scalars().first()
    if not orig_fs_orm:
        raise MissingFinancialDataError("No normalized financial statements found for stress computation.")

    # 3. Documents et DD Checks
    res_docs = await db.execute(select(DocumentEvidence).where(DocumentEvidence.case_id == case_id))
    docs_orm = res_docs.scalars().all()

    res_dd = await db.execute(select(DueDiligenceCheck).where(DueDiligenceCheck.case_id == case_id))
    dd_orm = res_dd.scalars().all()

    policy = await _get_active_policy(db)

    # 4. Pure Stress Engine
    try:
        stress_output: StressResultSchema = compute_stress_capacity(
            inputs=payload,
            scenarios=DEFAULT_SCENARIOS,
            policy=policy
        )
    except Exception as e:
        logger.error(f"Stress pure engine crash on case {case_id}: {e}")
        raise EngineComputationError("Internal error during pure execution of stress simulation.")

    # 5. Virtual Gate - Checking if the box holds under stress
    # On simule negative_equity si stress 60j = INSOLVENT
    simulated_negative_equity = (stress_output.stress_60d_result == StressDecision.INSOLVENT)

    docs_schemas = [
        DocumentEvidenceSchema(
            doc_type=d.doc_type,
            fiscal_year=d.fiscal_year or 0,
            status=d.status,
            reliability_level=d.reliability_level or "MEDIUM",
            auditor_opinion=d.auditor_opinion,
            notes=d.notes,
            red_flags=d.red_flags_json or []
        ) for d in docs_orm
    ]
    dd_schemas = [
        DueDiligenceCheckSchema(
            dd_level=d.dd_level,
            verdict=d.verdict,
            notes=d.notes or "",
            description=d.description
        ) for d in dd_orm
    ]

    virtual_gate = evaluate_gate(
        docs=docs_schemas,
        dd_checks=dd_schemas,
        policy=policy,
        has_negative_equity=simulated_negative_equity
    )

    # 6. Simulated Score — calculation under stressed conditions
    # We use the capacity score calculated by the Stress Engine as a proxy
    # The other pillars are degraded proportionally to the stress shock
    stress_multiplier = Decimal("0.8") if stress_output.stress_60d_result == StressDecision.LIMIT else (
        Decimal("0.5") if stress_output.stress_60d_result == StressDecision.INSOLVENT else Decimal("1.0")
    )

    simulated_score_input = ScorecardInputSchema(
        liquidity_score=(Decimal("3.0") * stress_multiplier).quantize(Decimal("0.01")),
        solvency_score=(Decimal("3.0") * stress_multiplier).quantize(Decimal("0.01")),
        profitability_score=(Decimal("3.0") * stress_multiplier).quantize(Decimal("0.01")),
        capacity_score=stress_output.score_capacity,
        quality_score=virtual_gate.reliability_score,
        is_gate_blocking=virtual_gate.is_gate_blocking if hasattr(virtual_gate, "is_gate_blocking") else (not virtual_gate.is_passed),
        gate_blocking_reasons=virtual_gate.blocking_reasons,
        has_negative_equity=simulated_negative_equity,
        contract_value=payload.contract_value
    )

    try:
        simulated_scorecard = compute_pure_scorecard(simulated_score_input, policy)
    except EngineComputationError as e:
        logger.warning(f"Simulated scorecard computation blocked by gate on case {case_id}: {e}")
        simulated_scorecard = None

    # 7. Persistence
    new_scenario = StressScenario(
        case_id=case_id,
        scenario_name=f"Stress Test [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}]",
        description="Simulation asynchrone via Stress Engine (compute_stress_capacity)",
        input_parameters_json=payload.model_dump(mode="json"),
        simulated_score_global=simulated_scorecard.global_score if simulated_scorecard else None,
        simulated_risk_class=simulated_scorecard.final_risk_class.name if simulated_scorecard else "BLOCKED_GATE",
        stress_results_json=stress_output.model_dump(mode="json")
    )
    db.add(new_scenario)
    await db.commit()
    await db.refresh(new_scenario)
    
    # ─ Audit Trail (MCC-Grade Compliance) ─────────────────────
    await log_event(
        db=db,
        event_type="STRESS_TEST_COMPUTED",
        entity_type="CaseAnalysis",
        entity_id=case_id,
        case_id=str(case_id),
        description="Asynchronous simulation via Stress Engine (compute_stress_capacity)",
    )

    return stress_output
