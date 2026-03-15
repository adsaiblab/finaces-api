from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Literal
from datetime import datetime
from uuid import UUID
from decimal import Decimal

class DocumentEvidenceSchema(BaseModel):
    id: Optional[UUID] = None
    doc_type: str
    fiscal_year: int
    filename: Optional[str] = None
    status: Literal["PRESENT", "MISSING", "INCOMPLETE", "REJECTED"] = "PRESENT"
    reliability_level: Literal["HIGH", "MEDIUM", "LOW", "UNAUDITED"] = "MEDIUM"
    auditor_opinion: Optional[Literal["UNQUALIFIED", "QUALIFIED", "ADVERSE", "DISCLAIMER"]] = None
    notes: Optional[str] = None
    red_flags: Optional[list[dict]] = []

    model_config = ConfigDict(from_attributes=True)

class DueDiligenceCheckSchema(BaseModel):
    id: Optional[UUID] = None
    dd_level: int
    verdict: Literal["OK", "RESERVE", "BLOCKING"]
    notes: str = ""
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class GateDecisionSchema(BaseModel):
    is_passed: bool
    verdict: str
    reliability_level: str
    reliability_score: Decimal
    missing_mandatory: List[str]
    missing_optional: List[str]
    blocking_reasons: List[str]
    reserve_flags: List[str]
    computed_at: datetime

    model_config = ConfigDict(from_attributes=True)
