from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Literal, Annotated
from uuid import UUID
from datetime import datetime
from enum import Enum

# Reusable bounded string type for free-text list items
_BoundedStr500 = Annotated[str, Field(min_length=1, max_length=500)]


class OverrideRecommendation(str, Enum):
    NONE = "NONE"
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"


class FinalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


class ExpertReviewInputSchema(BaseModel):
    analyst_id: str = Field(..., min_length=1, max_length=100)
    liquidity_comment: str       = Field("", max_length=2000)
    solvability_comment: str     = Field("", max_length=2000)
    profitability_comment: str   = Field("", max_length=2000)
    capacity_comment: str        = Field("", max_length=2000)
    quality_comment: str         = Field("", max_length=2000)
    dynamic_analysis_comment: str = Field("", max_length=4000)
    mitigating_factors: list[_BoundedStr500] = Field(default_factory=list, max_length=20)
    risk_factors: list[_BoundedStr500]        = Field(default_factory=list, max_length=20)
    override_recommendation: OverrideRecommendation = OverrideRecommendation.NONE
    # Keep legacy field for backward compat
    qualitative_notes: Optional[str] = Field(None, max_length=4000)


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
