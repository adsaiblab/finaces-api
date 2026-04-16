import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Optional, Any

from app.schemas.normalization_schema import NormalizedStatementUIResponse
from app.schemas.ratio_schema import RatioSetSchema, AlertSchema, ZScoreBreakdown
from app.schemas.policy_schema import PolicyConfigurationSchema

# ════════════════════════════════════════════════════════════════
# PURE SECURE ARITHMETIC HELPERS
# ════════════════════════════════════════════════════════════════

def _safe_divide(numerator: Optional[Decimal], denominator: Optional[Decimal], pct: bool = False) -> Optional[Decimal]:
    """
    CRITICAL: Secure division to prevent ZeroDivisionError.
    """
    if numerator is None or denominator is None or denominator == Decimal("0.0"):
        return None
    result = numerator / denominator
    return result * Decimal("100.0") if pct else result


def _safe_sub(a: Optional[Decimal], b: Optional[Decimal]) -> Optional[Decimal]:
    if a is None or b is None:
        return None
    return a - b


def _safe_sum(*values: Optional[Decimal], strict: bool = False) -> Optional[Decimal]:
    total = Decimal("0.0")
    has_data = False
    for v in values:
        if v is not None:
            total += v
            has_data = True
        elif strict:
            return None
    return total if has_data else None


# ════════════════════════════════════════════════════════════════
# ENGINE CALCULATION RATIOS (PURE FUNCTION)
# ════════════════════════════════════════════════════════════════

def compute_variations(current: RatioSetSchema, previous: RatioSetSchema) -> dict:
    """Calcule (N - N-1) / |N-1| * 100 pour chaque champ numérique."""
    variations = {}
    for field in current.model_fields:
        cur_val = getattr(current, field)
        prev_val = getattr(previous, field)
        if isinstance(cur_val, Decimal) and isinstance(prev_val, Decimal) and prev_val != 0:
            variations[f"{field}_variation_pct"] = float(
                ((cur_val - prev_val) / abs(prev_val)) * 100
            )
    return variations

def compute_ratios(norm: NormalizedStatementUIResponse, case_id: uuid.UUID, policy: PolicyConfigurationSchema) -> RatioSetSchema:
    """
    Pure Function: Computes all financial ratios from a Pydantic normalized statement.
    Totally decoupled from SQLAlchemy and FastAPI.
    """
    def _d(val: Any) -> Optional[Decimal]:
        if val is None:
            return None
        return Decimal(str(val))

    # Shortcuts
    ac = _d(norm.current_assets)
    al = _d(norm.liquid_assets)
    ai = _d(norm.non_current_assets)
    at = _d(norm.total_assets)
    pct_val = _d(norm.current_liabilities)
    plt = _d(norm.non_current_liabilities)
    ptot = _d(norm.total_liabilities_and_equity)
    cp = _d(norm.equity)
    ca = _d(norm.revenue)
    rn = _d(norm.net_income)
    ebitda = _d(norm.ebitda)
    cfo = _d(norm.operating_cash_flow)
    year = norm.fiscal_year

    # Shortcuts from the normalized layer
    stocks = _d(norm.inventory)
    creances = _d(norm.accounts_receivable)
    fourniss = _d(norm.accounts_payable)
    achats = _d(norm.cost_of_goods_sold)
    charges_f = _d(norm.financial_expenses)
    ebit = _d(norm.operating_income)
    dap = _d(norm.depreciation_and_amortization)
    df_lt = _d(norm.long_term_debt)
    df_ct = _d(norm.short_term_debt)

    # ── LIQUIDITY ─────────────────────────────────────────────
    current_ratio = _safe_divide(ac, pct_val)
    quick_ratio = _safe_divide(_safe_sub(ac, stocks), pct_val)
    cash_ratio = _safe_divide(al, pct_val)
    fdr = _safe_sub(ac, pct_val)

    # ── SOLVENCY ───────────────────────────────────────────
    dettes_fin = _safe_sum(df_lt, df_ct, strict=True)
    
    net_debt = None
    if dettes_fin is not None:
        if al is None:
            net_debt = None
        else:
            net_debt = dettes_fin - al
        
    dte = _safe_divide(dettes_fin, cp)
    autonomie = _safe_divide(cp, at)
    gearing = _safe_divide(net_debt, cp)

    interest_cov = None
    if ebit is not None and charges_f is not None and charges_f > Decimal("0.0"):
        interest_cov = _safe_divide(ebit, charges_f)

    # ── PROFITABILITY ───────────────────────────────────────────
    net_margin = _safe_divide(rn, ca, pct=True)
    ebitda_margin = _safe_divide(ebitda, ca, pct=True)
    op_margin = _safe_divide(ebit, ca, pct=True)
    roa = _safe_divide(rn, at, pct=True)
    
    roe = None
    if cp is not None:
        if cp < Decimal("0.0"):
            roe = None
        elif cp > Decimal("0.0"):
            roe = _safe_divide(rn, cp, pct=True)

    # ── ACTIVITY ──────────────────────────────────────────────
    dso = None
    dpo = None
    dio = None
    working_capital_requirement = None

    if creances is not None and ca is not None and ca > Decimal("0.0"):
        dso = _safe_divide(creances * Decimal("365"), ca)

    if fourniss is not None and achats is not None and achats > Decimal("0.0"):
        dpo = _safe_divide(fourniss * Decimal("365"), achats)

    if stocks is not None and achats is not None and achats > Decimal("0.0"):
        dio = _safe_divide(stocks * Decimal("365"), achats)

    if creances is not None and stocks is not None and fourniss is not None:
        working_capital_requirement = creances + stocks - fourniss

    working_capital_requirement_pct_revenue = _safe_divide(working_capital_requirement, ca, pct=True)

    ccc = None
    if dso is not None and dio is not None and dpo is not None:
        ccc = dso + dio - dpo

    # ── CASH FLOW GENERATION ───────────────────────────────────────
    cash_flow_capacity = None
    if rn is not None and dap is not None:
        cash_flow_capacity = rn + dap
    elif cfo is not None:
        cash_flow_capacity = cfo

    caf_margin = _safe_divide(cash_flow_capacity, ca, pct=True)

    debt_repayment = None
    if cash_flow_capacity is not None and cash_flow_capacity > Decimal("0.0") and dettes_fin is not None:
        debt_repayment = _safe_divide(dettes_fin, cash_flow_capacity)

    # ── AUTOMATIC FLAGS ────────────────────────────────────
    cap_neg = 1 if (cp is not None and cp < Decimal("0.0")) else 0
    cfo_neg = 1 if (cfo is not None and cfo < Decimal("0.0")) else 0

    # ── CONSISTENCY ALERTS ──────────────────────────────────
    coherence_alerts = []
    if at is not None and ptot is not None:
        diff = abs(at - ptot)
        mx = max(at, ptot)
        diff_pct = _safe_divide(diff, mx)
        if diff_pct and diff_pct > policy.ratio.balance_sheet_tolerance_pct: # <-- FIX
            coherence_alerts.append({
                "code": "UNBALANCED_BALANCE_SHEET",
                "message": f"Unbalanced balance sheet: gap {float(diff_pct):.1%}",
            })

    if current_ratio is not None and current_ratio < policy.ratio.very_low_current_ratio: # <-- FIX
        coherence_alerts.append({
            "code": "VERY_LOW_CURRENT_RATIO",
            "message": f"Very low Current Ratio: {float(current_ratio):.3f}",
        })

    if cp is not None and cp < Decimal("0.0"):
        coherence_alerts.append({
            "code": "NEGATIVE_EQUITY",
            "message": "Negative equity — critical financial situation",
        })

    # ── FINANCIAL INTELLIGENCE: ALTMAN Z-SCORE (EM) ─────────
    z_score_altman = None
    z_score_zone = None
    z_limits = {
        "safe": policy.ratio.z_score_safe_threshold,
        "grey": policy.ratio.z_score_grey_threshold
    } if (at and at > Decimal("0.0") and ptot and ptot > Decimal("0.0") and 
        ebit is not None and cp is not None and ac is not None and 
        pct_val is not None and rn is not None) else None
    
    if z_limits: # Only proceed if z_limits could be calculated
        dettes_totales = ptot - cp
        if dettes_totales > Decimal("0.0"):
            x1 = _safe_divide((ac - pct_val), at)
            x2 = _safe_divide(rn, at)
            x3 = _safe_divide(ebit, at)
            x4 = _safe_divide(cp, dettes_totales)
            
            if x1 is not None and x2 is not None and x3 is not None and x4 is not None:
                # P1-HARDCODE-01 Fixed
                c = policy.ratio.z_score_coefficients
                if not c:
                    from app.exceptions.finaces_exceptions import PolicyNotLoadedError
                    raise PolicyNotLoadedError("Missing Z-Score coefficients in policy")
                    
                z = (c["x1"] * x1) + (c["x2"] * x2) + (c["x3"] * x3) + (c["x4"] * x4)
                z_score_altman = z.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                
                if z_score_altman > z_limits["safe"]:
                    z_score_zone = "SAFE"
                elif z_score_altman >= z_limits["grey"]:
                    z_score_zone = "GREY"
                else:
                    z_score_zone = "DISTRESS"

    return RatioSetSchema(
        id=uuid.uuid4(),
        case_id=case_id,
        fiscal_year=year,
        normalized_statement_id=norm.id,
        current_ratio=current_ratio,
        quick_ratio=quick_ratio,
        cash_ratio=cash_ratio,
        working_capital=fdr,
        debt_to_equity=dte,
        financial_autonomy=autonomie,
        gearing=gearing,
        interest_coverage=interest_cov,
        net_margin=net_margin,
        ebitda_margin=ebitda_margin,
        operating_margin=op_margin,
        roa=roa,
        roe=roe,
        dso_days=dso,
        dpo_days=dpo,
        dio_days=dio,
        cash_conversion_cycle=ccc,
        working_capital_requirement=working_capital_requirement,
        working_capital_requirement_pct_revenue=working_capital_requirement_pct_revenue,
        cash_flow_capacity=cash_flow_capacity,
        cash_flow_capacity_margin_pct=caf_margin,
        debt_repayment_years=debt_repayment,
        negative_equity=cap_neg,
        negative_operating_cash_flow=cfo_neg,
        z_score_altman=z_score_altman,
        z_score_zone=z_score_zone,
        z_score_breakdown=ZScoreBreakdown(x1=x1, x2=x2, x3=x3, x4=x4) if (z_limits and x1 is not None) else None,
        coherence_alerts_json=coherence_alerts
    )

# ════════════════════════════════════════════════════════════════
# PURE ALERTS GENERATION
# ════════════════════════════════════════════════════════════════

def generate_alerts(ratio_set: RatioSetSchema, policy: PolicyConfigurationSchema) -> List[AlertSchema]:
    """
    Pure Function generating alerts from a ratio set,
    validated against a strict PolicyConfigurationSchema.
    """
    alerts = []
    year = ratio_set.fiscal_year
    
    alert_labels = policy.alert_labels

    def _add(key: str, value: Optional[Decimal], severity: str, note: str = "", affected: List[str] = [], action: str = ""):
        alerts.append(AlertSchema(
            key=key,
            label=alert_labels.get(key, key),
            year=year,
            value=value,
            severity=severity,
            note=note,
            affected_ratios=affected or [alert_labels.get(key, key)],
            suggested_action=action or "Verify the underlying financial normalization data for potential entry errors."
        ))

    if ratio_set.negative_equity:
        _add("negative_equity", None, "CRITICAL")

    if ratio_set.negative_operating_cash_flow:
        _add("negative_operating_cash_flow", ratio_set.cash_flow_capacity, "HIGH")

    rs_dict = ratio_set.model_dump()
    for field, t in policy.alert_thresholds.items():
        value = rs_dict.get(field)
        if value is None:
            continue

        min_val = t.min
        max_val = t.max
        warn_val = t.warn

        if min_val is not None:
            if value < min_val:
                _add(field, value, "HIGH", f"Value {float(value):.3f} < minimum threshold {float(min_val)}")
            elif warn_val is not None and value < warn_val:
                _add(field, value, "MEDIUM", f"Value {float(value):.3f} < warning threshold {float(warn_val)}")

        if max_val is not None:
            if value > max_val:
                _add(field, value, "HIGH", f"Value {float(value):.3f} > maximum threshold {float(max_val)}")
            elif warn_val is not None and value > warn_val:
                _add(field, value, "MEDIUM", f"Value {float(value):.3f} > warning threshold {float(warn_val)}")

    return alerts

    return alerts
