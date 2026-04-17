import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update
from app.db.models import RatioSet, DocumentEvidence, DueDiligenceCheck, GateResult, EvaluationCase
from app.schemas.enums import CaseStatus
from app.schemas.gate_schema import DocumentEvidenceSchema, DueDiligenceCheckSchema, GateDecisionSchema
from app.engines.gate_engine import evaluate_gate
from app.exceptions.finaces_exceptions import MissingFinancialDataError
from app.schemas.policy_schema import PolicyConfigurationSchema
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

async def _get_active_policy(db: AsyncSession) -> PolicyConfigurationSchema:
    """Mock Service for Policy Engine"""
    return PolicyConfigurationSchema(version_id="mock_active_policy_v2")

async def process_gate_evaluation(case_id: UUID, db: AsyncSession) -> GateDecisionSchema:
    """
    Asynchronous Orchestrator (Knock-out Gate):
    1. Get the most recent RatioSet (and therefore `has_negative_equity`).
    2. Recovers Documents and DDChecks.
    3. Maps to validated Pydantic native schemas.
    4. Execute the Gate (Pure function).
    5. Enregistre le `GateResult` en DB et commit.
    """
    logger.info(f"Starting async Gate Evaluation for case {case_id}")

    # has_negative_equity comes from DD checks or red flags — not from RatioSet
    has_negative_equity = False

    # 2. Document Recovery and Due Diligence Check Lists
    stmt_docs = select(DocumentEvidence).where(DocumentEvidence.case_id == case_id)
    res_docs = await db.execute(stmt_docs)
    docs_orm = res_docs.scalars().all()
    docs_schemas = [DocumentEvidenceSchema.model_validate(d) for d in docs_orm]

    stmt_dds = select(DueDiligenceCheck).where(DueDiligenceCheck.case_id == case_id)
    res_dds = await db.execute(stmt_dds)
    dds_orm = res_dds.scalars().all()
    dds_schemas = [DueDiligenceCheckSchema.model_validate(dd) for dd in dds_orm]

    # 3. Policy Execution
    policy = await _get_active_policy(db)
    
    # Injection in the pure engine
    try:
        gate_decision = evaluate_gate(
            docs=docs_schemas,
            dd_checks=dds_schemas,
            policy=policy,
            has_negative_equity=has_negative_equity
        )
    except Exception as e:
        logger.error(f"Computation pure gate math crash on case {case_id}: {str(e)}")
        raise

    # 4. Upserting the Result (New table)
    stmt_gate = select(GateResult).where(GateResult.case_id == case_id)
    res_gate = await db.execute(stmt_gate)
    existing_gate = res_gate.scalars().first()

    blocking_flag = not gate_decision.is_passed

    if existing_gate:
        existing_gate.is_gate_blocking = blocking_flag
        existing_gate.blocking_reasons_json = gate_decision.blocking_reasons
        existing_gate.is_passed = gate_decision.is_passed
        existing_gate.verdict = gate_decision.verdict
        existing_gate.reliability_level = gate_decision.reliability_level
        existing_gate.reliability_score = gate_decision.reliability_score
        existing_gate.missing_mandatory_json = gate_decision.missing_mandatory
        existing_gate.missing_optional_json = gate_decision.missing_optional
        existing_gate.reserve_flags_json = gate_decision.reserve_flags
        target_gate = existing_gate
    else:
        new_gate = GateResult(
            case_id=case_id,
            is_gate_blocking=blocking_flag,
            blocking_reasons_json=gate_decision.blocking_reasons,
            is_passed=gate_decision.is_passed,
            verdict=gate_decision.verdict,
            reliability_level=gate_decision.reliability_level,
            reliability_score=gate_decision.reliability_score,
            missing_mandatory_json=gate_decision.missing_mandatory,
            missing_optional_json=gate_decision.missing_optional,
            reserve_flags_json=gate_decision.reserve_flags
        )
        db.add(new_gate)
        target_gate = new_gate

    # Finalize status transition (MCC-Gate Pipeline stability)
    await db.execute(
        update(EvaluationCase)
        .where(EvaluationCase.id == case_id)
        .values(status=CaseStatus.PENDING_GATE)
    )

    await db.commit()
    await db.refresh(target_gate)

    # ─ Audit Trail (MCC-Grade Compliance) ─────────────────────
    await log_event(
        db=db,
        event_type="GATE_EVALUATED",
        entity_type="GateResult",
        entity_id=str(target_gate.id),
        case_id=str(case_id),
        description=f"Gate evaluated with verdict: {gate_decision.verdict}"
    )

    return gate_decision
