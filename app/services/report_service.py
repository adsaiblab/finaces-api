"""
app/services/report_service.py
FinaCES V1.2 — MCC-Grade Report Generator (Async Migration Sprint 2B)

CRITICAL RULE (cascaded awaits in build_full_report):
  All DB _helper functions are async and must be awaited.
  _build_section_XX functions (pure, synchronous) are called normally.
"""

import json
import uuid
import logging
import traceback
from datetime import datetime, timezone, date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.db.database import get_db
from app.db.models import (
    MCCGradeReport, EvaluationCase, Bidder, ContractCapacityAssessment, AuditLog,
)
from app.services.audit_service import log_event
from app.engines.gate_engine import evaluate_gate
from app.engines.normalization_engine import calculate_normalized_aggregates
from app.engines.ratio_engine import compute_ratios
from app.engines.scoring_engine import compute_pure_scorecard

from app.services.report_builders import (
    _build_section_01, _build_section_02, _build_section_03,
    _build_section_04, _build_section_05, _build_section_06,
    _build_section_07, _build_section_08, _build_section_09,
    _build_section_10, _build_section_11, _build_section_12,
    _build_section_13, _build_section_14, _build_section_consortium,
    _fmt_amount
)


logger = logging.getLogger(__name__)

# ── Constantes ─────────────────────────────────────────────────
SECTION_KEYS = [
    "section_01_info", "section_02_objective", "section_03_scope",
    "section_04_executive_summary", "section_05_profile", "section_06_analysis",
    "section_07_capacity", "section_08_red_flags", "section_09_mitigants",
    "section_10_scoring", "section_11_assessment", "section_12_recommendation",
    "section_13_limitations", "section_14_conclusion",
]

RECOMMENDATION_LABELS = {
    "ACCEPT":             "Acceptance recommended",
    "CONDITIONAL_ACCEPT": "Conditional acceptance",
    "REJECT_RECOMMENDED": "Rejection recommended",
}


# ════════════════════════════════════════════════════════════════
# HELPERS DB INTERNES (ASYNC)
# ════════════════════════════════════════════════════════════════

async def _get_case_data(case_id: str, db: AsyncSession) -> dict:
    """Load EvaluationCase + Bidder and return a flat dict."""
    result = await db.execute(
        select(EvaluationCase).where(EvaluationCase.id == uuid.UUID(case_id))
    )
    case = result.scalars().first()
    if not case:
        return {"id": case_id}

    bidder_name = ""
    legal_form = legal_form_val = sector = country = reg_number = ""

    if case.bidder_id:
        b_result = await db.execute(select(Bidder).where(Bidder.id == case.bidder_id))
        bidder = b_result.scalars().first()
        if bidder:
            bidder_name = bidder.name or ""
            legal_form = bidder.legal_form or "N/A"
            sector = bidder.sector or "N/A"
            country = bidder.country or "N/A"
            reg_number = bidder.registration_number or "N/A"

    def _val(v):
        return v.value if hasattr(v, "value") else v

    return {
        "id":                       str(case.id),
        "case_type":                _val(case.case_type),
        "bidder_id":                str(case.bidder_id) if case.bidder_id else None,
        "bidder_name":              bidder_name,
        "consortium_id":            str(case.consortium_id) if case.consortium_id else None,
        "market_reference":         case.market_reference,
        "market_object":            case.market_object,
        "contract_value":           case.contract_value,
        "contract_currency":        case.contract_currency,
        "contract_duration_months": case.contract_duration_months,
        "policy_version_id":        case.policy_version_id,
        "status":                   _val(case.status),
        "recommendation":           _val(case.recommendation),
        "legal_form":               legal_form,
        "sector":                   sector,
        "country":                  country,
        "registration_number":      reg_number,
    }


async def _get_latest_capacity(case_id: str, db: AsyncSession) -> Optional[dict]:
    """Loads the most recent ContractCapacityAssessment."""
    result = await db.execute(
        select(ContractCapacityAssessment)
        .where(ContractCapacityAssessment.case_id == uuid.UUID(case_id))
        .order_by(desc(ContractCapacityAssessment.created_at))
        .limit(1)
    )
    assess = result.scalars().first()
    if not assess:
        return None

    return {
        "contract_value":           assess.contract_value,
        "annual_ca_avg":            assess.annual_ca_avg,
        "exposition_pct":           assess.exposition_pct,
        "cash_available":           assess.cash_available,
        "bfr_estimate":             assess.working_capital_requirement_estimate, 
        "advance_payment_pct":      assess.advance_payment_pct,
        "stress_60d_result":        assess.stress_60d_result,
        "stress_90d_result":        assess.stress_90d_result,
        "stress_60d_cash_position": assess.stress_60d_cash_position,
        "stress_90d_cash_position": assess.stress_90d_cash_position,
        "score_capacite":           assess.score_capacity,                       
        "capacity_conclusion":      assess.capacity_conclusion,
        "coverage_ratio":           None,
        "coverage_status":          "N/A",
        "caf_avg":                  None,
        "annual_disbursement":      None,
        "monthly_flows":            [],
        "currency":                 "USD",
    }


async def _save_report(
    case_id:        str,
    policy:         dict,
    sections:       dict,
    complete_flags: dict,
    recommendation: Optional[str],
    db:             AsyncSession,
) -> str:
    """Persiste un MCCGradeReport en DRAFT et retourne l'ID."""
    count_result = await db.execute(
        select(func.count()).select_from(MCCGradeReport)
        .where(MCCGradeReport.case_id == uuid.UUID(case_id))
    )
    existing_count = count_result.scalar() or 0

    report_id = uuid.uuid4()
    now       = datetime.now(timezone.utc)

    db.add(MCCGradeReport(
        id=report_id,
        case_id=uuid.UUID(case_id),
        version_number=existing_count + 1,
        policy_version_id=policy.get("version_id"),
        status="DRAFT",
        recommendation=recommendation,
        section_01_info=         sections.get("section_01_info"),
        section_02_objective=        sections.get("section_02_objective"),
        section_03_scope=            sections.get("section_03_scope"),
        section_04_executive_summary=sections.get("section_04_executive_summary"),
        section_05_profile=          sections.get("section_05_profile"),
        section_06_analysis=         sections.get("section_06_analysis"),
        section_07_capacity=         sections.get("section_07_capacity"),
        section_08_red_flags=        sections.get("section_08_red_flags"),
        section_09_mitigants=        sections.get("section_09_mitigants"),
        section_10_scoring=          sections.get("section_10_scoring"),
        section_11_assessment=       sections.get("section_11_assessment"),
        section_12_recommendation=   sections.get("section_12_recommendation"),
        section_13_limitations=      sections.get("section_13_limitations"),
        section_14_conclusion=       sections.get("section_14_conclusion"),
        sections_complete_flags= complete_flags,
        created_at=now,
        updated_at=now,
    ))
    await db.commit()
    return str(report_id)


# ════════════════════════════════════════════════════════════════
# MAIN ASYNC FUNCTION
# build_full_report: cascaded awaits over each DB fetch
# ════════════════════════════════════════════════════════════════

async def build_full_report(case_id: str, policy: dict, db: AsyncSession) -> dict:
    """
    Builds the complete MCC-Grade report (14 sections).

    Await cascade (execution order):
      1. await _get_case_data()           — EvaluationCase + Bidder
      2. await _get_normalized_data()     — FinancialStatementNormalized list
      3. await _get_ratio_data()          — RatioSet list (multi-year)
      4. await _get_scorecard_data() — Most recent Scorecard
      5. await _get_gate_data()           — GateResult
      6. await _get_interpretation_data() — InterpretationResult
      7. await _get_latest_capacity() — ContractCapacityAssessment
      8. Pure _build_section_XX()         — Synchronous, no await
      9. await _save_report()             — MCCGradeReport INSERT
     10. await log_event()               — AuditLog REPORT_GENERATED
    """
    from app.db.models import (
        FinancialStatementNormalized, FinancialStatementRaw, RatioSet, Scorecard, GateResult, 
    )

    # 1. Case + Bidder
    case = await _get_case_data(case_id, db)

    # 2. Normalized statements (CORRECTED P0-06)
    raw_ids = await db.execute(
        select(FinancialStatementRaw.id)
        .where(FinancialStatementRaw.case_id == uuid.UUID(case_id))
    )
    raw_id_list = [r[0] for r in raw_ids.fetchall()]

    norm_result = await db.execute(
        select(FinancialStatementNormalized)
        .where(FinancialStatementNormalized.raw_statement_id.in_(raw_id_list))
        .order_by(FinancialStatementNormalized.fiscal_year.asc())
    )
    normalized_orms = norm_result.scalars().all()
    normalized_list = [
        {col.key: getattr(n, col.key) for col in n.__table__.columns}
        for n in normalized_orms
    ]

    # 3. Ratio sets
    rs_result = await db.execute(
        select(RatioSet)
        .where(RatioSet.case_id == uuid.UUID(case_id))
        .order_by(RatioSet.fiscal_year.asc())
    )
    ratio_orms = rs_result.scalars().all()
    ratio_sets = [
        {col.key: getattr(r, col.key) for col in r.__table__.columns}
        for r in ratio_orms
    ]

    # 4. Scorecard (most recent)
    sc_result = await db.execute(
        select(Scorecard)
        .where(Scorecard.case_id == uuid.UUID(case_id))
        .order_by(desc(Scorecard.computed_at))
        .limit(1)
    )
    sc_orm = sc_result.scalars().first()
    scorecard: dict = {}
    if sc_orm:
        scorecard = {col.key: getattr(sc_orm, col.key) for col in sc_orm.__table__.columns}
        # Normalize enum values
        for k, v in scorecard.items():
            if hasattr(v, "value"):
                scorecard[k] = v.value
        # Overrides list
        ov = scorecard.get("overrides_applied_json")
        if isinstance(ov, str):
            try:
                scorecard["overrides_applied"] = json.loads(ov)
            except Exception:
                scorecard["overrides_applied"] = []
        elif isinstance(ov, list):
            scorecard["overrides_applied"] = ov
        else:
            scorecard["overrides_applied"] = []
        scorecard.setdefault("smart_recommendations", [])
        scorecard.setdefault("trends_summary", {})
        scorecard.setdefault("final_risk_class", scorecard.get("risk_class"))

    # 5. Gate (most recent)
    gate_result = await db.execute(
        select(GateResult)
        .where(GateResult.case_id == uuid.UUID(case_id))
        .order_by(desc(GateResult.created_at))
        .limit(1)
    )
    gate_orm = gate_result.scalars().first()
    gate: dict = {}
    if gate_orm:
        gate = {col.key: getattr(gate_orm, col.key) for col in gate_orm.__table__.columns}
        for k, v in gate.items():
            if hasattr(v, "value"):
                gate[k] = v.value
        for list_key in ("blocking_flags", "reserve_flags", "fiscal_years_covered", "documents_summary"):
            val = gate.get(list_key)
            if isinstance(val, str):
                try:
                    gate[list_key] = json.loads(val)
                except Exception:
                    gate[list_key] = []
            elif val is None:
                gate[list_key] = []

    # 6. Interpretation (best effort — model may not exist yet)
    interpretation: dict = {}
    try:
        from app.db.models import InterpretationResult
        interp_result = await db.execute(
            select(InterpretationResult)
            .where(InterpretationResult.case_id == uuid.UUID(case_id))
            .order_by(desc(InterpretationResult.created_at))
            .limit(1)
        )
        interp_orm = interp_result.scalars().first()
        if interp_orm:
            interpretation = {col.key: getattr(interp_orm, col.key) for col in interp_orm.__table__.columns}
    except ModuleNotFoundError:
        logger.info(f"InterpretationResult model not yet migrated for case {case_id}.")
    except Exception as e:
        logger.error(f"Failed to load interpretation for case {case_id}: {e}")

    # 7. Capacity
    capacity = await _get_latest_capacity(case_id, db) or {}

    # 8. Consortium data (synchronous — no DB call)
    consortium_data = None
    if case.get("case_type") == "CONSORTIUM":
        consortium_data = {
            "consortium_id":       case.get("consortium_id"),
            "members":             [],
            "jv_type":             "N/A",
            "weighted_score":      0,
            "final_risk_class":    "N/A",
            "weak_link_triggered": False,
            "weak_link_member":    None,
            "leader_blocking":     False,
            "aggregated_stress":   "N/A",
            "mitigations_suggested": [],
            "aggregation_method":  "N/A",
        }

    latest_ratios = ratio_sets[-1] if ratio_sets else {}

    # ── Build sections 01–03, 05–14 (pure sync) ──────────────
    sections = {
        "section_01_info":           _build_section_01(case),
        "section_02_objective":       _build_section_02(case, policy),
        "section_03_scope":           _build_section_03(gate),
        "section_05_profile":         _build_section_05(case),
        "section_06_analysis":        _build_section_06(ratio_sets, interpretation, scorecard.get("trends_summary", {})),
        "section_07_capacity":        _build_section_07(capacity),
        "section_08_red_flags":       _build_section_08(scorecard, gate),
        "section_09_mitigants":       _build_section_09(scorecard),
        "section_10_scoring":         _build_section_10(scorecard),
        "section_11_assessment":      _build_section_11(scorecard),
        "section_12_recommendation":  _build_section_12(case.get("recommendation"), scorecard, capacity),
        "section_13_limitations":     _build_section_13(gate),
        "section_14_conclusion":      _build_section_14(case.get("recommendation"), scorecard),
    }

    if consortium_data:
        sections["section_06_analysis"] = (
            sections["section_06_analysis"] + "\n\n---\n\n" + _build_section_consortium(consortium_data)
        )

    # Section 04 last (executive summary synthesizes all other sections)
    sections["section_04_executive_summary"] = _build_section_04(case, scorecard, gate, capacity, sections, consortium_data)

    # 9. Completeness
    complete_flags = {k: bool(v and len(v.strip()) > 0) for k, v in sections.items()}

    # 10. Save
    report_id = await _save_report(case_id, policy, sections, complete_flags, case.get("recommendation"), db)

    # 11. Audit
    await log_event(
        db=db,
        event_type="REPORT_GENERATED",
        entity_type="MCCGradeReport",
        entity_id=report_id,
        case_id=case_id,
        description=(
            f"MCC-Grade report generated — "
            f"{sum(complete_flags.values())}/{len(SECTION_KEYS)} sections complete"
        ),
        new_value={
            "report_id":      report_id,
            "recommendation": case.get("recommendation"),
            "risk_class":     scorecard.get("final_risk_class"),
        },
    )

    return {
        "report_id":         report_id,
        "case_id":           case_id,
        "recommendation":    case.get("recommendation"),
        "complete_flags":    complete_flags,
        "sections_complete": sum(complete_flags.values()),
        "sections_total":    len(SECTION_KEYS),
        **sections,
    }


# ════════════════════════════════════════════════════════════════
# PUBLIC DB SERVICE FUNCTIONS (ASYNC)
# ════════════════════════════════════════════════════════════════

async def get_report(case_id: str, db: AsyncSession) -> Optional[dict]:
    """Returns the most recent report for a given case."""
    result = await db.execute(
        select(MCCGradeReport)
        .where(MCCGradeReport.case_id == uuid.UUID(case_id))
        .order_by(desc(MCCGradeReport.created_at))
        .limit(1)
    )
    report = result.scalars().first()
    if not report:
        return None

    last_word_log_r = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.case_id == uuid.UUID(case_id),
            AuditLog.event_type == "REPORT_EXPORTED",
            AuditLog.description.contains("Word"),
        )
        .order_by(desc(AuditLog.created_at)).limit(1)
    )
    last_word_log = last_word_log_r.scalars().first()

    last_pdf_log_r = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.case_id == uuid.UUID(case_id),
            AuditLog.event_type == "REPORT_EXPORTED",
            AuditLog.description.contains("PDF"),
        )
        .order_by(desc(AuditLog.created_at)).limit(1)
    )
    last_pdf_log = last_pdf_log_r.scalars().first()

    def _val(v):
        return v.value if hasattr(v, "value") else v

    return {
        "report_id":                str(report.id),
        "case_id":                  str(report.case_id),
        "version_number":           report.version_number,
        "status":                   _val(report.status),
        "recommendation":           _val(report.recommendation),
        "section_01_info":           report.section_01_info,
        "section_02_objective":       report.section_02_objective,
        "section_03_scope":           report.section_03_scope,
        "section_04_executive_summary": report.section_04_executive_summary,
        "section_05_profile":         report.section_05_profile,
        "section_06_analysis":        report.section_06_analysis,
        "section_07_capacity":        report.section_07_capacity,
        "section_08_red_flags":       report.section_08_red_flags,
        "section_09_mitigants":       report.section_09_mitigants,
        "section_10_scoring":         report.section_10_scoring,
        "section_11_assessment":      report.section_11_assessment,
        "section_12_recommendation":  report.section_12_recommendation,
        "section_13_limitations":     report.section_13_limitations,  
        "section_14_conclusion":      report.section_14_conclusion,
        "export_word_path":         report.export_word_path,
        "export_pdf_path":          report.export_pdf_path,
        "last_word_export_date":    last_word_log.created_at if last_word_log else None,
        "last_pdf_export_date":     last_pdf_log.created_at if last_pdf_log else None,
        "sections_complete_flags":  report.sections_complete_flags or {},
        "created_at":               report.created_at,
        "updated_at":               report.updated_at,
    }


async def update_report_section(
    report_id:   str,
    section_key: str,
    content:     str,
    db:          AsyncSession,
) -> bool:
    """Updates a single report section (manual corrections)."""
    if section_key not in SECTION_KEYS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown section: {section_key}")

    result = await db.execute(
        select(MCCGradeReport).where(MCCGradeReport.id == uuid.UUID(report_id))
    )
    report = result.scalars().first()
    if not report:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")

    setattr(report, section_key, content)
    report.updated_at = datetime.now(timezone.utc)

    flags = report.sections_complete_flags or {}
    if isinstance(flags, str):
        try:
            flags = json.loads(flags)
        except Exception:
            flags = {}
    flags[section_key] = bool(content and len(content.strip()) > 0)
    report.sections_complete_flags = flags

    await db.commit()
    return True


async def finalize_report(report_id: str, db: AsyncSession) -> bool:
    """Sets the report status to FINAL."""
    result = await db.execute(
        select(MCCGradeReport).where(MCCGradeReport.id == uuid.UUID(report_id))
    )
    report = result.scalars().first()
    if not report:
        return False
    report.status     = "FINAL"
    report.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return True


# ════════════════════════════════════════════════════════════════
# SECTION BUILDERS (SYNCHRONOUS)
# ════════════════════════════════════════════════════════════════
