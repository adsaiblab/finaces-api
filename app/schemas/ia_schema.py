"""
Pydantic V2 Schemas for AI Module

All schemas for IA prediction requests, responses, and related data structures.

Language: 100% English
"""

from pydantic import BaseModel, Field, ConfigDict, model_validator
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
    """Input schema for What-If simulation.

    At least one parameter override is required to run a meaningful simulation.
    Keys must be valid feature names known to the model; unknown keys are
    silently ignored during scoring but returned in the result for traceability.
    """
    scenario_name: str = Field(..., min_length=1, description="Human-readable scenario label")
    parameter_overrides: Dict[str, float] = Field(
        default_factory=dict,
        description="Feature overrides to apply on top of real computed features"
    )

    @model_validator(mode="after")
    def require_at_least_one_override(self) -> "WhatIfInput":
        if not self.parameter_overrides:
            raise ValueError("parameter_overrides must contain at least one entry")
        return self


class WhatIfResult(BaseModel):
    """Result schema for What-If simulation.

    Returns both the baseline (real) and the simulated (overridden) assessment
    so the frontend can display delta information clearly.
    """
    scenario_name: str
    # Baseline — real prediction without overrides
    baseline_score: float = Field(0.0, description="Real IA score (0-100) before overrides")
    baseline_class: str = Field("MODERATE", description="Real risk class before overrides")
    # Simulated — prediction with overrides applied
    predicted_score_if: float = Field(0.0, description="Simulated IA score (0-100) with overrides")
    predicted_class_if: str = Field("MODERATE", description="Simulated risk class with overrides")
    # Delta
    delta_score: float = Field(0.0, description="predicted_score_if - baseline_score")
    # Explanations and traceability
    feature_impacts: List[IAFeatureContribution] = Field(
        default_factory=list,
        description="Top SHAP contributions computed on the overridden features"
    )
    overridden_features: Dict[str, float] = Field(
        default_factory=dict,
        description="The effective overrides that were applied (subset of parameter_overrides)"
    )


class IAFeaturesResponse(BaseModel):
    """Response schema for computed features."""
    model_config = ConfigDict(from_attributes=True)
    
    case_id: str
    computed_at: str
    features: Dict[str, Any]
    missing_flags: Dict[str, bool]
    capped_flags: Dict[str, bool]
    metadata: Dict[str, Any]
