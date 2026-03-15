from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import List, Optional
from decimal import Decimal
from app.schemas.enums import ConsortiumRole

class ConsortiumMemberInput(BaseModel):
    bidder_id: str
    bidder_name: str
    role: ConsortiumRole
    participation_pct: Decimal = Field(..., ge=0, le=100)
    score_global: Decimal = Field(...)
    score_liquidity: Optional[Decimal] = None
    score_solvency: Optional[Decimal] = None
    score_profitability: Optional[Decimal] = None
    score_capacity: Optional[Decimal] = None
    final_risk_class: str
    stress_60d_result: str

    model_config = ConfigDict(from_attributes=True)

class ConsortiumInputSchema(BaseModel):
    consortium_id: str
    jv_type: str
    members: List[ConsortiumMemberInput]

    @model_validator(mode='after')
    def check_participation_sum(self):
        total_pct = sum([m.participation_pct for m in self.members])
        # Allow exact matches to 100.00
        if total_pct != Decimal('100.00'):
            raise ValueError(f"Consortium participation percentages must exactly equal 100.00%. Current total: {total_pct}")
        return self

    model_config = ConfigDict(from_attributes=True)

class ConsortiumScorecardOutput(BaseModel):
    consortium_id: str
    jv_type: str
    aggregation_method: str
    weighted_score: Decimal
    synergy_index: Decimal
    synergy_bonus: Decimal
    base_risk_class: str
    final_risk_class: str
    weak_link_triggered: bool
    weak_link_member: Optional[str] = None
    leader_blocking: bool
    leader_override: bool
    aggregated_stress: str
    members: List[dict]
    mitigations_suggested: List[str]
    computed_at: str

    model_config = ConfigDict(from_attributes=True)
