from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime
from uuid import UUID

from app.schemas.enums import RiskClass

class PillarDetailSchema(BaseModel):
    id: str
    name: str
    score: Decimal = Field(..., ge=0, le=5)
    weight: Decimal
    trend: List[Decimal] = []
    signals: List[str] = []
    status: str = "GOOD"  # EXCELLENT | GOOD | FAIR | POOR | CRITICAL
    key_drivers: List[str] = []
    detailText: str = ""

    model_config = ConfigDict(from_attributes=True)

class OverrideDetailSchema(BaseModel):
    id: Optional[UUID] = None
    target: str
    type: str
    old_val: str
    new_val: str
    status: str
    author: str
    time: datetime
    rationale: str

class ScorecardInputSchema(BaseModel):
    liquidity_score: Decimal = Field(..., ge=0, le=5)
    solvency_score: Decimal = Field(..., ge=0, le=5)
    profitability_score: Decimal = Field(..., ge=0, le=5)
    capacity_score: Decimal = Field(..., ge=0, le=5)
    quality_score: Decimal = Field(..., ge=0, le=5)
    
    # Flags bloquants
    is_gate_blocking: bool = False
    gate_blocking_reasons: List[str] = []
    
    has_negative_equity: bool = False
    
    # Financials for dynamism (Ex: Market Size Limits)
    contract_value: Decimal = Decimal("0.0")

class ScorecardOutputSchema(BaseModel):
    case_id: Optional[str] = None
    system_calculated_score: Decimal
    system_risk_class: RiskClass
    
    global_score: Decimal
    base_risk_class: RiskClass
    
    is_overridden: bool = False
    final_risk_class: RiskClass
    override_rationale: Optional[str] = None
    
    risk_profile: Optional[str] = None
    risk_description: Optional[str] = None
    
    synergy_index: Optional[Decimal] = None
    synergy_bonus: Optional[Decimal] = None
    
    cross_analysis_alerts: List[str] = []
    trends_summary: Dict[str, str] = {}
    
    pillars: List[PillarDetailSchema]
    smart_recommendations: List[str]
    overrides_applied: List[Dict[str, Any]] = []
    
    computed_at: datetime
    calculation_date: Optional[str] = None # For frontend compatibility
    
    model_config = ConfigDict(from_attributes=True)

class ScoreOverridePayload(BaseModel):
    new_score: Decimal = Field(..., ge=0, le=5)
    reason: str = Field(..., min_length=5)
