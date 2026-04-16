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
    Phase 3 — Pure normalization engine.
    READS pre-calculated aggregates from Raw (guaranteed by Phase 2).
    APPLIES exchange rate conversion to USD.
    APPLIES IFRS/sector adjustments.
    Does NOT recalculate basic arithmetic — that is Phase 2's responsibility.
    """
    ar = AdjustedRawState(raw, adjustments)
    fx = raw.exchange_rate_to_usd or Decimal("1.0")
    if fx <= 0:
        raise EngineComputationError(f"exchange_rate_to_usd invalide : {fx}")

    def to_usd(val: Optional[Decimal]) -> Optional[Decimal]:
        """Convert a Raw value to USD using exchange rate. Returns None if val is None."""
        if val is None:
            return None
        return (val / fx).quantize(Decimal("0.01"))

    # ── 1. EXTRACTION EN DEVISE LOCALE (Avec Fallbacks basiques) ──
    liquid_assets_original = ar.get("liquid_assets")
    inventory_original = ar.get("inventory")
    accounts_receivable_original = ar.get("accounts_receivable")
    other_current_assets_original = ar.get("other_current_assets")
    current_assets_original = ar.get("current_assets") or _safe_sum(liquid_assets_original, inventory_original, accounts_receivable_original, other_current_assets_original)

    intangible_assets_original = ar.get("intangible_assets")
    tangible_assets_original = ar.get("tangible_assets")
    financial_assets_original = ar.get("financial_assets")
    other_noncurrent_assets_original = ar.get("other_noncurrent_assets")
    non_current_assets_original = ar.get("non_current_assets") or _safe_sum(intangible_assets_original, tangible_assets_original, financial_assets_original, other_noncurrent_assets_original)

    total_assets_original = ar.get("total_assets") or _safe_sum(current_assets_original, non_current_assets_original)

    share_capital_original = ar.get("share_capital")
    reserves_original = ar.get("reserves")
    retained_earnings_prior_original = ar.get("retained_earnings_prior")
    current_year_earnings_original = ar.get("current_year_earnings")
    equity_original = ar.get("equity") or _safe_sum(share_capital_original, reserves_original, retained_earnings_prior_original, current_year_earnings_original)

    long_term_debt_original = ar.get("long_term_debt")
    long_term_provisions_original = ar.get("long_term_provisions")
    non_current_liabilities_original = ar.get("non_current_liabilities") or _safe_sum(long_term_debt_original, long_term_provisions_original)

    short_term_debt_original = ar.get("short_term_debt")
    accounts_payable_original = ar.get("accounts_payable")
    tax_and_social_liabilities_original = ar.get("tax_and_social_liabilities")
    other_current_liabilities_original = ar.get("other_current_liabilities")
    current_liabilities_original = ar.get("current_liabilities") or _safe_sum(short_term_debt_original, accounts_payable_original, tax_and_social_liabilities_original, other_current_liabilities_original)

    total_liabilities_and_equity_original = ar.get("total_liabilities_and_equity") or _safe_sum(equity_original, non_current_liabilities_original, current_liabilities_original)

    revenue_original = ar.get("revenue")
    sold_production_original = ar.get("sold_production")
    other_operating_revenue_original = ar.get("other_operating_revenue")
    cost_of_goods_sold_original = ar.get("cost_of_goods_sold")
    external_expenses_original = ar.get("external_expenses")
    personnel_expenses_original = ar.get("personnel_expenses")
    taxes_and_duties_original = ar.get("taxes_and_duties")
    depreciation_and_amortization_original = ar.get("depreciation_and_amortization")
    operating_income_original = ar.get("operating_income")
    financial_revenue_original = ar.get("financial_revenue")
    financial_expenses_original = ar.get("financial_expenses")
    financial_income_original = ar.get("financial_income")
    income_before_tax_original = ar.get("income_before_tax")
    extraordinary_income_original = ar.get("extraordinary_income")
    income_tax_original = ar.get("income_tax")
    net_income_original = ar.get("net_income")
    ebitda_original = ar.get("ebitda")

    operating_cash_flow_original = ar.get("operating_cash_flow")
    investing_cash_flow_original = ar.get("investing_cash_flow")
    financing_cash_flow_original = ar.get("financing_cash_flow")
    beginning_cash_original = ar.get("beginning_cash")
    ending_cash_original = ar.get("ending_cash")
    change_in_cash_original = ar.get("change_in_cash")
    capex_original = ar.get("capex")
    backlog_value_original = ar.get("backlog_value")
    headcount = ar.get("headcount")

    if operating_cash_flow_original is None and net_income_original is not None and depreciation_and_amortization_original is not None:
        operating_cash_flow_original = net_income_original + depreciation_and_amortization_original

    # ── 2. CONVERSION USD ──
    liquid_assets = to_usd(liquid_assets_original)
    inventory = to_usd(inventory_original)
    accounts_receivable = to_usd(accounts_receivable_original)
    other_current_assets = to_usd(other_current_assets_original)
    current_assets = to_usd(current_assets_original)
    intangible_assets = to_usd(intangible_assets_original)
    tangible_assets = to_usd(tangible_assets_original)
    financial_assets = to_usd(financial_assets_original)
    other_noncurrent_assets = to_usd(other_noncurrent_assets_original)
    non_current_assets = to_usd(non_current_assets_original)
    total_assets = to_usd(total_assets_original)
    share_capital = to_usd(share_capital_original)
    reserves = to_usd(reserves_original)
    retained_earnings_prior = to_usd(retained_earnings_prior_original)
    current_year_earnings = to_usd(current_year_earnings_original)
    equity = to_usd(equity_original)
    long_term_debt = to_usd(long_term_debt_original)
    long_term_provisions = to_usd(long_term_provisions_original)
    non_current_liabilities = to_usd(non_current_liabilities_original)
    short_term_debt = to_usd(short_term_debt_original)
    accounts_payable = to_usd(accounts_payable_original)
    tax_and_social_liabilities = to_usd(tax_and_social_liabilities_original)
    other_current_liabilities = to_usd(other_current_liabilities_original)
    current_liabilities = to_usd(current_liabilities_original)
    total_liabilities_and_equity = to_usd(total_liabilities_and_equity_original)
    revenue = to_usd(revenue_original)
    sold_production = to_usd(sold_production_original)
    other_operating_revenue = to_usd(other_operating_revenue_original)
    cost_of_goods_sold = to_usd(cost_of_goods_sold_original)
    external_expenses = to_usd(external_expenses_original)
    personnel_expenses = to_usd(personnel_expenses_original)
    taxes_and_duties = to_usd(taxes_and_duties_original)
    depreciation_and_amortization = to_usd(depreciation_and_amortization_original)
    operating_income = to_usd(operating_income_original)
    financial_revenue = to_usd(financial_revenue_original)
    financial_expenses = to_usd(financial_expenses_original)
    financial_income = to_usd(financial_income_original)
    income_before_tax = to_usd(income_before_tax_original)
    extraordinary_income = to_usd(extraordinary_income_original)
    income_tax = to_usd(income_tax_original)
    net_income = to_usd(net_income_original)
    ebitda = to_usd(ebitda_original)
    operating_cash_flow = to_usd(operating_cash_flow_original)
    investing_cash_flow = to_usd(investing_cash_flow_original)
    financing_cash_flow = to_usd(financing_cash_flow_original)
    beginning_cash = to_usd(beginning_cash_original)
    ending_cash = to_usd(ending_cash_original)
    change_in_cash = to_usd(change_in_cash_original)
    capex = to_usd(capex_original)
    backlog_value = to_usd(backlog_value_original)

    # ── 3. BUSINESS LOGIC VALIDATION (Post-FX) ──
    if total_assets is not None and total_liabilities_and_equity is not None:
        max_val = max(total_assets, total_liabilities_and_equity)
        if max_val > Decimal("0.0"):
            diff_pct = abs(total_assets - total_liabilities_and_equity) / max_val
            # On vérifie sur la base USD !
            if diff_pct > Decimal("0.01"):
                raise EngineComputationError(
                    message=f"Unbalanced balance sheet by {float(diff_pct):.1%}. Submission locked.",
                    details={"error_code": "UNBALANCED_BALANCE_SHEET"}
                )

    # ── 4. JSON GENERATION (Post-FX) ──
    normalized_json = _build_normalized_json(raw, {
        "liquid_assets": liquid_assets,
        "inventory": inventory,
        "accounts_receivable": accounts_receivable,
        "other_current_assets": other_current_assets,
        "current_assets": current_assets,
        "intangible_assets": intangible_assets,
        "tangible_assets": tangible_assets,
        "financial_assets": financial_assets,
        "other_noncurrent_assets": other_noncurrent_assets,
        "non_current_assets": non_current_assets,
        "total_assets": total_assets,
        "share_capital": share_capital,
        "reserves": reserves,
        "retained_earnings_prior": retained_earnings_prior,
        "current_year_earnings": current_year_earnings,
        "equity": equity,
        "long_term_debt": long_term_debt,
        "long_term_provisions": long_term_provisions,
        "non_current_liabilities": non_current_liabilities,
        "short_term_debt": short_term_debt,
        "accounts_payable": accounts_payable,
        "tax_and_social_liabilities": tax_and_social_liabilities,
        "other_current_liabilities": other_current_liabilities,
        "current_liabilities": current_liabilities,
        "total_liabilities_and_equity": total_liabilities_and_equity,
        "revenue": revenue,
        "sold_production": sold_production,
        "other_operating_revenue": other_operating_revenue,
        "cost_of_goods_sold": cost_of_goods_sold,
        "external_expenses": external_expenses,
        "personnel_expenses": personnel_expenses,
        "taxes_and_duties": taxes_and_duties,
        "depreciation_and_amortization": depreciation_and_amortization,
        "operating_income": operating_income,
        "financial_revenue": financial_revenue,
        "financial_expenses": financial_expenses,
        "financial_income": financial_income,
        "income_before_tax": income_before_tax,
        "extraordinary_income": extraordinary_income,
        "income_tax": income_tax,
        "net_income": net_income,
        "ebitda": ebitda,
        "operating_cash_flow": operating_cash_flow,
        "investing_cash_flow": investing_cash_flow,
        "financing_cash_flow": financing_cash_flow,
    })

    # ── 5. SCHÉMA FINAL ──
    return FinancialStatementNormalizedSchema(
        id=uuid.uuid4(),
        raw_statement_id=raw.id,
        fiscal_year=raw.fiscal_year,
        currency_usd="USD",
        currency_original=raw.currency_original,
        exchange_rate=fx,

        # USD
        liquid_assets=liquid_assets,
        inventory=inventory,
        accounts_receivable=accounts_receivable,
        other_current_assets=other_current_assets,
        current_assets=current_assets,
        intangible_assets=intangible_assets,
        tangible_assets=tangible_assets,
        financial_assets=financial_assets,
        other_noncurrent_assets=other_noncurrent_assets,
        non_current_assets=non_current_assets,
        total_assets=total_assets,
        share_capital=share_capital,
        reserves=reserves,
        retained_earnings_prior=retained_earnings_prior,
        current_year_earnings=current_year_earnings,
        equity=equity,
        long_term_debt=long_term_debt,
        long_term_provisions=long_term_provisions,
        non_current_liabilities=non_current_liabilities,
        short_term_debt=short_term_debt,
        accounts_payable=accounts_payable,
        tax_and_social_liabilities=tax_and_social_liabilities,
        other_current_liabilities=other_current_liabilities,
        current_liabilities=current_liabilities,
        total_liabilities_and_equity=total_liabilities_and_equity,
        revenue=revenue,
        sold_production=sold_production,
        other_operating_revenue=other_operating_revenue,
        cost_of_goods_sold=cost_of_goods_sold,
        external_expenses=external_expenses,
        personnel_expenses=personnel_expenses,
        taxes_and_duties=taxes_and_duties,
        depreciation_and_amortization=depreciation_and_amortization,
        operating_income=operating_income,
        financial_revenue=financial_revenue,
        financial_expenses=financial_expenses,
        financial_income=financial_income,
        income_before_tax=income_before_tax,
        extraordinary_income=extraordinary_income,
        income_tax=income_tax,
        net_income=net_income,
        ebitda=ebitda,
        operating_cash_flow=operating_cash_flow,
        investing_cash_flow=investing_cash_flow,
        financing_cash_flow=financing_cash_flow,
        beginning_cash=beginning_cash,
        ending_cash=ending_cash,
        change_in_cash=change_in_cash,
        capex=capex,
        backlog_value=backlog_value,

        # ORIGINAL
        liquid_assets_original=liquid_assets_original,
        inventory_original=inventory_original,
        accounts_receivable_original=accounts_receivable_original,
        other_current_assets_original=other_current_assets_original,
        current_assets_original=current_assets_original,
        intangible_assets_original=intangible_assets_original,
        tangible_assets_original=tangible_assets_original,
        financial_assets_original=financial_assets_original,
        other_noncurrent_assets_original=other_noncurrent_assets_original,
        non_current_assets_original=non_current_assets_original,
        total_assets_original=total_assets_original,
        share_capital_original=share_capital_original,
        reserves_original=reserves_original,
        retained_earnings_prior_original=retained_earnings_prior_original,
        current_year_earnings_original=current_year_earnings_original,
        equity_original=equity_original,
        long_term_debt_original=long_term_debt_original,
        long_term_provisions_original=long_term_provisions_original,
        non_current_liabilities_original=non_current_liabilities_original,
        short_term_debt_original=short_term_debt_original,
        accounts_payable_original=accounts_payable_original,
        tax_and_social_liabilities_original=tax_and_social_liabilities_original,
        other_current_liabilities_original=other_current_liabilities_original,
        current_liabilities_original=current_liabilities_original,
        total_liabilities_and_equity_original=total_liabilities_and_equity_original,
        revenue_original=revenue_original,
        sold_production_original=sold_production_original,
        other_operating_revenue_original=other_operating_revenue_original,
        cost_of_goods_sold_original=cost_of_goods_sold_original,
        external_expenses_original=external_expenses_original,
        personnel_expenses_original=personnel_expenses_original,
        taxes_and_duties_original=taxes_and_duties_original,
        depreciation_and_amortization_original=depreciation_and_amortization_original,
        operating_income_original=operating_income_original,
        financial_revenue_original=financial_revenue_original,
        financial_expenses_original=financial_expenses_original,
        financial_income_original=financial_income_original,
        income_before_tax_original=income_before_tax_original,
        extraordinary_income_original=extraordinary_income_original,
        income_tax_original=income_tax_original,
        net_income_original=net_income_original,
        ebitda_original=ebitda_original,
        operating_cash_flow_original=operating_cash_flow_original,
        investing_cash_flow_original=investing_cash_flow_original,
        financing_cash_flow_original=financing_cash_flow_original,
        beginning_cash_original=beginning_cash_original,
        ending_cash_original=ending_cash_original,
        change_in_cash_original=change_in_cash_original,
        capex_original=capex_original,
        backlog_value_original=backlog_value_original,

        # META
        headcount=headcount,
        is_consolidated=raw.is_consolidated,
        adjustments_count=len(adjustments),
        normalized_json=normalized_json
    )
