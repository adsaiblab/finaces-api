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
    Takes a Raw Pydantic Schema and a list of Adjustments Pydantic Schema.
    Returns a Normalized Pydantic Schema ready to be manipulated or stored.
    No Database injection. No HTTP logic.
    """
    
    ar = AdjustedRawState(raw, adjustments)

    # ── Bottom-up L1 reconstruction with Adjustments ────────────────────

    # Assets
    liquid_assets = ar.get("liquid_assets") or Decimal("0.0")
    
    ai_base = ar.get("non_current_assets")
    if ai_base is None:
        ai_base = _safe_sum(ar.get("tangible_assets"), ar.get("intangible_assets"), ar.get("financial_assets"))
    non_current_assets = ai_base or Decimal("0.0")
    
    ac_base = ar.get("current_assets")
    if ac_base is None:
        ac_base = _safe_sum(liquid_assets, ar.get("inventory"), ar.get("accounts_receivable"), ar.get("other_current_assets"))
    current_assets = ac_base or Decimal("0.0")
    
    at_base = ar.get("total_assets")
    if at_base is None:
        at_base = _safe_sum(current_assets, non_current_assets)
    total_assets = at_base or Decimal("0.0")

    # Liabilities
    equity = ar.get("equity") or Decimal("0.0")

    pct_base = ar.get("current_liabilities")
    if pct_base is None:
        pct_base = _safe_sum(ar.get("short_term_debt"), ar.get("accounts_payable"), ar.get("tax_and_social_liabilities"), ar.get("other_current_liabilities"))
    current_liabilities = pct_base or Decimal("0.0")

    plt_base = ar.get("non_current_liabilities")
    if plt_base is None:
        plt_base = _safe_sum(ar.get("long_term_debt"), ar.get("long_term_provisions"))
    non_current_liabilities = plt_base or Decimal("0.0")

    pt_base = ar.get("total_liabilities_and_equity")
    if pt_base is None:
        pt_base = _safe_sum(equity, non_current_liabilities, current_liabilities)
    total_liabilities_and_equity = pt_base or Decimal("0.0")

    # Income Statement
    ca_base = ar.get("revenue")
    if ca_base is None:
        ca_base = ar.get("sold_production")
    revenue = ca_base or Decimal("0.0")

    net_income = ar.get("net_income") or Decimal("0.0")

    ebitda = ar.get("ebitda")
    if ebitda is None:
        ebit = ar.get("operating_income")
        dap  = ar.get("depreciation_and_amortization")
        if ebit is not None and dap is not None:
            ebitda = ebit + dap
    ebitda = ebitda or Decimal("0.0")

    cfo = ar.get("operating_cash_flow")
    if cfo is None and ar.get("net_income") is not None and ar.get("depreciation_and_amortization") is not None:
        cfo = ar.get("net_income") + ar.get("depreciation_and_amortization")
        var_bfr = ar.get("change_in_working_capital")
        if var_bfr is not None:
            cfo -= var_bfr
    cfo = cfo or Decimal("0.0")

    # ── BUSINESS LOGIC VALIDATION ────────────────────────────────
    
    if total_assets and total_liabilities_and_equity:
        diff_pct = _safe_divide(abs(total_assets - total_liabilities_and_equity), max(total_assets, total_liabilities_and_equity))
        if diff_pct and diff_pct > Decimal("0.01"):
            raise EngineComputationError(
                message=f"Unbalanced balance sheet by {float(diff_pct):.1%}. Submission locked.", 
                details={"error_code": "UNBALANCED_BALANCE_SHEET"}
            )

    # ── JSON GENERATION FOR WORKSHEET ─────────────────────────
    
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
        "operating_cash_flow": cfo,
    })

    # Return populated schema
    return FinancialStatementNormalizedSchema(
        id=uuid.uuid4(),
        raw_statement_id=raw.id,
        fiscal_year=raw.fiscal_year,
        exchange_rate=raw.exchange_rate_to_usd,
        
        total_assets=total_assets,
        current_assets=current_assets,
        liquid_assets=liquid_assets,
        non_current_assets=non_current_assets,
        
        total_liabilities_and_equity=total_liabilities_and_equity,
        current_liabilities=current_liabilities,
        non_current_liabilities=non_current_liabilities,
        equity=equity,
        
        revenue=revenue,
        net_income=net_income,
        ebitda=ebitda,
        operating_cash_flow=cfo,
        
        is_consolidated=raw.is_consolidated,
        adjustments_count=len(adjustments),
        normalized_json=normalized_json
    )
