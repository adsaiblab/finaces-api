import uuid
from decimal import Decimal
from typing import List, Dict, Optional
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

from app.schemas.gate_schema import (
    DocumentEvidenceSchema,
    DueDiligenceCheckSchema,
    GateDecisionSchema,
)
from app.schemas.policy_schema import PolicyConfigurationSchema


from decimal import Decimal, ROUND_HALF_UP

# ── Pure Helpers ──────────────────────────────────────────────
def _compute_reliability_score(docs: List[DocumentEvidenceSchema], policy: PolicyConfigurationSchema) -> Decimal:
    """Weighted average of the reliability level of present documents."""
    present = [d for d in docs if d.status == "PRESENT"]
    if not present:
        return Decimal("0.0")
    total = sum(Decimal(str(policy.gate.reliability_weights.get(d.reliability_level, 0.5))) for d in present)
    return (total / Decimal(str(len(present)))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

def _score_to_reliability_level(score: Decimal, policy: PolicyConfigurationSchema) -> str:
    # ── Dynamic extraction of thresholds (secure fallback)
    p = getattr(policy, "gate", None)
    high_th = Decimal(str(getattr(p, 'reliability_high_threshold', "0.90")))
    med_th  = Decimal(str(getattr(p, 'reliability_medium_threshold', "0.65")))
    low_th  = Decimal(str(getattr(p, 'reliability_low_threshold', "0.30")))

    if score >= high_th:
        return "HIGH"
    elif score >= med_th:
        return "MEDIUM"
    elif score >= low_th:
        return "LOW"
    else:
        return "UNAUDITED"

# ── Gate Engine (Pure Function) ──────────────────────────────
def evaluate_gate(
    docs: List[DocumentEvidenceSchema], 
    dd_checks: List[DueDiligenceCheckSchema], 
    policy: PolicyConfigurationSchema,
    statement_end_date: datetime.date = None,
    min_years: int = 3,
    has_negative_equity: bool = False
) -> GateDecisionSchema:
    """
    Pure function validating documentary compliance and due diligences, according to policy parameters.
    """
    blocking_flags = []
    reserve_flags = []

    # 1. Mandatory documents verification via policy
    present_types = {d.doc_type for d in docs if d.status == "PRESENT"}
    missing_mandatory = [t for t in policy.gate.required_doc_types if t not in present_types]
    missing_optional = [t for t in policy.gate.optional_doc_types if t not in present_types]

    for mt in missing_mandatory:
        blocking_flags.append(f"Missing mandatory document: {mt}")

    # 2. Covered fiscal years
    fiscal_years = sorted(set(d.fiscal_year for d in docs if d.fiscal_year and d.status == "PRESENT"))
    min_years_ok = len(fiscal_years) >= min_years

    if not min_years_ok:
        blocking_flags.append(f"Insufficient time coverage: {len(fiscal_years)} year(s) provided, {min_years} required.")

    if statement_end_date:
        today = datetime.now(timezone.utc).date()
        diff = relativedelta(today, statement_end_date)
        months_old = diff.years * 12 + diff.months
        
        if months_old > policy.stale_data_months_limit:
            reserve_flags.append(f"STALE_DATA_WARNING: Stale data by {months_old} months (limit: {policy.stale_data_months_limit} months)")

    # 3. Dynamically computed reliability score
    reliability_score = _compute_reliability_score(docs, policy)
    reliability_level = _score_to_reliability_level(reliability_score, policy) 

    # 4. Document and Auditor red flags
    if has_negative_equity:
        blocking_flags.append("Negative equity detected (NEGATIVE_EQUITY)")

    for doc in docs:
        for flag in doc.red_flags or []:
            severity = flag.get("severity", "RESERVE")
            label = flag.get("label", str(flag))
            if severity == "BLOCKING":
                blocking_flags.append(label)
            else:
                reserve_flags.append(label)

        if doc.doc_type == "AUDITOR_OPINION" and doc.auditor_opinion:
            op = doc.auditor_opinion
            if op in ["ADVERSE", "DISCLAIMER"]:
                blocking_flags.append(f"Blocking Auditor Opinion: {op}")
            elif op == "QUALIFIED":
                reserve_flags.append(f"Qualified Auditor Opinion: {op}")
            elif op == "NOT_AUDITED":
                blocking_flags.append("Auditor Opinion: unaudited document — automatic red flag")
            elif op not in ["UNQUALIFIED"]:
                reserve_flags.append(f"Unrecognized Auditor Opinion: {op}")

    # 5. Due Diligence Checks
    for check in dd_checks:
        level_name = policy.gate.dd_levels.get(check.dd_level, f"Level {check.dd_level}")
        if check.verdict == "BLOCKING":
            blocking_flags.append(f"Due diligence {level_name} : BLOCKING")
        elif check.verdict == "RESERVE":
            reserve_flags.append(f"Due diligence {level_name} : RESERVE")

    # 6. Final verdict
    is_passed = True
    verdict = "PASS"

    if has_negative_equity:
        verdict = "REJECTED"
        is_passed = False
    elif blocking_flags:
        verdict = "BLOCKING"
        is_passed = False
    elif reserve_flags:
        verdict = "PASS_WITH_RESERVES"

    return GateDecisionSchema(
        is_passed=is_passed,
        verdict=verdict,
        reliability_level=reliability_level,
        reliability_score=reliability_score,
        missing_mandatory=missing_mandatory,
        missing_optional=missing_optional,
        blocking_reasons=blocking_flags,
        reserve_flags=reserve_flags,
        computed_at=datetime.now(timezone.utc)
    )
