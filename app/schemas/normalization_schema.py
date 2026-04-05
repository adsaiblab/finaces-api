from pydantic import BaseModel, ConfigDict, Field, model_validator
from decimal import Decimal
from typing import Optional, Literal, Annotated
from datetime import datetime
from uuid import UUID

class AdjustmentSchema(BaseModel):
    raw_statement_id: UUID
    fiscal_year: int
    adj_type: Literal["RECLASS", "CORRECTION", "ESTIMATE", "CURRENCY", "OTHER"]
    field: str
    amount_before: Decimal = Decimal("0.0")
    amount_after: Decimal = Decimal("0.0")
    mode: Literal['replace', 'add'] = 'add'
    justification: str
    source_ref: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

from datetime import date
from pydantic import field_validator

class FinancialStatementRawSchema(BaseModel):
    """Schema representing the raw statement input expected by the engine."""
    id: UUID
    case_id: UUID
    fiscal_year: int
    statement_end_date: Optional[date] = None  # Pas en DB → calculé via fiscal_year si absent
    currency_original: str
    exchange_rate_to_usd: Decimal = Field(ge=0)
    referentiel: Optional[str] = "IFRS"  # Défaut IFRS si NULL en DB
    is_consolidated: bool = False
    
    # Raw values can potentially be None depending on the dataset
    liquid_assets: Optional[Decimal] = None
    inventory: Optional[Decimal] = None
    accounts_receivable: Optional[Decimal] = None
    other_current_assets: Optional[Decimal] = None
    current_assets: Optional[Decimal] = None
    
    intangible_assets: Optional[Decimal] = None
    tangible_assets: Optional[Decimal] = None
    financial_assets: Optional[Decimal] = None
    non_current_assets: Optional[Decimal] = None
    
    total_assets: Optional[Decimal] = None

    equity: Optional[Decimal] = None
    
    long_term_debt: Optional[Decimal] = None
    long_term_provisions: Optional[Decimal] = None
    non_current_liabilities: Optional[Decimal] = None
    
    short_term_debt: Optional[Decimal] = None
    accounts_payable: Optional[Decimal] = None
    tax_and_social_liabilities: Optional[Decimal] = None
    other_current_liabilities: Optional[Decimal] = None
    current_liabilities: Optional[Decimal] = None
    
    total_liabilities_and_equity: Optional[Decimal] = None

    revenue: Optional[Decimal] = None
    sold_production: Optional[Decimal] = None
    operating_income: Optional[Decimal] = None
    depreciation_and_amortization: Optional[Decimal] = None
    ebitda: Optional[Decimal] = None
    net_income: Optional[Decimal] = None
    operating_cash_flow: Optional[Decimal] = None
    change_in_working_capital: Optional[Decimal] = None

    @field_validator(
        'revenue', 
        'inventory', 
        'total_assets', 
        'liquid_assets',
        mode='before'
    )
    @classmethod
    def prevent_economic_absurdities(cls, v, info):
        if v is not None and Decimal(str(v)) < Decimal("0.0"):
            field_name = info.field_name
            raise ValueError(f"Field {field_name} cannot be strictly negative.")
        return v

    model_config = ConfigDict(from_attributes=True)

class FinancialStatementNormalizedSchema(BaseModel):
    """Schema representing the output of the normalization engine."""
    id: Optional[UUID] = Field(default=None, description="Will be generated if None")
    raw_statement_id: UUID
    fiscal_year: int
    currency_usd: str = "USD"
    exchange_rate: Annotated[Decimal, Field(ge=0)]
    
    # Assets
    total_assets: Decimal
    current_assets: Decimal
    liquid_assets: Decimal
    inventory: Decimal = Decimal("0.0")
    accounts_receivable: Decimal = Decimal("0.0")
    other_current_assets: Decimal = Decimal("0.0")
    non_current_assets: Decimal
    intangible_assets: Decimal = Decimal("0.0")
    tangible_assets: Decimal = Decimal("0.0")
    financial_assets: Decimal = Decimal("0.0")
    
    # Liabilities & Equity
    total_liabilities_and_equity: Decimal
    equity: Decimal
    share_capital: Decimal = Decimal("0.0")
    reserves: Decimal = Decimal("0.0")
    retained_earnings_prior: Decimal = Decimal("0.0")
    current_year_earnings: Decimal = Decimal("0.0")
    non_current_liabilities: Decimal
    long_term_debt: Decimal = Decimal("0.0")
    long_term_provisions: Decimal = Decimal("0.0")
    current_liabilities: Decimal
    short_term_debt: Decimal = Decimal("0.0")
    accounts_payable: Decimal = Decimal("0.0")
    tax_and_social_liabilities: Decimal = Decimal("0.0")
    other_current_liabilities: Decimal = Decimal("0.0")
    
    # Income Statement
    revenue: Decimal
    sold_production: Decimal = Decimal("0.0")
    other_operating_revenue: Decimal = Decimal("0.0")
    cost_of_goods_sold: Decimal = Decimal("0.0")
    external_expenses: Decimal = Decimal("0.0")
    personnel_expenses: Decimal = Decimal("0.0")
    taxes_and_duties: Decimal = Decimal("0.0")
    depreciation_and_amortization: Decimal = Decimal("0.0")
    other_operating_expenses: Decimal = Decimal("0.0")
    operating_income: Decimal = Decimal("0.0")
    financial_revenue: Decimal = Decimal("0.0")
    financial_expenses: Decimal = Decimal("0.0")
    financial_income: Decimal = Decimal("0.0")
    income_before_tax: Decimal = Decimal("0.0")
    extraordinary_income: Decimal = Decimal("0.0")
    income_tax: Decimal = Decimal("0.0")
    net_income: Decimal
    ebitda: Decimal
    
    # Cash Flows
    operating_cash_flow: Decimal
    investing_cash_flow: Decimal = Decimal("0.0")
    financing_cash_flow: Decimal = Decimal("0.0")
    change_in_cash: Decimal = Decimal("0.0")
    beginning_cash: Decimal = Decimal("0.0")
    ending_cash: Decimal = Decimal("0.0")
    
    # Info
    headcount: Optional[int] = None
    backlog_value: Optional[Decimal] = None
    capex: Optional[Decimal] = None
    is_consolidated: bool
    
    adjustments_count: int = 0
    normalized_json: str

    @model_validator(mode='after')
    def check_accounting_equation(self):
        liabilities_and_equity = self.equity + self.non_current_liabilities + self.current_liabilities
        diff = abs(self.total_assets - liabilities_and_equity)
        if diff > Decimal("1.0"):
            raise ValueError(
                f"Accounting equation violated: Total Assets ({self.total_assets}) "
                f"!= Equity + Liabilities ({liabilities_and_equity})"
            )
        return self

    model_config = ConfigDict(from_attributes=True)
