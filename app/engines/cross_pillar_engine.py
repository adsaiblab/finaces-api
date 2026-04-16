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
            description="High risk of Illusory Liquidity detected.",
            note="The current ratio suggests stability, but cash is severely restricted. Large portions of your working capital are likely trapped in slow-moving inventory or overdue receivables.",
            affected_ratios=["Current Ratio", "Cash Ratio", "DIO"],
            suggested_action="Perform an aging analysis of accounts receivable and audit inventory for obsolescence."
        ))
        
    # ── 2. HIDDEN_OVERLEVERAGE (CRITICAL) ─────────────────────────────
    roe = latest_ratio.roe
    gearing = latest_ratio.gearing
    if roe and roe >= th.overleverage_roe_min and gearing and gearing > th.overleverage_dte_min:
        alerts.append(AlertSchema(
            pattern="HIDDEN_OVERLEVERAGE",
            severity="CRITICAL",
            description="Critical Debt-Driven ROE Inflation.",
            note="The impressive Return on Equity is currently driven by excessive debt rather than operational efficiency. This high gearing profile creates a 'tower of cards' vulnerability to interest rate shifts.",
            affected_ratios=["ROE", "Gearing", "Interest Coverage"],
            suggested_action="Review debt structure immediately and consider equity injection to de-risk the balance sheet."
        ))
        
    # ── 3. TOXIC_WCR (CRITICAL) ───────────────────────────────────────
    wcr_pct = latest_ratio.working_capital_requirement_pct_revenue
    cfo_neg = latest_ratio.negative_operating_cash_flow
    if wcr_pct and wcr_pct > th.toxic_wcr_pct_min and cfo_neg == 1:
        alerts.append(AlertSchema(
            pattern="TOXIC_WCR",
            severity="CRITICAL",
            description="Operational Cash Asphyxiation.",
            note="WCR weight (>30% Revenue) is consuming all operational resources. The company is actively destroying cash flow to finance its daily operations, signaling imminent liquidity distress.",
            affected_ratios=["WCR % Revenue", "Operating Cash Flow"],
            suggested_action="Optimize the cash conversion cycle and negotiate stricter terms for receivables collection."
        ))
        
    # ── 4. SCISSORS_EFFECT (Graded) ───────────────────────────────────
    if len(ratio_sets) >= 2:
        first_ratio, last_ratio = ratio_sets[0], ratio_sets[-1]
        p1_active, p2_active = False, False
        
        eb_latest, eb_first = last_ratio.ebitda_margin, first_ratio.ebitda_margin
        bfr_latest, bfr_first = last_ratio.working_capital_requirement_pct_revenue, first_ratio.working_capital_requirement_pct_revenue
        
        if eb_latest is not None and eb_first is not None and bfr_latest is not None and bfr_first is not None:
            if eb_latest < (eb_first - th.scissors_margin_drop) and bfr_latest > (bfr_first + th.scissors_wcr_rise):
                p1_active = True
                
        def _get_fixed_costs(n):
            return (Decimal(str(n.personnel_expenses)) + Decimal(str(n.external_expenses)) + 
                    Decimal(str(n.taxes_and_duties)) + Decimal(str(n.depreciation_and_amortization)))
        fc_latest, fc_first = _get_fixed_costs(latest_norm), _get_fixed_costs(normalized_statements[0])
        rev_latest, rev_first = Decimal(str(latest_norm.revenue)), Decimal(str(normalized_statements[0].revenue))
        if rev_first > 0 and rev_latest < (rev_first * Decimal("0.95")):
            if fc_latest >= (fc_first * Decimal("0.98")):
                p2_active = True
        
        if p1_active or p2_active:
            severity = "CRITICAL" if (p1_active and p2_active) else "WARNING"
            headline = "Double Scissors Effect Confirmed." if (p1_active and p2_active) else "Severe Scissors Effect Pattern Detected."
            analysis = "Simultaneous collapse of operating margins and sharp rise in working capital finance needs." if p1_active else "Sharp revenue decline coupled with a rigid, non-reducing fixed cost structure."
            if p1_active and p2_active: analysis = "Critical divergence where revenue/margins fall while costs and WCR rise simultaneously."
                
            alerts.append(AlertSchema(
                pattern="SCISSORS_EFFECT",
                severity=severity,
                description=headline,
                note=analysis,
                affected_ratios=["EBITDA Margin", "Revenue", "WCR % Revenue"],
                suggested_action="Implement urgent structural cost reductions and pivot toward high-margin revenue streams."
            ))

    # ── 5. NEGATIVE_EQUITY (CRITICAL) ──────────────────────────────────
    if latest_ratio.negative_equity == 1:
        alerts.append(AlertSchema(
            pattern="NEGATIVE_EQUITY",
            severity="CRITICAL",
            description="Technical & Legal Insolvency.",
            note="Total equity has fallen below zero. The entity is technically bankrupt and, in most jurisdictions, requires immediate legal action or mandatory recapitalization to continue operating.",
            affected_ratios=["Equity", "Financial Autonomy"],
            suggested_action="Initiate mandatory recapitalization and legal review of solvency status."
        ))

    # ── 6. EARNINGS_QUALITY (CRITICAL) ─────────────────────────────────
    nm, cfo_neg = latest_ratio.net_margin, latest_ratio.negative_operating_cash_flow
    if nm is not None and nm >= Decimal("0.005") and cfo_neg == 1:
        burn_ratio_mention = ""
        if latest_norm and latest_norm.operating_cash_flow and latest_norm.net_income and latest_norm.net_income > 0:
            burn_ratio = abs(latest_norm.operating_cash_flow / latest_norm.net_income)
            burn_ratio_mention = f" For every 1 MAD of accounting profit, the company burned {burn_ratio:.2f} MAD in actual cash."

        alerts.append(AlertSchema(
            pattern="EARNINGS_QUALITY",
            severity="CRITICAL",
            description="Major Profit/Cash Flow Divergence.",
            note=f"High-risk 'Enron' pattern: The company reports healthy accounting profits but is destroying cash at an operational level.{burn_ratio_mention}",
            affected_ratios=["Net Margin", "Operating Cash Flow"],
            suggested_action="Audit revenue recognition policies and investigate potential accrual manipulation."
        ))

    # ── 7. MATURITY_MISMATCH (WARNING) ─────────────────────────────────
    wc = latest_ratio.working_capital
    if wc is not None and wc < 0:
        alerts.append(AlertSchema(
            pattern="MATURITY_MISMATCH",
            severity="WARNING",
            description="Structural Financing Imbalance.",
            note="Working capital is negative, meaning long-term assets are being financed by short-term bank debt. This mismatch creates extreme vulnerability to sudden credit line cancellations.",
            affected_ratios=["Working Capital", "Gearing"],
            suggested_action="Secure long-term financing to stabilize the balance sheet and reduce transformation risk."
        ))
                
    return alerts
