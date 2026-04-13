from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Literal
from app.schemas.enums import DocStatus, ReliabilityLevel, AuditorOpinion, DDVerdict
from datetime import datetime
from uuid import UUID
from decimal import Decimal

class DocumentEvidenceSchema(BaseModel):
    id: Optional[UUID] = None
    doc_type: str
    fiscal_year: Optional[int] = None
    filename: Optional[str] = None
    status: DocStatus = DocStatus.PRESENT
    reliability_level: ReliabilityLevel = ReliabilityLevel.MEDIUM
    auditor_opinion: Optional[AuditorOpinion] = None
    notes: Optional[str] = None
    red_flags: Optional[list[dict]] = Field(default_factory=list, alias="red_flags_json")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, use_enum_values=True)

class DueDiligenceCheckSchema(BaseModel):
    id: Optional[UUID] = None
    dd_level: int
    verdict: DDVerdict
    notes: str = ""
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

class GateDecisionSchema(BaseModel):
    is_passed: bool
    verdict: Literal["PASSED", "BLOCKING", "PASS_WITH_RESERVES", "REJECTED"]
    reliability_level: str
    reliability_score: Decimal
    missing_mandatory: List[str]
    missing_optional: List[str]
    blocking_reasons: List[str]
    reserve_flags: List[str]
    computed_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)
