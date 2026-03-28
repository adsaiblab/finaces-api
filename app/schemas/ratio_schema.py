from pydantic import BaseModel, ConfigDict, Field, model_validator
from decimal import Decimal
from decimal import Decimal
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from uuid import UUID

class AlertSchema(BaseModel):
    """Schema representing financial alerts and cross-pillar patterns."""
    key: Optional[str] = None
    label: Optional[str] = None
    year: Optional[int] = None
    value: Optional[Decimal] = None
    severity: Optional[str] = None
    note: Optional[str] = None
    
    # Used for advanced cross-pillar patterns
    pattern: Optional[str] = None
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class RatioSetSchema(BaseModel):
    """Schema representing the calculated ratios for a given fiscal year."""
    id: Optional[UUID] = Field(default=None, description="Will be generated if None")
    case_id: UUID
    fiscal_year: int
    normalized_statement_id: UUID
    
    current_ratio: Optional[Decimal] = None
    quick_ratio: Optional[Decimal] = None
    cash_ratio: Optional[Decimal] = None
    working_capital: Optional[Decimal] = None
    debt_to_equity: Optional[Decimal] = None
    financial_autonomy: Optional[Decimal] = None
    gearing: Optional[Decimal] = None
    interest_coverage: Optional[Decimal] = None
    net_margin: Optional[Decimal] = None
    ebitda_margin: Optional[Decimal] = None
    operating_margin: Optional[Decimal] = None
    roa: Optional[Decimal] = None
    roe: Optional[Decimal] = None
    dso_days: Optional[Decimal] = None
    dpo_days: Optional[Decimal] = None
    dio_days: Optional[Decimal] = None
    cash_conversion_cycle: Optional[Decimal] = None
    working_capital_requirement: Optional[Decimal] = None
    working_capital_requirement_pct_revenue: Optional[Decimal] = None
    cash_flow_capacity: Optional[Decimal] = None
    cash_flow_capacity_margin_pct: Optional[Decimal] = None
    debt_repayment_years: Optional[Decimal] = None
    
    negative_equity: Optional[int] = None
    negative_operating_cash_flow: Optional[int] = None
    
    coherence_alerts_json: Optional[List[Dict[str, Any]] | Dict[str, Any] | list | dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Financial Intelligence Phase 2
    z_score_altman: Optional[Decimal] = None
    z_score_zone: Optional[str] = None

    @model_validator(mode='after')
    def validate_ratio_coherence(self) -> 'RatioSetSchema':
        """P2-08: Global consistency check for calculated ratios."""
        if self.current_ratio is not None and self.current_ratio < 0:
            raise ValueError("Current Ratio cannot be negative.")
        if self.debt_to_equity is not None and self.debt_to_equity < -100: # Safety margin for negative equity
            raise ValueError("Extreme Debt-to-Equity imbalance detected.")
        return self

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# T09: RatioValue enrichment schemas
# ============================================================================

from app.schemas.enums import RatioStatus


class TrendPoint(BaseModel):
    fiscal_year: int
    value: float


class RatioValue(BaseModel):
    current: float
    trend: list[TrendPoint] = []
    benchmark_min: float = 0.0
    benchmark_max: float = 0.0
    status: str = "GREEN"  # GREEN|YELLOW|ORANGE|RED
    unit: str = "x"
    variation_pct: float = 0.0
    analyst_note: str | None = None


class LiquidityGroup(BaseModel):
    current_ratio: RatioValue
    quick_ratio: RatioValue
    cash_ratio: RatioValue
    dio_days: RatioValue
    cash_conversion_cycle: RatioValue


class SolvencyGroup(BaseModel):
    debt_to_equity: RatioValue
    debt_to_assets: RatioValue
    interest_coverage: RatioValue
    negative_equity: bool = False
    negative_operating_cash_flow: bool = False


class ProfitabilityGroup(BaseModel):
    gross_margin: RatioValue
    operating_margin: RatioValue
    net_margin: RatioValue
    return_on_assets: RatioValue
    return_on_equity: RatioValue
    ebitda_margin: RatioValue


class CapacityGroup(BaseModel):
    debt_service_coverage: RatioValue
    free_cash_flow_to_debt: RatioValue
    capex_to_revenue: RatioValue


class ZScoreGroup(BaseModel):
    z_score_altman: RatioValue
    z_score_zone: str = "GREY"


class RatioSetEnrichedOut(BaseModel):
    id: str
    case_id: str
    sector_code: str | None = None
    coherence_status: str | None = None
    liquidity: LiquidityGroup
    solvency: SolvencyGroup
    profitability: ProfitabilityGroup
    capacity: CapacityGroup
    z_score: ZScoreGroup
    created_at: datetime


class BenchmarkRange(BaseModel):
    min: float
    max: float
