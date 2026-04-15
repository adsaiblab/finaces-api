import uuid
import json
from decimal import Decimal
from typing import List, Dict, Optional, Any

from app.schemas.normalization_schema import (
    FinancialStatementRawSchema,
    AdjustmentSchema,
    FinancialStatementNormalizedSchema,
)
from app.exceptions.finaces_exceptions import (
    MissingFinancialDataError,
    EngineComputationError,
)

# ════════════════════════════════════════════════════════════════
# INTERNAL HELPERS (PURE)
# ════════════════════════════════════════════════════════════════

def _safe_sum(*values: Optional[Decimal]) -> Optional[Decimal]:
    """Pure function to safely sum Decimal values, ignoring Nones."""
    total = Decimal("0.0")
    has_data = False
    for v in values:
        if v is not None:
            total += v
            has_data = True
    return total if has_data else None

def _safe_divide(num: Optional[Decimal], den: Optional[Decimal]) -> Optional[Decimal]:
    """Safe division preventing ZeroDivisionError and handling None values."""
    if num is None or den is None or den == Decimal("0.0"):
        return None
    return num / den


def _build_normalized_json(raw: FinancialStatementRawSchema, aggregates: Dict[str, Optional[Decimal]]) -> str:
    """Builds the L1/L2/L3 structured JSON in pure data mode without losing Decimal precision."""
    
    def decimal_to_str(d: Optional[Decimal]) -> Optional[str]:
        return str(d) if d is not None else None

    structure = {
        "L1_balance_sheet": {
            "total_assets":       decimal_to_str(aggregates.get("total_assets")),
            "current_assets":     decimal_to_str(aggregates.get("current_assets")),
            "non_current_assets":  decimal_to_str(aggregates.get("non_current_assets")),
            "total_liabilities_and_equity":      decimal_to_str(aggregates.get("total_liabilities_and_equity")),
            "equity":  decimal_to_str(aggregates.get("equity")),
            "non_current_liabilities":         decimal_to_str(aggregates.get("non_current_liabilities")),
            "current_liabilities":         decimal_to_str(aggregates.get("current_liabilities")),
        },
        "L2_income_statement": {
            "revenue":  decimal_to_str(aggregates.get("revenue")),
            "ebitda":            decimal_to_str(aggregates.get("ebitda")),
            "net_income":      decimal_to_str(aggregates.get("net_income")),
        },
        "L3_cash_flows": {
            "operating_cash_flow": decimal_to_str(aggregates.get("operating_cash_flow")),
            "liquid_assets":          decimal_to_str(aggregates.get("liquid_assets")),
        },
        "meta": {
            "fiscal_year":        raw.fiscal_year,
            "currency":           raw.currency_original,
            "exchange_rate":      decimal_to_str(raw.exchange_rate_to_usd),
            "referentiel":        raw.referentiel,
            "is_consolidated":    raw.is_consolidated,
        },
    }
    return json.dumps(structure, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
# ADJUSTMENT SUBSTITUTION ENGINE
# ════════════════════════════════════════════════════════════════

class AdjustedRawState:
    """Pure structure isolating the ADD/REPLACE logic of Raw variables."""
    def __init__(self, raw: FinancialStatementRawSchema, adjs: list[AdjustmentSchema]):
        self.raw = raw
        self.final_values: Dict[str, Decimal] = {}
        self.has_adj = set()
        
        # The history of adjustments dictates the final value (chronological order assumed)
        for a in adjs:
            if a.field and a.amount_after is not None:
                field = a.field
                mode = getattr(a, 'mode', 'add')
                
                # Fetch baseline if uninitiated
                if field not in self.final_values:
                    val = getattr(self.raw, field, None)
                    self.final_values[field] = val if val is not None else Decimal("0.0")
                
                if mode == 'replace':
                    self.final_values[field] = a.amount_after
                else:
                    # mode == 'add'
                    delta = a.amount_after - a.amount_before
                    self.final_values[field] += delta
                    
                self.has_adj.add(field)

    def get(self, name: str) -> Optional[Decimal]:
        if name in self.has_adj:
            return self.final_values[name]
        return getattr(self.raw, name, None)


# ════════════════════════════════════════════════════════════════
# PURE MATHEMATICAL LOGIC
# ════════════════════════════════════════════════════════════════

def calculate_normalized_aggregates(
    raw: FinancialStatementRawSchema, 
    adjustments: List[AdjustmentSchema]
) -> FinancialStatementNormalizedSchema:
    """
    Pure Function: Core engine for FinaCES standardization.
    Standardizes raw financial data into a consistent USD-denominated schema.
    """
    
    ar = AdjustedRawState(raw, adjustments)

    # 1. EXTRACTION DES COMPOSANTS (Devise Originale)
    # --- Assets ---
    liquid_assets      = ar.get("liquid_assets") or Decimal("0.0")
    inventory          = ar.get("inventory") or Decimal("0.0")
    accounts_receiv    = ar.get("accounts_receivable") or Decimal("0.0")
    other_curr_assets  = ar.get("other_current_assets") or Decimal("0.0")
    
    intangible_assets  = ar.get("intangible_assets") or Decimal("0.0")
    tangible_assets    = ar.get("tangible_assets") or Decimal("0.0")
    financial_assets   = ar.get("financial_assets") or Decimal("0.0")
    other_non_curr     = ar.get("other_noncurrent_assets") or Decimal("0.0")

    # --- Liabilities ---
    share_capital      = ar.get("share_capital") or Decimal("0.0")
    reserves           = ar.get("reserves") or Decimal("0.0")
    retained_prior     = ar.get("retained_earnings_prior") or Decimal("0.0")
    current_earnings   = ar.get("current_year_earnings") or Decimal("0.0")
    
    short_term_debt    = ar.get("short_term_debt") or Decimal("0.0")
    accounts_payable   = ar.get("accounts_payable") or Decimal("0.0")
    tax_social_liab    = ar.get("tax_and_social_liabilities") or Decimal("0.0")
    other_curr_liab    = ar.get("other_current_liabilities") or Decimal("0.0")
    
    long_term_debt     = ar.get("long_term_debt") or Decimal("0.0")
    long_term_prov     = ar.get("long_term_provisions") or Decimal("0.0")

    # --- P&L ---
    revenue            = ar.get("revenue") or Decimal("0.0")
    sold_production    = ar.get("sold_production") or Decimal("0.0")
    other_op_revenue   = ar.get("other_operating_revenue") or Decimal("0.0")
    cost_goods_sold    = ar.get("cost_of_goods_sold") or Decimal("0.0")
    external_expenses  = ar.get("external_expenses") or Decimal("0.0")
    personnel_expenses = ar.get("personnel_expenses") or Decimal("0.0")
    taxes_and_duties   = ar.get("taxes_and_duties") or Decimal("0.0")
    depreciation_amort = ar.get("depreciation_and_amortization") or Decimal("0.0")
    operating_income   = ar.get("operating_income") or Decimal("0.0")
    financial_revenue  = ar.get("financial_revenue") or Decimal("0.0")
    financial_expenses = ar.get("financial_expenses") or Decimal("0.0")
    financial_income   = ar.get("financial_income") or Decimal("0.0")
    income_before_tax  = ar.get("income_before_tax") or Decimal("0.0")
    extraordinary_inc  = ar.get("extraordinary_income") or Decimal("0.0")
    income_tax         = ar.get("income_tax") or Decimal("0.0")

    # --- Cash Flows & Meta ---
    op_cash_flow       = ar.get("operating_cash_flow") or Decimal("0.0")
    inv_cash_flow      = ar.get("investing_cash_flow") or Decimal("0.0")
    fin_cash_flow      = ar.get("financing_cash_flow") or Decimal("0.0")
    change_in_cash     = ar.get("change_in_cash") or Decimal("0.0")
    beginning_cash     = ar.get("beginning_cash") or Decimal("0.0")
    ending_cash        = ar.get("ending_cash") or Decimal("0.0")
    backlog_value      = ar.get("backlog_value") or Decimal("0.0")
    capex              = ar.get("capex") or Decimal("0.0")
    headcount          = ar.get("headcount")

    # 2. CALCULS D'AGRÉGATS BOTTOM-UP (Devise Originale)
    # Construction des Actifs
    non_current_assets = ar.get("non_current_assets")
    if not non_current_assets:
        non_current_assets = _safe_sum(intangible_assets, tangible_assets, financial_assets, other_non_curr)
    non_current_assets = non_current_assets or Decimal("0.0")
    
    current_assets = ar.get("current_assets")
    if not current_assets:
        current_assets = _safe_sum(liquid_assets, inventory, accounts_receiv, other_curr_assets)
    current_assets = current_assets or Decimal("0.0")
    
    total_assets = ar.get("total_assets")
    if not total_assets:
        total_assets = _safe_sum(current_assets, non_current_assets)
    total_assets = total_assets or Decimal("0.0")

    # Reconstruction des Passifs
    equity_calc = ar.get("equity")
    if not equity_calc:
        equity_calc = _safe_sum(share_capital, reserves, retained_prior, current_earnings)
    equity = equity_calc or Decimal("0.0")

    current_liabilities = ar.get("current_liabilities")
    if not current_liabilities:
        current_liabilities = _safe_sum(short_term_debt, accounts_payable, tax_social_liab, other_curr_liab)
    current_liabilities = current_liabilities or Decimal("0.0")

    non_current_liabilities = ar.get("non_current_liabilities")
    if not non_current_liabilities:
        non_current_liabilities = _safe_sum(long_term_debt, long_term_prov)
    non_current_liabilities = non_current_liabilities or Decimal("0.0")

    total_liabilities_and_equity = ar.get("total_liabilities_and_equity")
    if not total_liabilities_and_equity:
        total_liabilities_and_equity = _safe_sum(equity, non_current_liabilities, current_liabilities)
    total_liabilities_and_equity = total_liabilities_and_equity or Decimal("0.0")

    # Reconstruction du P&L
    if not revenue:
        revenue = sold_production or Decimal("0.0")

    net_income = ar.get("net_income") or Decimal("0.0")
    
    ebitda = ar.get("ebitda")
    if not ebitda:
        if operating_income and depreciation_amort:
            ebitda = operating_income + depreciation_amort
    ebitda = ebitda or Decimal("0.0")

    # 3. VALIDATION ÉQUILIBRE BILAN (Devise Originale)
    if total_assets and total_liabilities_and_equity:
        diff_pct = _safe_divide(abs(total_assets - total_liabilities_and_equity), max(total_assets, total_liabilities_and_equity))
        if diff_pct and diff_pct > Decimal("0.01"):
            raise EngineComputationError(
                message=f"Unbalanced balance sheet by {float(diff_pct):.1%}. Submission locked.", 
                details={"error_code": "UNBALANCED_BALANCE_SHEET"}
            )

    # 4. CONVERSION USD
    rate = raw.exchange_rate_to_usd or Decimal("1.0")
    if rate <= 0:
        raise EngineComputationError(f"exchange_rate_to_usd invalide : {rate}")

    def _to_usd(val: Optional[Decimal]) -> Decimal:
        if val is None:
            return Decimal("0.0")
        return (val / rate).quantize(Decimal("0.01"))

    # Conversion unitaire par champ (lisibilité maximale)
    total_assets                  = _to_usd(total_assets)
    current_assets                = _to_usd(current_assets)
    non_current_assets            = _to_usd(non_current_assets)
    liquid_assets                 = _to_usd(liquid_assets)
    inventory                     = _to_usd(inventory)
    accounts_receiv               = _to_usd(accounts_receiv)
    other_curr_assets             = _to_usd(other_curr_assets)
    intangible_assets             = _to_usd(intangible_assets)
    tangible_assets               = _to_usd(tangible_assets)
    financial_assets              = _to_usd(financial_assets)

    total_liabilities_and_equity  = _to_usd(total_liabilities_and_equity)
    equity                        = _to_usd(equity)
    share_capital                 = _to_usd(share_capital)
    reserves                      = _to_usd(reserves)
    retained_prior                = _to_usd(retained_prior)
    current_earnings              = _to_usd(current_earnings)
    non_current_liabilities       = _to_usd(non_current_liabilities)
    current_liabilities           = _to_usd(current_liabilities)
    long_term_debt                = _to_usd(long_term_debt)
    long_term_prov                = _to_usd(long_term_prov)
    short_term_debt               = _to_usd(short_term_debt)
    accounts_payable              = _to_usd(accounts_payable)
    tax_social_liab               = _to_usd(tax_social_liab)
    other_curr_liab               = _to_usd(other_curr_liab)

    revenue                       = _to_usd(revenue)
    sold_production               = _to_usd(sold_production)
    other_op_revenue              = _to_usd(other_op_revenue)
    cost_goods_sold               = _to_usd(cost_goods_sold)
    external_expenses             = _to_usd(external_expenses)
    personnel_expenses            = _to_usd(personnel_expenses)
    taxes_and_duties              = _to_usd(taxes_and_duties)
    depreciation_amort            = _to_usd(depreciation_amort)
    operating_income              = _to_usd(operating_income)
    financial_revenue             = _to_usd(financial_revenue)
    financial_expenses            = _to_usd(financial_expenses)
    financial_income              = _to_usd(financial_income)
    income_before_tax             = _to_usd(income_before_tax)
    extraordinary_inc             = _to_usd(extraordinary_inc)
    income_tax                    = _to_usd(income_tax)
    net_income                    = _to_usd(net_income)
    ebitda                        = _to_usd(ebitda)

    op_cash_flow                  = _to_usd(op_cash_flow)
    inv_cash_flow                 = _to_usd(inv_cash_flow)
    fin_cash_flow                 = _to_usd(fin_cash_flow)
    change_in_cash                = _to_usd(change_in_cash)
    beginning_cash                = _to_usd(beginning_cash)
    ending_cash                   = _to_usd(ending_cash)
    backlog_value                 = _to_usd(backlog_value)
    capex                         = _to_usd(capex)

    # 5. GÉNÉRATION JSON & RETOUR (Full USD)
    normalized_json = _build_normalized_json(raw, {
        "total_assets":            total_assets,
        "current_assets":          current_assets,
        "liquid_assets":          liquid_assets,
        "non_current_assets":       non_current_assets,
        "total_liabilities_and_equity":           total_liabilities_and_equity,
        "current_liabilities":              current_liabilities,
        "non_current_liabilities":              non_current_liabilities,
        "equity":       equity,
        "revenue":       revenue,
        "net_income":           net_income,
        "ebitda":                 ebitda,
        "operating_cash_flow": op_cash_flow,
    })

    return FinancialStatementNormalizedSchema(
        id=uuid.uuid4(),
        raw_statement_id=raw.id,
        fiscal_year=raw.fiscal_year,
        currency_usd="USD",
        exchange_rate=rate,
        total_assets=total_assets,
        current_assets=current_assets,
        liquid_assets=liquid_assets,
        inventory=inventory,
        accounts_receivable=accounts_receiv,
        other_current_assets=other_curr_assets,
        non_current_assets=non_current_assets,
        intangible_assets=intangible_assets,
        tangible_assets=tangible_assets,
        financial_assets=financial_assets,
        total_liabilities_and_equity=total_liabilities_and_equity,
        equity=equity,
        share_capital=share_capital,
        reserves=reserves,
        retained_earnings_prior=retained_prior,
        current_year_earnings=current_earnings,
        non_current_liabilities=non_current_liabilities,
        long_term_debt=long_term_debt,
        long_term_provisions=long_term_prov,
        current_liabilities=current_liabilities,
        short_term_debt=short_term_debt,
        accounts_payable=accounts_payable,
        tax_and_social_liabilities=tax_social_liab,
        other_current_liabilities=other_curr_liab,
        revenue=revenue,
        sold_production=sold_production,
        other_operating_revenue=other_op_revenue,
        cost_of_goods_sold=cost_goods_sold,
        external_expenses=external_expenses,
        personnel_expenses=personnel_expenses,
        taxes_and_duties=taxes_and_duties,
        depreciation_and_amortization=depreciation_amort,
        operating_income=operating_income,
        financial_revenue=financial_revenue,
        financial_expenses=financial_expenses,
        financial_income=financial_income,
        income_before_tax=income_before_tax,
        extraordinary_income=extraordinary_inc,
        income_tax=income_tax,
        net_income=net_income,
        ebitda=ebitda,
        operating_cash_flow=op_cash_flow,
        investing_cash_flow=inv_cash_flow,
        financing_cash_flow=fin_cash_flow,
        change_in_cash=change_in_cash,
        beginning_cash=beginning_cash,
        ending_cash=ending_cash,
        headcount=headcount,
        backlog_value=backlog_value,
        capex=capex,
        is_consolidated=raw.is_consolidated,
        adjustments_count=len(adjustments),
        normalized_json=normalized_json
    )
