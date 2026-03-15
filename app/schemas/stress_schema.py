from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict
from decimal import Decimal
from datetime import datetime
from enum import Enum

class StressDecision(str, Enum):
    SOLVENT = "SOLVENT"
    LIMIT = "LIMIT"
    INSOLVENT = "INSOLVENT"

class PaymentMilestoneSchema(BaseModel):
    title: str = ""
    day: int
    pct: Decimal

class StressScenarioInputSchema(BaseModel):
    contract_value: Decimal
    contract_months: int
    annual_ca_avg: Decimal
    cash_available: Decimal
    advance_pct: Decimal = Decimal("0.0")
    credit_lines: Decimal = Decimal("0.0")
    backlog_value: Decimal = Decimal("0.0")
    bank_guarantee: bool = False
    bank_guarantee_amount: Decimal = Decimal("0.0")
    milestones: List[PaymentMilestoneSchema] = []
    
    # Indicateurs dynamiques
    bfr_rate_sector: Decimal = Decimal("0.15") # Equivalent au BFR_sector_rates JSON
    annual_caf_generated: Optional[Decimal] = None

class ScenarioFlowSchema(BaseModel):
    month: int
    day: int
    caf_generated: Decimal
    costs: Dict[str, Decimal] = {}
    cash: Dict[str, Decimal] = {}

class ScenarioSimulationResultSchema(BaseModel):
    name: str
    status: StressDecision
    cash_remaining: Decimal
    critical_month: Optional[int] = None
    config: Dict[str, str] = {}
    
class StressResultSchema(BaseModel):
    contract_value: Decimal
    contract_months: int
    annual_ca_avg: Decimal
    exposition_pct: Decimal
    backlog_value: Decimal
    
    bank_guarantee: bool
    bank_guarantee_amount: Decimal
    credit_lines_confirmed: Decimal
    cash_available: Decimal
    
    working_capital_requirement_estimate: Decimal
    advance_payment_pct: Decimal
    payment_milestones: List[PaymentMilestoneSchema]
    
    stress_60d_result: StressDecision
    stress_90d_result: StressDecision
    
    stress_60d_cash_position: Decimal
    stress_90d_cash_position: Decimal
    
    score_capacity: Decimal
    capacity_conclusion: str
    
    monthly_flows: List[ScenarioFlowSchema]
    scenarios_results: Dict[str, ScenarioSimulationResultSchema]
    data_alerts: List[str]
    
    model_config = ConfigDict(from_attributes=True)
