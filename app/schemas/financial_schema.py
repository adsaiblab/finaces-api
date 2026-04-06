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
    total_assets: Decimal
    current_assets: Decimal
    liquid_assets: Decimal
    inventory: Decimal = Decimal("0.0")
    other_noncurrent_assets: Decimal = Decimal("0.0")


class BalanceSheetLiabilities(BaseModel):
    total_liabilities: Decimal
    current_liabilities: Decimal
    long_term_debt: Decimal
    equity: Decimal


class IncomeStatement(BaseModel):
    revenue: Decimal
    gross_profit: Decimal = Decimal("0.0")
    operating_income: Decimal
    ebitda: Decimal
    net_income: Decimal
    extraordinary_expenses: Decimal = Decimal("0.0")
    dividends: Decimal = Decimal("0.0")


class CashFlow(BaseModel):
    operating_cash_flow: Decimal
    investing_cash_flow: Decimal = Decimal("0.0")
    financing_cash_flow: Decimal = Decimal("0.0")
    free_cash_flow: Decimal = Decimal("0.0")


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
            # Assets
            "total_assets": bsa.total_assets,
            "current_assets": bsa.current_assets,
            "liquid_assets": bsa.liquid_assets,
            "inventory": bsa.inventory,
            "other_noncurrent_assets": bsa.other_noncurrent_assets,
            # Liabilities
            "total_liabilities_and_equity": bsl.total_liabilities,
            "current_liabilities": bsl.current_liabilities,
            "long_term_debt": bsl.long_term_debt,
            "equity": bsl.equity,
            # Income
            "revenue": inc.revenue,
            "gross_profit": inc.gross_profit,
            "operating_income": inc.operating_income,
            "ebitda": inc.ebitda,
            "net_income": inc.net_income,
            "extraordinary_expenses": inc.extraordinary_expenses,
            "dividends_distributed": inc.dividends,
            # Cash flow
            "operating_cash_flow": cf.operating_cash_flow,
            "investing_cash_flow": cf.investing_cash_flow,
            "financing_cash_flow": cf.financing_cash_flow,
            "free_cash_flow": cf.free_cash_flow,
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
            referentiel=str(orm_obj.referentiel.value) if orm_obj.referentiel else None,
            is_consolidated=bool(orm_obj.is_consolidated),
            balance_sheet_assets=BalanceSheetAssets(
                total_assets=orm_obj.total_assets or Decimal("0.0"),
                current_assets=orm_obj.current_assets or Decimal("0.0"),
                liquid_assets=orm_obj.liquid_assets or Decimal("0.0"),
                inventory=orm_obj.inventory or Decimal("0.0"),
                other_noncurrent_assets=orm_obj.other_noncurrent_assets or Decimal("0.0"),
            ),
            balance_sheet_liabilities=BalanceSheetLiabilities(
                total_liabilities=orm_obj.total_liabilities_and_equity or Decimal("0.0"),
                current_liabilities=orm_obj.current_liabilities or Decimal("0.0"),
                long_term_debt=orm_obj.long_term_debt or Decimal("0.0"),
                equity=orm_obj.equity or Decimal("0.0"),
            ),
            income_statement=IncomeStatement(
                revenue=orm_obj.revenue or Decimal("0.0"),
                gross_profit=orm_obj.gross_profit or Decimal("0.0"),
                operating_income=orm_obj.operating_income or Decimal("0.0"),
                ebitda=orm_obj.ebitda or Decimal("0.0"),
                net_income=orm_obj.net_income or Decimal("0.0"),
                extraordinary_expenses=orm_obj.extraordinary_expenses or Decimal("0.0"),
                dividends=orm_obj.dividends_distributed or Decimal("0.0"),
            ),
            cash_flow=CashFlow(
                operating_cash_flow=orm_obj.operating_cash_flow or Decimal("0.0"),
                investing_cash_flow=orm_obj.investing_cash_flow or Decimal("0.0"),
                financing_cash_flow=orm_obj.financing_cash_flow or Decimal("0.0"),
                free_cash_flow=orm_obj.free_cash_flow or Decimal("0.0"),
            ),
            created_at=orm_obj.created_at,
        )
