from pydantic import BaseModel, ConfigDict
from typing import Optional, Literal
from uuid import UUID
from datetime import datetime

class ExpertReviewInputSchema(BaseModel):
    analyst_id: str
    qualitative_notes: str
    manual_risk_override: Optional[str] = None
    final_decision: Literal["APPROVED", "REJECTED", "ESCALATED"]

class ExpertReviewOutputSchema(BaseModel):
    id: UUID
    case_id: UUID
    analyst_id: str
    qualitative_notes: Optional[str] = None
    manual_risk_override: Optional[str] = None
    final_decision: Literal["APPROVED", "REJECTED", "ESCALATED"]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
