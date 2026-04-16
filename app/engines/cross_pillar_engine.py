import uuid
from decimal import Decimal
from typing import List, Optional
from app.schemas.ratio_schema import RatioSetSchema, AlertSchema
from app.schemas.normalization_schema import NormalizedStatementUIResponse
from app.schemas.policy_schema import PolicyConfigurationSchema

def generate_cross_pillar_patterns(
    ratio_sets: List[RatioSetSchema], 
    normalized_statements: List[NormalizedStatementUIResponse],
    policy: PolicyConfigurationSchema
) -> List[AlertSchema]:
    """
    Pure Function detecting complex cross-period and cross-pillar financial patterns.
    Follows P3-CROSS-PILLAR rules for FinaCES.
    """
    alerts = []
    if not ratio_sets or not normalized_statements:
        return alerts
        
    # Sort by year to ensure correct trend analysis
    ratio_sets.sort(key=lambda x: x.fiscal_year)
    normalized_statements.sort(key=lambda x: x.fiscal_year)
    
    latest_ratio = ratio_sets[-1]
    latest_norm = next((n for n in normalized_statements if n.fiscal_year == latest_ratio.fiscal_year), None)
    
    if not latest_norm:
        return alerts

    th = policy.cross_pillar
    
    # ── 1. FALSE_LIQUIDITY (WARNING) ──────────────────────────────────
    # High Current Ratio but low Cash Ratio
    cr = latest_ratio.current_ratio
    cash_ratio = latest_ratio.cash_ratio
    if cr and cr > th.false_liquidity_cr_min and cash_ratio and cash_ratio < th.false_liquidity_qr_max:
        alerts.append(AlertSchema(
            pattern="FALSE_LIQUIDITY",
            severity="WARNING",
            description="Trésorerie illusoire : le ratio courant est élevé mais la liquidité immédiate est faible (fonds bloqués dans les stocks/créances)."
        ))
        
    # ── 2. HIDDEN_OVERLEVERAGE (CRITICAL) ─────────────────────────────
    # High ROE driven by excessive gearing
    roe = latest_ratio.roe
    gearing = latest_ratio.gearing
    if roe and roe >= th.overleverage_roe_min and gearing and gearing > th.overleverage_dte_min:
        alerts.append(AlertSchema(
            pattern="HIDDEN_OVERLEVERAGE",
            severity="CRITICAL",
            description="Levier d'endettement critique : la rentabilité financière (ROE) est dopée par un surendettement masqué."
        ))
        
    # ── 3. TOXIC_WCR (CRITICAL) ───────────────────────────────────────
    # WCR consuming all revenue resources and killing cash flow
    wcr_pct = latest_ratio.working_capital_requirement_pct_revenue
    cfo = latest_ratio.negative_operating_cash_flow # 1 if negative, 0 if positive
    if wcr_pct and wcr_pct > th.toxic_wcr_pct_min and cfo == 1:
        alerts.append(AlertSchema(
            pattern="TOXIC_WCR",
            severity="CRITICAL",
            description="Asphyxie opérationnelle : le poids du BFR (>30% CA) consomme toute la ressource et détruit le cash-flow d'exploitation."
        ))
        
    # ── 4. SCISSORS_EFFECT (Graded) ───────────────────────────────────
    if len(ratio_sets) >= 2:
        first_ratio = ratio_sets[0]
        first_norm = next((n for n in normalized_statements if n.fiscal_year == first_ratio.fiscal_year), None)
        
        proxy1_active = False
        proxy2_active = False
        
        # Proxy 1: Margin/WCR (EBITDA margin drop + WCR rise)
        eb_latest = latest_ratio.ebitda_margin
        eb_first = first_ratio.ebitda_margin
        bfr_latest = latest_ratio.working_capital_requirement_pct_revenue
        bfr_first = first_ratio.working_capital_requirement_pct_revenue
        
        if eb_latest is not None and eb_first is not None and bfr_latest is not None and bfr_first is not None:
            if eb_latest < (eb_first - th.scissors_margin_drop) and bfr_latest > (bfr_first + th.scissors_wcr_rise):
                proxy1_active = True
                
        # Proxy 2: Revenue/Fixed Costs (Revenue drop + Fixed costs stable/rise)
        if latest_norm and first_norm:
            rev_latest = latest_norm.revenue
            rev_first = first_norm.revenue
            
            # Helper to approximate fixed costs: Personnel + External + Taxes + Amort.
            def _get_fixed_costs(n):
                return (n.personnel_expenses + n.external_expenses + 
                        n.taxes_and_duties + n.depreciation_and_amortization)
            
            fc_latest = _get_fixed_costs(latest_norm)
            fc_first = _get_fixed_costs(first_norm)
            
            # Revenue drop > 5% (hardcoded safety or policy)
            if rev_first > 0 and rev_latest < (rev_first * Decimal("0.95")):
                if fc_latest >= (fc_first * Decimal("0.98")): # Stable or rising
                    proxy2_active = True
        
        if proxy1_active or proxy2_active:
            msg = ""
            severity = "WARNING"
            if proxy1_active and proxy2_active:
                msg = "Double ciseau confirmé : dégradation simultanée des marges, du BFR et du poids des charges fixes."
                severity = "CRITICAL"
            elif proxy1_active:
                msg = "Ciseau marge/WCR : dégradation de la rentabilité couplée à une augmentation du besoin de financement."
            else:
                msg = "Ciseau CA/charges fixes : chute de l'activité sans réduction proportionnelle de la structure de coûts."
                
            alerts.append(AlertSchema(
                pattern="SCISSORS_EFFECT",
                severity=severity,
                description=msg
            ))
                
    return alerts
