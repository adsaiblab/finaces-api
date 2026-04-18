from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timezone
from uuid import UUID

from app.schemas.scoring_schema import ScorecardInputSchema, ScorecardOutputSchema, RiskClass, PillarDetailSchema
from app.schemas.policy_schema import PolicyConfigurationSchema
from app.exceptions.finaces_exceptions import EngineComputationError
from app.engines._risk_utils import get_risk_band

def _get_dynamic_weights(contract_value: Decimal, policy: PolicyConfigurationSchema) -> Dict[str, Decimal]:
    """Pure Function: Determines weights via the dynamic Policy"""
        
    market_size = "SMALL"
    if contract_value > policy.scoring.market_size_limits.large_threshold:
        market_size = "LARGE"
    elif contract_value >= policy.scoring.market_size_limits.medium_threshold:
        market_size = "MEDIUM"

    dyn_weights = policy.scoring.dynamic_weights.get(market_size)
    if not dyn_weights:
        dyn_weights = policy.scoring.default_weights
        
    return {
        "liquidity": dyn_weights.liquidity,
        "solvency": dyn_weights.solvency,
        "profitability": dyn_weights.profitability,
        "capacity": dyn_weights.capacity,
        "quality": dyn_weights.quality,
    }



def _classify_risk_profile(scores: List[Decimal], policy: PolicyConfigurationSchema) -> Tuple[str, str]:
    if not scores: 
        return "UNDEFINED", "Risk profile not calculable."
    ma, mi = max(scores), min(scores)
    
    # ── Dynamic extraction of thresholds (secure fallback)
    p = getattr(policy, "scoring", None)
    prof = getattr(p, "profiles", None)

    bal_min      = Decimal(str(getattr(prof, 'balanced_min_score', "3.0")))
    bal_gap      = Decimal(str(getattr(prof, 'balanced_max_gap', "1.5")))
    asym_gap     = Decimal(str(getattr(prof, 'asymmetrical_min_gap', "2.5")))
    agg_min      = Decimal(str(getattr(prof, 'aggressive_min_score', "2.0")))
    agg_prof_min = Decimal(str(getattr(prof, 'aggressive_profitability_min', "4.0")))
    def_min      = Decimal(str(getattr(prof, 'defensive_min_score', "2.5")))
    def_liq_min  = Decimal(str(getattr(prof, 'defensive_liquidity_min', "3.5")))
    def_sol_min  = Decimal(str(getattr(prof, 'defensive_solvency_min', "3.5")))
    
    if mi >= bal_min and (ma - mi) <= bal_gap:
        return "BALANCED", "Homogeneous and robust scores across all financial pillars."
    if (ma - mi) >= asym_gap:
        return "ASYMMETRICAL", "Strong performance disparity between pillars (marked strengths and weaknesses)."
    if mi >= agg_min and len(scores) > 2 and scores[2] >= agg_prof_min:
        return "AGGRESSIVE", "Profile oriented towards high profitability accepting a margin of risk."
    if mi >= def_min and len(scores) > 1 and scores[0] >= def_liq_min and scores[1] >= def_sol_min:
        return "DEFENSIVE", "Excellent coverage of cash and balance sheet risks (protective profile)."
    
    return "CLASSIC", "Profile with isolated vulnerabilities requiring monitoring."

def compute_pure_scorecard(
    inputs: ScorecardInputSchema, 
    policy: PolicyConfigurationSchema,
    has_missing_pillars: bool = False,
    overrides: List[Dict[str, str]] = None
) -> ScorecardOutputSchema:
    """
    Pure Mathematical Engine: 
    ZERO database interference. Parses rules from the injected Policy.
    Guarantees strict cast to Decimal.
    """
    if inputs.is_gate_blocking:
        reasons = ", ".join(inputs.gate_blocking_reasons)
        raise EngineComputationError(f"Calculation impossible: Case is blocked at Gate stage (NO_GO). Reasons: {reasons}")
        
    weights = _get_dynamic_weights(inputs.contract_value, policy)
    
    w_sum = sum(weights.values())
    if abs(w_sum - Decimal("1.0")) > Decimal("0.001"):
        raise EngineComputationError(f"Calculation impossible: Scoring weights sum is {w_sum}, must be exactly 1.0")

    # Rigorous mathematical rounding (System Score)
    raw_score = (
        inputs.liquidity_score * weights["liquidity"]
        + inputs.solvency_score * weights["solvency"]
        + inputs.profitability_score * weights["profitability"]
        + inputs.capacity_score * weights["capacity"]
        + inputs.quality_score * weights["quality"]
    )
    
    system_calculated_score = min(Decimal("5.000"), max(Decimal("0.000"), raw_score)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    system_risk_class = get_risk_band(system_calculated_score, policy)
    
    global_score = system_calculated_score
    base_risk_class = system_risk_class
    overrides_applied = overrides or []
    
    # ── NOT_EVALUATED Rule: Cap on missing data ────────────
    if has_missing_pillars:
        cap_class = RiskClass(policy.max_score_if_missing_pillar)
        # Extraction dynamique du plafond (Fallback 3.999)
        missing_cap = Decimal(str(getattr(getattr(policy, "scoring", None), "missing_pillar_score_cap", "3.999")))
        
        if base_risk_class == RiskClass.LOW and cap_class != RiskClass.LOW:
            global_score = min(global_score, missing_cap).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
            base_risk_class = cap_class
            overrides_applied.append({
                "type": "AUTO_FLAG",
                "code": "MISSING_PILLAR",
                "description": f"Missing pillar detected. Mathematical score capped at class {cap_class.value}"
            })

    # ── Negative equity (Kill Switch) ────────────
    if inputs.has_negative_equity:
        # Extraction dynamique du plafond critique (Fallback 2.000)
        neg_eq_cap = Decimal(str(getattr(getattr(policy, "scoring", None), "negative_equity_score_cap", "2.000")))
        
        global_score = min(neg_eq_cap, global_score).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        base_risk_class = RiskClass.CRITICAL
        overrides_applied.append({
            "type": "AUTO_FLAG",
            "code": "NEGATIVE_EQUITY",
            "description": f"Negative equity. Score capped at {neg_eq_cap} and forced to CRITICAL class."
        })
        
    risk_prof, risk_desc = _classify_risk_profile([
        inputs.liquidity_score, inputs.solvency_score, 
        inputs.profitability_score, inputs.capacity_score
    ], policy)  # <-- FIXED: Policy injection
    
    # Determine Overrides Traceability Logic
    is_overridden = False
    final_risk_class = base_risk_class
    override_rationale = None
    
    for ov in overrides_applied:
        if ov.get("type") == "MANUAL_RISK_OVERRIDE":
            is_overridden = True
            try:
                final_risk_class = RiskClass(ov.get("new_val"))
            except ValueError:
                pass
            override_rationale = ov.get("rationale")
    
    # Pillar Details
    def get_pillar_status(score: Decimal) -> str:
        if score >= 4: return "EXCELLENT"
        if score >= 3: return "GOOD"
        if score >= 2: return "FAIR"
        if score >= 1: return "POOR"
        return "CRITICAL"

    pillars = [
        PillarDetailSchema(
            id="liq", 
            name="Liquidity & Cash", 
            score=inputs.liquidity_score, 
            weight=weights["liquidity"]*100, 
            status=get_pillar_status(inputs.liquidity_score),
            key_drivers=["Current Ratio", "Quick Ratio"],
            trend=[inputs.liquidity_score], 
            signals=[], 
            detailText=""
        ),
        PillarDetailSchema(
            id="solv", 
            name="Solvency & Debt", 
            score=inputs.solvency_score, 
            weight=weights["solvency"]*100, 
            status=get_pillar_status(inputs.solvency_score),
            key_drivers=["Debt to Equity", "Gearing"],
            trend=[inputs.solvency_score], 
            signals=[], 
            detailText=""
        ),
        PillarDetailSchema(
            id="rent", 
            name="Profitability", 
            score=inputs.profitability_score, 
            weight=weights["profitability"]*100, 
            status=get_pillar_status(inputs.profitability_score),
            key_drivers=["ROE", "Operating Margin"],
            trend=[inputs.profitability_score], 
            signals=[], 
            detailText=""
        ),
        PillarDetailSchema(
            id="cap", 
            name="Repayment Capacity", 
            score=inputs.capacity_score, 
            weight=weights["capacity"]*100, 
            status=get_pillar_status(inputs.capacity_score),
            key_drivers=["DSCR", "Cash Flow"],
            trend=[inputs.capacity_score], 
            signals=[], 
            detailText=""
        ),
        PillarDetailSchema(
            id="qual", 
            name="Document Quality", 
            score=inputs.quality_score, 
            weight=weights["quality"]*100, 
            status=get_pillar_status(inputs.quality_score),
            key_drivers=["Auditor Opinion", "Statement Integrity"],
            trend=[inputs.quality_score], 
            signals=[], 
            detailText=""
        ),
    ]
    
    recos = []
    if final_risk_class == RiskClass.LOW:
        recos.append("Faible risque global : Aucune condition financière spécifique n'est requise.")
    elif final_risk_class == RiskClass.MODERATE:
        recos.append("Risque modéré : Une surveillance trimestrielle du BFR est conseillée.")
    elif final_risk_class in [RiskClass.HIGH, RiskClass.CRITICAL]:
        recos.append(f"Risque {final_risk_class.value} : L'attribution est mathématiquement déconseillée sans garanties additionnelles.")

    now = datetime.now(timezone.utc)
    return ScorecardOutputSchema(
        case_id=None,
        system_calculated_score=system_calculated_score,
        system_risk_class=system_risk_class,
        global_score=global_score,
        base_risk_class=base_risk_class,
        is_overridden=is_overridden,
        final_risk_class=final_risk_class,
        override_rationale=override_rationale,
        risk_profile=risk_prof,
        risk_description=risk_desc,
        synergy_index=None,
        synergy_bonus=None,
        pillars=pillars,
        smart_recommendations=recos,
        overrides_applied=overrides_applied,
        computed_at=now,
        calculation_date=now.strftime("%d/%m/%Y")
    )
