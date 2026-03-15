from pydantic import BaseModel, ConfigDict
from typing import Dict, List, Optional
from decimal import Decimal

class TemporalDataPoint(BaseModel):
    fiscal_year: int
    current_ratio: Optional[Decimal] = None
    debt_to_equity: Optional[Decimal] = None
    net_margin: Optional[Decimal] = None
    cash_flow_capacity: Optional[Decimal] = None
    revenue: Optional[Decimal] = None
    revenue_growth_pct: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)

class TemporalComparisonSchema(BaseModel):
    status: str
    case_id: str
    years_covered: List[int]
    data: Dict[int, TemporalDataPoint]
    trend: str
    dynamic_risk_alerts: List[str]

    model_config = ConfigDict(from_attributes=True)

class BenchmarkMetricResult(BaseModel):
    name: str
    value: Decimal
    reference_max: Optional[Decimal] = None
    reference_min: Optional[Decimal] = None
    status: str

    model_config = ConfigDict(from_attributes=True)

class BenchmarkResultSchema(BaseModel):
    status: str
    case_id: str
    detected_sector: str
    analysis: Dict[str, BenchmarkMetricResult]

    model_config = ConfigDict(from_attributes=True)
