from pydantic import BaseModel, ConfigDict
from typing import Optional, Literal
from uuid import UUID
from datetime import datetime
from enum import Enum

class OverrideRecommendation(str, Enum):
    NONE = "NONE"
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"

class FinalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"

class ExpertReviewInputSchema(BaseModel):
    analyst_id: str
    liquidity_comment: str = ""
    solvability_comment: str = ""
    profitability_comment: str = ""
    capacity_comment: str = ""
    quality_comment: str = ""
    dynamic_analysis_comment: str = ""
    mitigating_factors: list[str] = []
    risk_factors: list[str] = []
    override_recommendation: OverrideRecommendation = OverrideRecommendation.NONE
    # Keep legacy field for backward compat
    qualitative_notes: Optional[str] = None

class ExpertReviewOutputSchema(BaseModel):
    id: UUID
    case_id: UUID
    analyst_id: str
    liquidity_comment: Optional[str] = None
    solvability_comment: Optional[str] = None
    profitability_comment: Optional[str] = None
    capacity_comment: Optional[str] = None
    quality_comment: Optional[str] = None
    dynamic_analysis_comment: Optional[str] = None
    mitigating_factors: list[str] = []
    risk_factors: list[str] = []
    override_recommendation: Optional[str] = "NONE"
    qualitative_notes: Optional[str] = None
    manual_risk_override: Optional[str] = None
    final_decision: Literal["APPROVED", "REJECTED", "ESCALATED"]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


def derive_final_decision(
    override: str,
    final_score: float,
    threshold_approved: float = 3.0,
    threshold_escalate: float = 2.0,
) -> str:
    effective_score = final_score
    if override == "UPGRADE":
        effective_score += 0.5
    elif override == "DOWNGRADE":
        effective_score -= 0.5

    if effective_score >= threshold_approved:
        return "APPROVED"
    elif effective_score >= threshold_escalate:
        return "ESCALATED"
    else:
        return "REJECTED"
