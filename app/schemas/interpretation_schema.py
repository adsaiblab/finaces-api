from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict

class InterpretationInputSchema(BaseModel):
    liquidity_label: Optional[str] = None
    liquidity_comment: Optional[str] = None
    
    solvency_label: Optional[str] = None
    solvency_comment: Optional[str] = None
    
    profitability_label: Optional[str] = None
    profitability_comment: Optional[str] = None
    
    capacity_label: Optional[str] = None
    capacity_comment: Optional[str] = None
    
    quality_label: Optional[str] = None
    quality_comment: Optional[str] = None
    
    dynamic_analysis_comment: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class InterpretationValidationSchema(BaseModel):
    valid: bool = True
    coherence_ok: bool
    warnings: List[str]
    suggested_labels: Dict[str, str]

    model_config = ConfigDict(from_attributes=True)
