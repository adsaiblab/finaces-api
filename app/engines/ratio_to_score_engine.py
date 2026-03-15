"""
ratio_to_score_engine.py — Pure Conversion Layer (P0-01 Fix)

Converts raw financial ratios (RatioSetSchema) into normalized scores on a 0.0 → 5.0 scale.
This layer is mandatory between the Ratio Engine output and the Scoring Engine input.
All thresholds are derived from the injected PolicyConfigurationSchema for auditability.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.schemas.ratio_schema import RatioSetSchema
from app.schemas.policy_schema import PolicyConfigurationSchema


def _clamp(value: Decimal, lo: Decimal = Decimal("0.0"), hi: Decimal = Decimal("5.0")) -> Decimal:
    """Clamps any decimal value to the [lo, hi] range."""
    return max(lo, min(hi, value))


def _score_from_thresholds(
    value: Optional[Decimal],
    critical: Decimal,
    warn: Decimal,
    invert: bool = False,
) -> Decimal:
    """
    Maps a raw ratio value onto a 0.0–5.0 scale using two policy thresholds.

    - Above `warn` → 5.0 (excellent)
    - Between `critical` and `warn` → 3.0 (adequate)
    - Below `critical` → 1.0 (critical risk)

    When `invert=True` (lower is better, e.g. debt ratios):
    - Below `critical` → 5.0
    - Between `critical` and `warn` → 3.0
    - Above `warn` → 1.0
    """
    if value is None:
        return Decimal("0.0")

    if not invert:
        if value >= warn:
            return Decimal("5.0")
        elif value >= critical:
            return Decimal("3.0")
        else:
            return Decimal("1.0")
    else:
        if value <= critical:
            return Decimal("5.0")
        elif value <= warn:
            return Decimal("3.0")
        else:
            return Decimal("1.0")


from app.exceptions.finaces_exceptions import PolicyNotLoadedError

def convert_ratios_to_scores(ratios: RatioSetSchema, policy: PolicyConfigurationSchema) -> dict:
    """
    Pure Function — Fail-Fast Implementation (P1-HARDCODE-02 & P1-HARDCODE-03 Fixed).
    Raises PolicyNotLoadedError if ANY threshold is missing.
    """
    def _thresh(key: str, level: str) -> Decimal:
        try:
            thresh_obj = policy.alert_thresholds.get(key)
            if not thresh_obj:
                raise PolicyNotLoadedError(f"Missing policy threshold section: {key}")
            val = getattr(thresh_obj, level, None)
            if val is None:
                raise PolicyNotLoadedError(f"Missing policy threshold key: {key}.{level}")
            return Decimal(str(val))
        except Exception as e:
            if isinstance(e, PolicyNotLoadedError):
                raise
            raise PolicyNotLoadedError(f"Invalid threshold config for {key}.{level}")

    weights = policy.scoring.intra_pillar_weights

    # 1. LIQUIDITY PILLAR
    cr_warn = _thresh("current_ratio", "warn")
    cr_crit = _thresh("current_ratio", "min")
    score_cr = _score_from_thresholds(ratios.current_ratio, cr_crit, cr_warn, invert=False)

    qr_warn = _thresh("quick_ratio", "warn")
    qr_crit = _thresh("quick_ratio", "min")
    score_qr = _score_from_thresholds(ratios.quick_ratio, qr_crit, qr_warn, invert=False)

    liquidity_score = _clamp(((score_cr * weights.liquidity["primary"]) + (score_qr * weights.liquidity["secondary"]))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    # 2. SOLVENCY PILLAR
    fa_warn = _thresh("financial_autonomy", "warn")
    fa_crit = _thresh("financial_autonomy", "min")
    score_fa = _score_from_thresholds(ratios.financial_autonomy, fa_crit, fa_warn, invert=False)

    dte_warn = _thresh("debt_to_equity", "warn")
    dte_crit = _thresh("debt_to_equity", "min")
    score_dte = _score_from_thresholds(ratios.debt_to_equity, dte_crit, dte_warn, invert=True)

    solvency_score = _clamp(((score_fa * weights.solvency["primary"]) + (score_dte * weights.solvency["secondary"]))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    # 3. PROFITABILITY PILLAR
    nm_warn = _thresh("net_margin", "warn")
    nm_crit = _thresh("net_margin", "min")
    score_nm = _score_from_thresholds(ratios.net_margin, nm_crit, nm_warn, invert=False)

    om_warn = _thresh("operating_margin", "warn")
    om_crit = _thresh("operating_margin", "min")
    score_om = _score_from_thresholds(ratios.operating_margin, om_crit, om_warn, invert=False)

    profitability_score = _clamp(((score_nm * weights.profitability["primary"]) + (score_om * weights.profitability["secondary"]))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    # 4. CAPACITY PILLAR
    dry_warn = _thresh("debt_repayment_years", "warn")
    dry_crit = _thresh("debt_repayment_years", "min")
    score_dry = _score_from_thresholds(ratios.debt_repayment_years, dry_crit, dry_warn, invert=True)

    cfm_warn = _thresh("cash_flow_capacity_margin_pct", "warn")
    cfm_crit = _thresh("cash_flow_capacity_margin_pct", "min")
    score_cfm = _score_from_thresholds(ratios.cash_flow_capacity_margin_pct, cfm_crit, cfm_warn, invert=False)

    if ratios.negative_operating_cash_flow:
        score_dry  = min(score_dry,  Decimal("1.0"))
        score_cfm  = min(score_cfm, Decimal("1.0"))

    capacity_score = _clamp(((score_dry * weights.capacity["primary"]) + (score_cfm * weights.capacity["secondary"]))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    return {
        "liquidity_score":     liquidity_score,
        "solvency_score":      solvency_score,
        "profitability_score": profitability_score,
        "capacity_score":      capacity_score,
    }
