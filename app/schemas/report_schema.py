from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any, List
from app.schemas.gate_schema import GateDecisionSchema
from app.schemas.scoring_schema import ScorecardOutputSchema
from app.schemas.stress_schema import StressResultSchema
from app.schemas.consortium_schema import ConsortiumScorecardOutput

class ReportMasterSchema(BaseModel):
    report_id: str
    case_id: str
    bidder_name: str
    recommendation: Optional[str] = None
    
    # Textual Sections
    section_01_info: Optional[str] = None
    section_02_objective: Optional[str] = None
    section_03_scope: Optional[str] = None
    section_04_executive_summary: Optional[str] = None
    section_05_profile: Optional[str] = None
    section_06_analysis: Optional[str] = None
    section_07_capacity: Optional[str] = None
    section_08_red_flags: Optional[str] = None
    section_09_mitigants: Optional[str] = None
    section_10_scoring: Optional[str] = None
    section_11_assessment: Optional[str] = None
    section_12_recommendation: Optional[str] = None
    section_13_limitations: Optional[str] = None
    section_14_conclusion: Optional[str] = None
    
    # Tracking
    complete_flags: Dict[str, bool]
    sections_complete: int
    sections_total: int

    model_config = ConfigDict(from_attributes=True)
