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
    All messages are in English for consistency with the financial module.
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
    cr = latest_ratio.current_ratio
    cash_ratio = latest_ratio.cash_ratio
    if cr and cr > th.false_liquidity_cr_min and cash_ratio and cash_ratio < th.false_liquidity_qr_max:
        alerts.append(AlertSchema(
            pattern="FALSE_LIQUIDITY",
            severity="WARNING",
            description="Illusory Liquidity: High current ratio masked by low immediate liquidity (funds blocked in inventory or slow receivables).",
            affected_ratios=["Current Ratio", "Cash Ratio", "Inventory Turnover"],
            suggested_action="Perform an aging analysis of accounts receivable and audit inventory obsolescence."
        ))
        
    # ── 2. HIDDEN_OVERLEVERAGE (CRITICAL) ─────────────────────────────
    roe = latest_ratio.roe
    gearing = latest_ratio.gearing
    if roe and roe >= th.overleverage_roe_min and gearing and gearing > th.overleverage_dte_min:
        alerts.append(AlertSchema(
            pattern="HIDDEN_OVERLEVERAGE",
            severity="CRITICAL",
            description="Critical Leverage: Return on Equity (ROE) is artificially inflated by excessive debt levels.",
            affected_ratios=["ROE", "Gearing", "Debt-to-Equity"],
            suggested_action="Review debt structure and consider equity injection to stabilize the solvency profile."
        ))
        
    # ── 3. TOXIC_WCR (CRITICAL) ───────────────────────────────────────
    wcr_pct = latest_ratio.working_capital_requirement_pct_revenue
    cfo_neg = latest_ratio.negative_operating_cash_flow
    if wcr_pct and wcr_pct > th.toxic_wcr_pct_min and cfo_neg == 1:
        alerts.append(AlertSchema(
            pattern="TOXIC_WCR",
            severity="CRITICAL",
            description="Operational Asphyxiation: WCR weight (>30% Revenue) is consuming all resources and destroying operating cash flow.",
            affected_ratios=["WCR % Revenue", "Operating Cash Flow"],
            suggested_action="Optimize the cash conversion cycle and renegotiate supplier payment terms."
        ))
        
    # ── 4. SCISSORS_EFFECT (Graded) ───────────────────────────────────
    if len(ratio_sets) >= 2:
        first_ratio = ratio_sets[0]
        first_norm = next((n for n in normalized_statements if n.fiscal_year == first_ratio.fiscal_year), None)
        
        proxy1_active = False
        proxy2_active = False
        
        eb_latest, eb_first = latest_ratio.ebitda_margin, first_ratio.ebitda_margin
        bfr_latest, bfr_first = latest_ratio.working_capital_requirement_pct_revenue, first_ratio.working_capital_requirement_pct_revenue
        
        if eb_latest is not None and eb_first is not None and bfr_latest is not None and bfr_first is not None:
            if eb_latest < (eb_first - th.scissors_margin_drop) and bfr_latest > (bfr_first + th.scissors_wcr_rise):
                proxy1_active = True
                
        if latest_norm and first_norm:
            def _get_fixed_costs(n):
                return (Decimal(str(n.personnel_expenses)) + Decimal(str(n.external_expenses)) + 
                        Decimal(str(n.taxes_and_duties)) + Decimal(str(n.depreciation_and_amortization)))
            fc_latest, fc_first = _get_fixed_costs(latest_norm), _get_fixed_costs(first_norm)
            d_rev_first, d_rev_latest = Decimal(str(first_norm.revenue)), Decimal(str(latest_norm.revenue))
            if d_rev_first > 0 and d_rev_latest < (d_rev_first * Decimal("0.95")):
                if fc_latest >= (fc_first * Decimal("0.98")):
                    proxy2_active = True
        
        if proxy1_active or proxy2_active:
            severity = "CRITICAL" if (proxy1_active and proxy2_active) else "WARNING"
            if proxy1_active and proxy2_active:
                msg = "Double Scissors Confirmed: Simultaneous degradation of margins, WCR weight, and fixed cost structure."
            elif proxy1_active:
                msg = "Margin/WCR Scissors: Declining profitability coupled with rising working capital financing needs."
            else:
                msg = "Revenue/Fixed Costs Scissors: Sharp decline in activity without proportional reduction in structural costs."
                
            alerts.append(AlertSchema(
                pattern="SCISSORS_EFFECT",
                severity=severity,
                description=msg,
                affected_ratios=["EBITDA Margin", "WCR % Revenue", "Revenue"],
                suggested_action="Implement an emergency cost-reduction plan and pivot to higher-margin activities."
            ))

    # ── 5. NEGATIVE_EQUITY (CRITICAL) ──────────────────────────────────
    if latest_ratio.negative_equity == 1:
        alerts.append(AlertSchema(
            pattern="NEGATIVE_EQUITY",
            severity="CRITICAL",
            description="Technical Insolvency: Total equity is negative, signaling technical or legal bankruptcy requiring urgent recapitalization.",
            affected_ratios=["Total Equity", "Financial Autonomy"],
            suggested_action="Immediate mandatory recapitalization required to restore the legal existence of the entity."
        ))

    # ── 6. EARNINGS_QUALITY (CRITICAL) ─────────────────────────────────
    nm, cfo_neg = latest_ratio.net_margin, latest_ratio.negative_operating_cash_flow
    if nm is not None and nm >= Decimal("0.005") and cfo_neg == 1:
        burn_ratio_mention = ""
        if latest_norm and latest_norm.operating_cash_flow and latest_norm.net_income and latest_norm.net_income > 0:
            burn_ratio = abs(latest_norm.operating_cash_flow / latest_norm.net_income)
            burn_ratio_mention = f" Severity confirmed: for every 1 MAD of accounting profit reported, the company actually burned {burn_ratio:.2f} MAD in operating cash."

        alerts.append(AlertSchema(
            pattern="EARNINGS_QUALITY",
            severity="CRITICAL",
            description="Cash Divergence: The company reports significant accounting profits but is destroying its operating cash (Enron-style alert)." + burn_ratio_mention,
            affected_ratios=["Net Margin", "Operating Cash Flow"],
            suggested_action="Audit revenue recognition policies and verify lead-to-cash cycle efficiency."
        ))

    # ── 7. MATURITY_MISMATCH (WARNING) ─────────────────────────────────
    wc = latest_ratio.working_capital
    if wc is not None and wc < 0:
        alerts.append(AlertSchema(
            pattern="MATURITY_MISMATCH",
            severity="WARNING",
            description="Structural Imbalance: Working Capital is negative, indicating that long-term assets are being financed by short-term debt (transformation risk).",
            affected_ratios=["Working Capital", "Gearing"],
            suggested_action="Consolidate short-term debt into medium/long-term financing to secure the top-of-balance-sheet balance."
        ))
                
    return alerts
