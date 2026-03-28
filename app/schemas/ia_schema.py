"""
Pydantic V2 Schemas for AI Module

All schemas for IA prediction requests, responses, and related data structures.

Language: 100% English
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class IARiskClass(str, Enum):
    """AI-generated risk classification."""
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IAFeatureContribution(BaseModel):
    """Individual feature contribution to prediction."""
    model_config = ConfigDict(from_attributes=True)

    feature_name: str
    feature_value: Optional[float] = None
    shap_value: float
    impact: str  # "increases_risk" or "decreases_risk"
    direction: str = "POSITIVE"  # POSITIVE | NEGATIVE
    magnitude: str = "LOW"  # LOW | MEDIUM | HIGH

    @classmethod
    def from_raw(cls, feature_name: str, feature_value: float, shap_value: float):
        abs_val = abs(shap_value)
        return cls(
            feature_name=feature_name,
            feature_value=feature_value,
            shap_value=shap_value,
            impact="increases_risk" if shap_value >= 0 else "decreases_risk",
            direction="POSITIVE" if shap_value >= 0 else "NEGATIVE",
            magnitude="HIGH" if abs_val > 0.3 else "MEDIUM" if abs_val > 0.1 else "LOW",
        )


class IAExplanation(BaseModel):
    """SHAP-based explanation for AI prediction."""
    model_config = ConfigDict(from_attributes=True)
    
    top_features: List[IAFeatureContribution]
    explanation_method: str = "SHAP TreeExplainer"
    base_value: float


class IAPredictionResult(BaseModel):
    """Complete AI prediction result."""
    model_config = ConfigDict(from_attributes=True)
    
    case_id: str
    ia_score: float = Field(..., description="IA score on 0-100 scale")
    ia_probability_default: float = Field(..., description="Probability of default (0-1)")
    ia_risk_class: IARiskClass
    model_version: str
    predicted_at: datetime
    explanations: Optional[IAExplanation] = None
    threshold_info: Dict[str, float]


class WhatIfInput(BaseModel):
    scenario_name: str
    parameter_overrides: dict[str, float] = {}


class WhatIfResult(BaseModel):
    scenario_name: str
    predicted_score_if: float = 0.0
    predicted_class_if: str = "MODERATE"
    delta_score: float = 0.0
    feature_impacts: list[IAFeatureContribution] = []


class IAFeaturesResponse(BaseModel):
    """Response schema for computed features."""
    model_config = ConfigDict(from_attributes=True)
    
    case_id: str
    computed_at: str
    features: Dict[str, Any]
    missing_flags: Dict[str, bool]
    capped_flags: Dict[str, bool]
    metadata: Dict[str, Any]
