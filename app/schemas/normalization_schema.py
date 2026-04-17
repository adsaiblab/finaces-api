from pydantic import BaseModel, ConfigDict, Field, model_validator
from decimal import Decimal
from typing import Optional, Literal, Annotated, List
from datetime import datetime
from uuid import UUID


class AdjustmentSchema(BaseModel):
    raw_statement_id: UUID
    fiscal_year: int = Field(..., ge=1900, le=2100)
    adj_type: Literal["RECLASS", "CORRECTION", "ESTIMATE", "CURRENCY", "OTHER"]
    field: str = Field(..., min_length=1, max_length=100)
    amount_before: float = 0.0
    amount_after: float = 0.0
    mode: Literal['replace', 'add'] = 'add'
    justification: str = Field(..., min_length=1, max_length=2000)
    source_ref: Optional[str] = Field(None, max_length=500)

    model_config = ConfigDict(from_attributes=True)


class AdjustmentOut(BaseModel):
    """Schéma de sortie pour un ajustement/retraitement appliqué."""
    line_item: str
    original_value: float
    adjusted_value: float
    delta: float
    reason: str
    standard: str

    model_config = ConfigDict(from_attributes=True)


class BalanceSheetCoherence(BaseModel):
    """Indicateurs de cohérence comptable du bilan normalisé."""
    assets_liabilities_balanced: bool
    ebitda_coherent: bool
    cash_flow_coherent: bool
    coherence_score: float


class RatioReadiness(BaseModel):
    """Certification de disponibilité des champs pour le calcul de ratios avancés."""
    basic_ratios_ready: bool
    advanced_ratios_ready: bool
    missing_fields: List[str]


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
    
    # Assets Details
    liquid_assets: Optional[Decimal] = None
    inventory: Optional[Decimal] = None
    accounts_receivable: Optional[Decimal] = None
    other_current_assets: Optional[Decimal] = None
    current_assets: Optional[Decimal] = None # Aggregate
    
    intangible_assets: Optional[Decimal] = None
    tangible_assets: Optional[Decimal] = None
    financial_assets: Optional[Decimal] = None
    other_noncurrent_assets: Optional[Decimal] = None
    non_current_assets: Optional[Decimal] = None # Aggregate
    
    total_assets: Optional[Decimal] = None # Aggregate

    # Liabilities & Equity Details
    equity: Optional[Decimal] = None # Aggregate
    share_capital: Optional[Decimal] = None
    reserves: Optional[Decimal] = None
    retained_earnings_prior: Optional[Decimal] = None
    current_year_earnings: Optional[Decimal] = None

    non_current_liabilities: Optional[Decimal] = None # Aggregate
    long_term_debt: Optional[Decimal] = None
    long_term_provisions: Optional[Decimal] = None
    
    current_liabilities: Optional[Decimal] = None # Aggregate
    short_term_debt: Optional[Decimal] = None
    accounts_payable: Optional[Decimal] = None
    tax_and_social_liabilities: Optional[Decimal] = None
    other_current_liabilities: Optional[Decimal] = None
    
    total_liabilities_and_equity: Optional[Decimal] = None # Aggregate

    # Income Statement Details
    revenue: Optional[Decimal] = None
    sold_production: Optional[Decimal] = None
    other_operating_revenue: Optional[Decimal] = None
    cost_of_goods_sold: Optional[Decimal] = None
    external_expenses: Optional[Decimal] = None
    personnel_expenses: Optional[Decimal] = None
    taxes_and_duties: Optional[Decimal] = None
    depreciation_and_amortization: Optional[Decimal] = None
    other_operating_expenses: Optional[Decimal] = None
    operating_income: Optional[Decimal] = None
    financial_revenue: Optional[Decimal] = None
    financial_expenses: Optional[Decimal] = None
    financial_income: Optional[Decimal] = None
    income_before_tax: Optional[Decimal] = None
    extraordinary_income: Optional[Decimal] = None
    extraordinary_expenses: Optional[Decimal] = None
    income_tax: Optional[Decimal] = None
    net_income: Optional[Decimal] = None
    ebitda: Optional[Decimal] = None
    gross_profit: Optional[Decimal] = None

    # Cash Flows
    operating_cash_flow: Optional[Decimal] = None
    investing_cash_flow: Optional[Decimal] = None
    financing_cash_flow: Optional[Decimal] = None
    free_cash_flow: Optional[Decimal] = None
    change_in_cash: Optional[Decimal] = None
    beginning_cash: Optional[Decimal] = None
    ending_cash: Optional[Decimal] = None

    # Operational Metrics
    headcount: Optional[int] = None
    backlog_value: Optional[Decimal] = None
    dividends_distributed: Optional[Decimal] = None
    capex: Optional[Decimal] = None
    source_notes: Optional[str] = None

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


class NormalizedStatementDBInsert(BaseModel):
    """Schema representing the output of the normalization engine."""
    id: Optional[UUID] = Field(default=None, description="Will be generated if None")
    raw_statement_id: UUID
    fiscal_year: int
    currency_usd: str = "USD"
    exchange_rate: float
    
    # Assets
    total_assets: float
    current_assets: float
    liquid_assets: float
    inventory: float = 0.0
    accounts_receivable: float = 0.0
    other_current_assets: float = 0.0
    non_current_assets: float
    intangible_assets: float = 0.0
    tangible_assets: float = 0.0
    financial_assets: float = 0.0
    other_noncurrent_assets: float = 0.0
    
    # Liabilities & Equity
    total_liabilities_and_equity: float
    equity: float
    share_capital: float = 0.0
    reserves: float = 0.0
    retained_earnings_prior: float = 0.0
    current_year_earnings: float = 0.0
    non_current_liabilities: float
    long_term_debt: float = 0.0
    long_term_provisions: float = 0.0
    current_liabilities: float
    short_term_debt: float = 0.0
    accounts_payable: float = 0.0
    tax_and_social_liabilities: float = 0.0
    other_current_liabilities: float = 0.0
    
    # Income Statement
    revenue: float
    sold_production: float = 0.0
    other_operating_revenue: float = 0.0
    cost_of_goods_sold: float = 0.0
    external_expenses: float = 0.0
    personnel_expenses: float = 0.0
    taxes_and_duties: float = 0.0
    depreciation_and_amortization: float = 0.0
    other_operating_expenses: float = 0.0
    operating_income: float = 0.0
    financial_revenue: float = 0.0
    financial_expenses: float = 0.0
    financial_income: float = 0.0
    income_before_tax: float = 0.0
    extraordinary_income: float = 0.0
    income_tax: float = 0.0
    net_income: float
    ebitda: float
    extraordinary_expenses: float = 0.0
    dividends: float = 0.0
    gross_profit: float = 0.0
    
    # Cash Flows
    operating_cash_flow: Optional[float] = None
    investing_cash_flow: Optional[float] = None
    financing_cash_flow: Optional[float] = None
    change_in_cash: Optional[float] = None
    beginning_cash: Optional[float] = None
    ending_cash: Optional[float] = None
    free_cash_flow: float = 0.0

    # capex, backlog, headcount...
    capex: Optional[float] = None
    backlog_value: Optional[float] = None
    headcount: Optional[int] = None
    is_consolidated: bool

    adjustments_count: int = 0
    normalized_json: str

    @model_validator(mode='after')
    def check_accounting_equation(self):
        liabilities_and_equity = self.equity + self.non_current_liabilities + self.current_liabilities
        diff = abs(self.total_assets - liabilities_and_equity)
        if diff > 1.0:
            raise ValueError(
                f"Accounting equation violated: Total Assets ({self.total_assets}) "
                f"!= Equity + Liabilities ({liabilities_and_equity})"
            )
        return self

    model_config = ConfigDict(from_attributes=True)


class NormalizedStatementUIResponse(NormalizedStatementDBInsert):
    # Optional original fields
    capex_original: Optional[float] = None
    backlog_value_original: Optional[float] = None
    
    # Currency context for UI
    currency_original: Optional[str] = None
    
    # Assets (USD vs ORIGINAL)
    total_assets_original: Optional[float] = None
    current_assets_original: Optional[float] = None
    liquid_assets_original: float = 0.0
    inventory_original: Optional[float] = None
    accounts_receivable_original: Optional[float] = None
    other_current_assets_original: float = 0.0
    non_current_assets_original: float = 0.0
    intangible_assets_original: float = 0.0
    tangible_assets_original: float = 0.0
    financial_assets_original: float = 0.0
    other_noncurrent_assets_original: float = 0.0
    
    # Liabilities & Equity (USD vs ORIGINAL)
    total_liabilities_and_equity_original: float = 0.0
    equity_original: float = 0.0
    share_capital_original: float = 0.0
    reserves_original: float = 0.0
    retained_earnings_prior_original: float = 0.0
    current_year_earnings_original: float = 0.0
    non_current_liabilities_original: float = 0.0
    long_term_debt_original: float = 0.0
    long_term_provisions_original: float = 0.0
    current_liabilities_original: float = 0.0
    short_term_debt_original: float = 0.0
    accounts_payable_original: float = 0.0
    tax_and_social_liabilities_original: float = 0.0
    other_current_liabilities_original: float = 0.0
    
    # Income Statement (USD vs ORIGINAL)
    revenue_original: Optional[float] = None
    sold_production_original: float = 0.0
    extraordinary_expenses_original: float = 0.0
    dividends_original: float = 0.0
    gross_profit_original: float = 0.0
    other_operating_revenue_original: float = 0.0
    cost_of_goods_sold_original: float = 0.0
    external_expenses_original: float = 0.0
    personnel_expenses_original: float = 0.0
    taxes_and_duties_original: float = 0.0
    depreciation_and_amortization_original: float = 0.0
    other_operating_expenses_original: float = 0.0
    operating_income_original: Optional[float] = None
    financial_revenue_original: float = 0.0
    financial_expenses_original: float = 0.0
    financial_income_original: float = 0.0
    income_before_tax_original: float = 0.0
    extraordinary_income_original: float = 0.0
    income_tax_original: float = 0.0
    net_income_original: Optional[float] = None
    ebitda_original: Optional[float] = None
    
    # Cash Flows (USD vs ORIGINAL)
    operating_cash_flow_original: float = 0.0
    investing_cash_flow_original: float = 0.0
    financing_cash_flow_original: float = 0.0
    change_in_cash_original: float = 0.0
    beginning_cash_original: float = 0.0
    ending_cash_original: float = 0.0
    free_cash_flow_original: float = 0.0

    adjustments: List[AdjustmentOut] = []

    # Mission 5 — Validation cohérence bilan
    coherence: Optional[BalanceSheetCoherence] = None

    # Mission 6 — Certification champs pour ratios
    ratio_readiness: Optional[RatioReadiness] = None

