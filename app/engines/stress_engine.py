from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Optional
import json

from app.schemas.stress_schema import (
    StressScenarioInputSchema, 
    StressResultSchema, 
    StressDecision, 
    ScenarioFlowSchema, 
    ScenarioSimulationResultSchema
)
from app.schemas.policy_schema import PolicyConfigurationSchema

def _safe_divide(num: Optional[Decimal], den: Optional[Decimal]) -> Optional[Decimal]:
    """Safe division preventing ZeroDivisionError and handling None values."""
    if num is None or den is None or den == Decimal("0.0"):
        return None
    return num / den

def _simulate_milestone_payments(contract_value: Decimal, milestones: list, eval_day: int, delay_days: int = 0) -> Decimal:
    """Calculates external payments actually received before evaluation. Pure Function."""
    if not milestones:
        return Decimal("0.0")

    total_received = Decimal("0.0")
    for m in milestones:
        payment_day = m.day + delay_days
        if payment_day <= eval_day:
            pct_val = _safe_divide(m.pct, Decimal("100.0")) or Decimal("0.0")
            total_received += contract_value * pct_val

    return total_received

def _estimate_costs_at_day(contract_value: Decimal, contract_months: int, day: int, policy: PolicyConfigurationSchema) -> Decimal:
    """Estimates incurred costs via the 3rd degree Polynomial S-Curve."""
    total_days = contract_months * 30
    if total_days == 0:
        return Decimal("0.0")
        
    calc_ratio = _safe_divide(Decimal(str(day)), Decimal(str(total_days))) or Decimal("0.0")
    x = min(max(calc_ratio, Decimal("0.0")), Decimal("1.0"))
    
    # 3x^2 - 2x^3 (S-curve)
    s_factor = (x ** Decimal("2")) * (Decimal("3.0") - Decimal("2.0") * x)
    
    cost_ratio = policy.stress.cost_curve_ratio
    return contract_value * cost_ratio * s_factor

def _classify_stress(cash_position: Decimal, working_capital_requirement_estimate: Decimal = Decimal("0.0")) -> StressDecision:
    if cash_position > Decimal("0"):
        return StressDecision.SOLVENT
    elif cash_position > -abs(working_capital_requirement_estimate * Decimal("0.05")):
        return StressDecision.LIMIT
    else:
        return StressDecision.INSOLVENT

def _compute_capacity_score(
    exposition_pct: Decimal,
    current_ratio:  Decimal,
    stress_60d:     StressDecision,
    stress_90d:     StressDecision,
    advance_pct:    Decimal,
    annual_ca_avg:  Decimal,
    backlog_value:  Decimal,
    bank_guarantee: bool,
    bank_guarantee_amount: Decimal,
    policy:         PolicyConfigurationSchema, 
) -> Decimal:
    """Capacity score 0-5 Pure Math (Dynamic Policy Driven)"""
    
    # ── Dynamic extraction of thresholds (secure fallback)
    p = policy.stress
    w_exp = Decimal(str(getattr(p, 'weight_exposure', "0.25")))
    w_s60 = Decimal(str(getattr(p, 'weight_stress_60d', "0.30")))
    w_s90 = Decimal(str(getattr(p, 'weight_stress_90d', "0.15")))
    w_wcr = Decimal(str(getattr(p, 'weight_wcr', "0.20")))
    w_bon = Decimal(str(getattr(p, 'weight_bonus', "0.10")))

    exp_low = Decimal(str(getattr(p, 'exposure_low', "30.0")))
    exp_med = Decimal(str(getattr(p, 'exposure_medium', "50.0")))
    exp_hi  = Decimal(str(getattr(p, 'exposure_high', "70.0")))

    wcr_hi  = Decimal(str(getattr(p, 'wcr_coverage_high', "2.0")))
    wcr_med = Decimal(str(getattr(p, 'wcr_coverage_medium', "1.2")))
    wcr_low = Decimal(str(getattr(p, 'wcr_coverage_low', "0.8")))

    adv_thr  = Decimal(str(getattr(p, 'advance_bonus_threshold', "0.10")))
    bkl_crit = Decimal(str(getattr(p, 'backlog_ratio_critical', "1.5")))
    bkl_hi   = Decimal(str(getattr(p, 'backlog_ratio_high', "1.0")))

    ceil_60  = Decimal(str(getattr(p, 'ceiling_insolvent_60d', "1.5")))
    ceil_90  = Decimal(str(getattr(p, 'ceiling_insolvent_90d', "2.0")))

    # ── 1. Exposure
    score_exp = Decimal("0.0")
    if exposition_pct < exp_low: score_exp = Decimal("5.0")
    elif exposition_pct <= exp_med: score_exp = Decimal("3.0")
    elif exposition_pct <= exp_hi: score_exp = Decimal("1.0")

    # ── 2. 60d Stress
    score_s60 = Decimal("0.0")
    if stress_60d == StressDecision.SOLVENT: score_s60 = Decimal("5.0")
    elif stress_60d == StressDecision.LIMIT: score_s60 = Decimal("2.5")

    # ── 3. 90d Stress
    score_s90 = Decimal("0.0")
    if stress_90d == StressDecision.SOLVENT: score_s90 = Decimal("5.0")
    elif stress_90d == StressDecision.LIMIT: score_s90 = Decimal("2.5")

    # ── 4. WCR Coverage
    score_bfr = Decimal("0.0")
    if current_ratio >= wcr_hi: score_bfr = Decimal("5.0")
    elif current_ratio >= wcr_med: score_bfr = Decimal("3.0")
    elif current_ratio >= wcr_low: score_bfr = Decimal("1.0")

    # ── 5. Advance/Guarantees Bonus
    score_bonus = Decimal("0.0")
    if advance_pct >= adv_thr: score_bonus += Decimal("2.5")
    if bank_guarantee and bank_guarantee_amount > Decimal("0"): score_bonus += Decimal("2.5")
    
    backlog_ratio = _safe_divide(backlog_value, annual_ca_avg) or Decimal("0.0")
    if backlog_ratio > bkl_crit: score_bonus -= Decimal("2.0")
    elif backlog_ratio > bkl_hi: score_bonus -= Decimal("1.0")
    
    score_bonus = min(Decimal("5.0"), max(Decimal("0.0"), score_bonus))

    # Weighting
    score = (score_exp * w_exp) + (score_s60 * w_s60) + (score_s90 * w_s90) + (score_bfr * w_wcr) + (score_bonus * w_bon)
    score = min(Decimal("5.0"), max(Decimal("0.0"), score))
    
    # Floor Rule FIN-10: Critical insolvency ceiling
    if stress_60d == StressDecision.INSOLVENT:
        score = min(score, ceil_60)
    elif stress_90d == StressDecision.INSOLVENT:
        score = min(score, ceil_90)

    return score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

def compute_stress_capacity(inputs: StressScenarioInputSchema, scenarios: List[dict], policy: PolicyConfigurationSchema) -> StressResultSchema:
    """Decoupled financial stress testing, purely transactional calculation."""
    
    exposition_pct = (inputs.contract_value / inputs.annual_ca_avg * Decimal("100")) if inputs.annual_ca_avg > Decimal("0") else Decimal("0.0")
    advance_amount = inputs.contract_value * inputs.advance_pct
    total_liquidity = inputs.cash_available + advance_amount + inputs.credit_lines

    # Estimated WCR
    annual_contract_ca = inputs.contract_value / max(Decimal(inputs.contract_months) / Decimal("12.0"), Decimal("0.1"))
    working_capital_requirement_estimate = annual_contract_ca * inputs.bfr_rate_sector

    monthly_flows = []
    
    min_cash_s2 = Decimal("Infinity")
    min_cash_s3 = Decimal("Infinity")
    cfo_missing = inputs.annual_caf_generated is None

    all_scenario_min_cash = {sc["name"]: Decimal("Infinity") for sc in scenarios}
    all_scenario_crit_month = {sc["name"]: None for sc in scenarios}

    for M in range(1, inputs.contract_months + 1):
        day = M * 30
        # M-08: Assumption of linearity for cumulative cash flow generation throughout the contract year.
        adjusted_caf = inputs.annual_caf_generated
        if adjusted_caf is not None:
            # P1-MULTIYEAR-03 Fixed: Apply prudent haircut if historical trend is declining
            caf_trend = getattr(inputs, 'historical_caf_cagr', Decimal("0.0"))
            if caf_trend < Decimal("0.0"):
                adjusted_caf = adjusted_caf * (Decimal("1.0") + caf_trend)
                
        caf_ratio = _safe_divide(adjusted_caf, Decimal("12.0")) or Decimal("0.0")
        caf_generated = caf_ratio * Decimal(M)
        
        flow_data = ScenarioFlowSchema(month=M, day=day, caf_generated=caf_generated.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        
        for sc in scenarios:
            name = sc["name"]
            delay = sc.get("delay_days", 0)
            overrun = Decimal(str(sc.get("cost_overrun", 0.0)))
            ca_shock = Decimal(str(sc.get("ca_shock", 0.0)))
            
            sc_contract_value = inputs.contract_value * (Decimal("1.0") + ca_shock)
            
            sc_payments = _simulate_milestone_payments(sc_contract_value, inputs.milestones, eval_day=day, delay_days=delay)
            sc_costs = _estimate_costs_at_day(inputs.contract_value, inputs.contract_months, day=day, policy=policy) * (Decimal("1.0") + overrun)
            
            sc_cash = total_liquidity + sc_payments - sc_costs + caf_generated
            
            flow_data.costs[f"costs_{name}"] = sc_costs.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            flow_data.cash[f"cash_{name}"] = sc_cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            
            if name == "S2_RETARD_60" and sc_cash < min_cash_s2:
                min_cash_s2 = sc_cash
            if name == "S3_RETARD_90" and sc_cash < min_cash_s3:
                min_cash_s3 = sc_cash

            if sc_cash < all_scenario_min_cash[name]:
                all_scenario_min_cash[name] = sc_cash
            if sc_cash < Decimal("0") and all_scenario_crit_month[name] is None:
                all_scenario_crit_month[name] = M
                
        monthly_flows.append(flow_data)

    stress_60d = _classify_stress(min_cash_s2 if min_cash_s2 != Decimal("Infinity") else Decimal("0"), working_capital_requirement_estimate)
    stress_90d = _classify_stress(min_cash_s3 if min_cash_s3 != Decimal("Infinity") else Decimal("0"), working_capital_requirement_estimate)

    scenarios_results = {}
    for sc in scenarios:
        name = sc["name"]
        mc = all_scenario_min_cash[name]
        mc = mc if mc != Decimal("Infinity") else Decimal("0")
        scenarios_results[name] = ScenarioSimulationResultSchema(
            name=name,
            status=_classify_stress(mc, working_capital_requirement_estimate),
            cash_remaining=mc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            critical_month=all_scenario_crit_month[name],
            config={k: str(v) for k, v in sc.items() if k != "name"}
        )

    score = _compute_capacity_score(
        exposition_pct=exposition_pct,
        current_ratio=_safe_divide(total_liquidity, working_capital_requirement_estimate) or Decimal("0.0"),
        stress_60d=stress_60d,
        stress_90d=stress_90d,
        advance_pct=inputs.advance_pct,
        annual_ca_avg=inputs.annual_ca_avg,
        backlog_value=inputs.backlog_value,
        bank_guarantee=inputs.bank_guarantee,
        bank_guarantee_amount=inputs.bank_guarantee_amount,
        policy=policy,  
    )

    data_alerts = []
    if cfo_missing:
        data_alerts.append("CFO_MISSING_ASSUMED_ZERO")

    return StressResultSchema(
        contract_value=inputs.contract_value,
        contract_months=inputs.contract_months,
        annual_ca_avg=inputs.annual_ca_avg,
        exposition_pct=exposition_pct.quantize(Decimal("0.01")),
        backlog_value=inputs.backlog_value,
        bank_guarantee=inputs.bank_guarantee,
        bank_guarantee_amount=inputs.bank_guarantee_amount,
        credit_lines_confirmed=inputs.credit_lines,
        cash_available=inputs.cash_available,
        working_capital_requirement_estimate=working_capital_requirement_estimate.quantize(Decimal("0.01")),
        advance_payment_pct=inputs.advance_pct * Decimal("100"),
        payment_milestones=inputs.milestones,
        stress_60d_result=stress_60d,
        stress_90d_result=stress_90d,
        stress_60d_cash_position=min_cash_s2.quantize(Decimal("0.01")) if min_cash_s2 != Decimal("Infinity") else Decimal("0"),
        stress_90d_cash_position=min_cash_s3.quantize(Decimal("0.01")) if min_cash_s3 != Decimal("Infinity") else Decimal("0"),
        score_capacity=score,
        capacity_conclusion=f"Capacity score: {score}. 60d stress: {stress_60d.value}. 90d stress: {stress_90d.value}.",
        monthly_flows=monthly_flows,
        scenarios_results=scenarios_results,
        data_alerts=data_alerts
    )
