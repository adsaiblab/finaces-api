"""
Nested financial statement schemas (T06).

The DB stays flat (SQLAlchemy), but API input/output uses nested structures
for clarity and frontend alignment.
"""
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from decimal import Decimal
from datetime import datetime
from uuid import UUID


# ═══════════════════════════════════════════════════════════
# Nested sub-schemas
# ═══════════════════════════════════════════════════════════

class BalanceSheetAssets(BaseModel):
    total_assets: Optional[Decimal] = None
    current_assets: Optional[Decimal] = None
    liquid_assets: Decimal
    inventory: Decimal = Decimal("0.0")
    other_noncurrent_assets: Decimal = Decimal("0.0")
    # New fields aligned with SQL
    non_current_assets: Optional[Decimal] = Decimal("0.0")
    intangible_assets: Optional[Decimal] = Decimal("0.0")
    tangible_assets: Optional[Decimal] = Decimal("0.0")
    financial_assets: Optional[Decimal] = Decimal("0.0")
    accounts_receivable: Optional[Decimal] = Decimal("0.0")
    other_current_assets: Optional[Decimal] = Decimal("0.0")


class BalanceSheetLiabilities(BaseModel):
    total_liabilities: Optional[Decimal] = None
    current_liabilities: Optional[Decimal] = None
    long_term_debt: Decimal
    equity: Optional[Decimal] = None
    # New fields aligned with SQL
    share_capital: Optional[Decimal] = Decimal("0.0")
    reserves: Optional[Decimal] = Decimal("0.0")
    retained_earnings_prior: Optional[Decimal] = Decimal("0.0")
    current_year_earnings: Optional[Decimal] = Decimal("0.0")
    short_term_debt: Optional[Decimal] = Decimal("0.0")
    accounts_payable: Optional[Decimal] = Decimal("0.0")
    tax_and_social_liabilities: Optional[Decimal] = Decimal("0.0")
    other_current_liabilities: Optional[Decimal] = Decimal("0.0")
    long_term_provisions: Optional[Decimal] = Decimal("0.0")
    non_current_liabilities: Optional[Decimal] = Decimal("0.0")


class IncomeStatement(BaseModel):
    revenue: Decimal
    gross_profit: Decimal = Decimal("0.0")
    operating_income: Optional[Decimal] = None
    ebitda: Optional[Decimal] = None
    net_income: Optional[Decimal] = None
    extraordinary_expenses: Decimal = Decimal("0.0")
    dividends: Decimal = Decimal("0.0")
    # New fields aligned with SQL
    sold_production: Optional[Decimal] = Decimal("0.0")
    other_operating_revenue: Optional[Decimal] = Decimal("0.0")
    cost_of_goods_sold: Optional[Decimal] = Decimal("0.0")
    external_expenses: Optional[Decimal] = Decimal("0.0")
    personnel_expenses: Optional[Decimal] = Decimal("0.0")
    taxes_and_duties: Optional[Decimal] = Decimal("0.0")
    depreciation_and_amortization: Optional[Decimal] = Decimal("0.0")
    other_operating_expenses: Optional[Decimal] = Decimal("0.0")
    financial_revenue: Optional[Decimal] = Decimal("0.0")
    financial_expenses: Optional[Decimal] = Decimal("0.0")
    financial_income: Optional[Decimal] = Decimal("0.0")
    income_before_tax: Optional[Decimal] = Decimal("0.0")
    extraordinary_income: Optional[Decimal] = Decimal("0.0")
    income_tax: Optional[Decimal] = Decimal("0.0")


class CashFlow(BaseModel):
    operating_cash_flow: Decimal
    investing_cash_flow: Decimal = Decimal("0.0")
    financing_cash_flow: Decimal = Decimal("0.0")
    free_cash_flow: Decimal = Decimal("0.0")
    # New fields aligned with SQL
    change_in_cash: Optional[Decimal] = Decimal("0.0")
    beginning_cash: Optional[Decimal] = Decimal("0.0")
    ending_cash: Optional[Decimal] = Decimal("0.0")
    capex: Optional[Decimal] = Decimal("0.0")


# ═══════════════════════════════════════════════════════════
# Create (nested input)
# ═══════════════════════════════════════════════════════════

class FinancialStatementNestedCreate(BaseModel):
    fiscal_year: int = Field(..., ge=1900, le=2100)
    currency_original: str = Field("USD", min_length=3, max_length=3)  # ISO 4217
    exchange_rate_to_usd: Decimal = Field(default=Decimal("1.0"), ge=Decimal("0.0"))
    referentiel: str = Field("IFRS", min_length=1, max_length=10)
    is_consolidated: bool = False
    balance_sheet_assets: BalanceSheetAssets
    balance_sheet_liabilities: BalanceSheetLiabilities
    income_statement: IncomeStatement
    cash_flow: CashFlow
    # Metadata fields from SQL
    headcount: Optional[int] = None
    backlog_value: Optional[Decimal] = Decimal("0.0")
    source_notes: Optional[str] = None

    def to_flat_dict(self) -> dict:
        """Flattens nested structure into a dict matching DB columns."""
        bsa = self.balance_sheet_assets
        bsl = self.balance_sheet_liabilities
        inc = self.income_statement
        cf = self.cash_flow
        return {
            "fiscal_year": self.fiscal_year,
            "currency_original": self.currency_original,
            "exchange_rate_to_usd": self.exchange_rate_to_usd,
            "referentiel": self.referentiel,
            "is_consolidated": 1 if self.is_consolidated else 0,
            "headcount": self.headcount,
            "backlog_value": self.backlog_value,
            "source_notes": self.source_notes,
            # Assets
            "total_assets": bsa.total_assets,
            "current_assets": bsa.current_assets,
            "liquid_assets": bsa.liquid_assets,
            "inventory": bsa.inventory,
            "other_noncurrent_assets": bsa.other_noncurrent_assets,
            "non_current_assets": bsa.non_current_assets,
            "intangible_assets": bsa.intangible_assets,
            "tangible_assets": bsa.tangible_assets,
            "financial_assets": bsa.financial_assets,
            "accounts_receivable": bsa.accounts_receivable,
            "other_current_assets": bsa.other_current_assets,
            # Liabilities
            "total_liabilities_and_equity": bsl.total_liabilities,
            "current_liabilities": bsl.current_liabilities,
            "long_term_debt": bsl.long_term_debt,
            "equity": bsl.equity,
            "share_capital": bsl.share_capital,
            "reserves": bsl.reserves,
            "retained_earnings_prior": bsl.retained_earnings_prior,
            "current_year_earnings": bsl.current_year_earnings,
            "short_term_debt": bsl.short_term_debt,
            "accounts_payable": bsl.accounts_payable,
            "tax_and_social_liabilities": bsl.tax_and_social_liabilities,
            "other_current_liabilities": bsl.other_current_liabilities,
            "long_term_provisions": bsl.long_term_provisions,
            "non_current_liabilities": bsl.non_current_liabilities,
            # Income
            "revenue": inc.revenue,
            "gross_profit": inc.gross_profit,
            "operating_income": inc.operating_income,
            "ebitda": inc.ebitda,
            "net_income": inc.net_income,
            "extraordinary_expenses": inc.extraordinary_expenses,
            "dividends_distributed": inc.dividends,
            "sold_production": inc.sold_production,
            "other_operating_revenue": inc.other_operating_revenue,
            "cost_of_goods_sold": inc.cost_of_goods_sold,
            "external_expenses": inc.external_expenses,
            "personnel_expenses": inc.personnel_expenses,
            "taxes_and_duties": inc.taxes_and_duties,
            "depreciation_and_amortization": inc.depreciation_and_amortization,
            "other_operating_expenses": inc.other_operating_expenses,
            "financial_revenue": inc.financial_revenue,
            "financial_expenses": inc.financial_expenses,
            "financial_income": inc.financial_income,
            "income_before_tax": inc.income_before_tax,
            "extraordinary_income": inc.extraordinary_income,
            "income_tax": inc.income_tax,
            # Cash flow
            "operating_cash_flow": cf.operating_cash_flow,
            "investing_cash_flow": cf.investing_cash_flow,
            "financing_cash_flow": cf.financing_cash_flow,
            "free_cash_flow": cf.free_cash_flow,
            "change_in_cash": cf.change_in_cash,
            "beginning_cash": cf.beginning_cash,
            "ending_cash": cf.ending_cash,
            "capex": cf.capex,
        }


# ═══════════════════════════════════════════════════════════
# Output (nested response)
# ═══════════════════════════════════════════════════════════

class FinancialStatementNestedOut(BaseModel):
    id: str
    case_id: str
    fiscal_year: int
    currency_original: str
    exchange_rate_to_usd: Decimal
    referentiel: Optional[str] = None
    is_consolidated: bool
    balance_sheet_assets: BalanceSheetAssets
    balance_sheet_liabilities: BalanceSheetLiabilities
    income_statement: IncomeStatement
    cash_flow: CashFlow
    # Metadata
    headcount: Optional[int] = None
    backlog_value: Optional[Decimal] = Decimal("0.0")
    source_notes: Optional[str] = None
    created_at: datetime

    @classmethod
    def from_orm_flat(cls, orm_obj) -> "FinancialStatementNestedOut":
        """Converts flat ORM object to nested Pydantic schema."""
        return cls(
            id=str(orm_obj.id),
            case_id=str(orm_obj.case_id),
            fiscal_year=orm_obj.fiscal_year,
            currency_original=orm_obj.currency_original or "USD",
            exchange_rate_to_usd=orm_obj.exchange_rate_to_usd or Decimal("1.0"),
            referentiel=str(orm_obj.referentiel.value) if hasattr(orm_obj.referentiel, 'value') else str(orm_obj.referentiel) if orm_obj.referentiel else None,
            is_consolidated=bool(orm_obj.is_consolidated),
            headcount=orm_obj.headcount,
            backlog_value=orm_obj.backlog_value or Decimal("0.0"),
            source_notes=orm_obj.source_notes,
            balance_sheet_assets=BalanceSheetAssets(
                total_assets=orm_obj.total_assets or Decimal("0.0"),
                current_assets=orm_obj.current_assets or Decimal("0.0"),
                liquid_assets=orm_obj.liquid_assets or Decimal("0.0"),
                inventory=orm_obj.inventory or Decimal("0.0"),
                other_noncurrent_assets=orm_obj.other_noncurrent_assets or Decimal("0.0"),
                non_current_assets=orm_obj.non_current_assets or Decimal("0.0"),
                intangible_assets=orm_obj.intangible_assets or Decimal("0.0"),
                tangible_assets=orm_obj.tangible_assets or Decimal("0.0"),
                financial_assets=orm_obj.financial_assets or Decimal("0.0"),
                accounts_receivable=orm_obj.accounts_receivable or Decimal("0.0"),
                other_current_assets=orm_obj.other_current_assets or Decimal("0.0"),
            ),
            balance_sheet_liabilities=BalanceSheetLiabilities(
                total_liabilities=orm_obj.total_liabilities_and_equity or Decimal("0.0"),
                current_liabilities=orm_obj.current_liabilities or Decimal("0.0"),
                long_term_debt=orm_obj.long_term_debt or Decimal("0.0"),
                equity=orm_obj.equity or Decimal("0.0"),
                share_capital=orm_obj.share_capital or Decimal("0.0"),
                reserves=orm_obj.reserves or Decimal("0.0"),
                retained_earnings_prior=orm_obj.retained_earnings_prior or Decimal("0.0"),
                current_year_earnings=orm_obj.current_year_earnings or Decimal("0.0"),
                short_term_debt=orm_obj.short_term_debt or Decimal("0.0"),
                accounts_payable=orm_obj.accounts_payable or Decimal("0.0"),
                tax_and_social_liabilities=orm_obj.tax_and_social_liabilities or Decimal("0.0"),
                other_current_liabilities=orm_obj.other_current_liabilities or Decimal("0.0"),
                long_term_provisions=orm_obj.long_term_provisions or Decimal("0.0"),
                non_current_liabilities=orm_obj.non_current_liabilities or Decimal("0.0"),
            ),
            income_statement=IncomeStatement(
                revenue=orm_obj.revenue or Decimal("0.0"),
                gross_profit=orm_obj.gross_profit or Decimal("0.0"),
                operating_income=orm_obj.operating_income or Decimal("0.0"),
                ebitda=orm_obj.ebitda or Decimal("0.0"),
                net_income=orm_obj.net_income or Decimal("0.0"),
                extraordinary_expenses=orm_obj.extraordinary_expenses or Decimal("0.0"),
                dividends=orm_obj.dividends_distributed or Decimal("0.0"),
                sold_production=orm_obj.sold_production or Decimal("0.0"),
                other_operating_revenue=orm_obj.other_operating_revenue or Decimal("0.0"),
                cost_of_goods_sold=orm_obj.cost_of_goods_sold or Decimal("0.0"),
                external_expenses=orm_obj.external_expenses or Decimal("0.0"),
                personnel_expenses=orm_obj.personnel_expenses or Decimal("0.0"),
                taxes_and_duties=orm_obj.taxes_and_duties or Decimal("0.0"),
                depreciation_and_amortization=orm_obj.depreciation_and_amortization or Decimal("0.0"),
                other_operating_expenses=orm_obj.other_operating_expenses or Decimal("0.0"),
                financial_revenue=orm_obj.financial_revenue or Decimal("0.0"),
                financial_expenses=orm_obj.financial_expenses or Decimal("0.0"),
                financial_income=orm_obj.financial_income or Decimal("0.0"),
                income_before_tax=orm_obj.income_before_tax or Decimal("0.0"),
                extraordinary_income=orm_obj.extraordinary_income or Decimal("0.0"),
                income_tax=orm_obj.income_tax or Decimal("0.0"),
            ),
            cash_flow=CashFlow(
                operating_cash_flow=orm_obj.operating_cash_flow or Decimal("0.0"),
                investing_cash_flow=orm_obj.investing_cash_flow or Decimal("0.0"),
                financing_cash_flow=orm_obj.financing_cash_flow or Decimal("0.0"),
                free_cash_flow=orm_obj.free_cash_flow or Decimal("0.0"),
                change_in_cash=orm_obj.change_in_cash or Decimal("0.0"),
                beginning_cash=orm_obj.beginning_cash or Decimal("0.0"),
                ending_cash=orm_obj.ending_cash or Decimal("0.0"),
                capex=orm_obj.capex or Decimal("0.0"),
            ),
            created_at=orm_obj.created_at,
        )
