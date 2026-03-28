from decimal import Decimal
from typing import Optional

from app.schemas.policy_schema import PolicyConfigurationSchema
from app.schemas.enums import RiskClass

def get_risk_band(score: Decimal, policy: PolicyConfigurationSchema) -> RiskClass:
    """
    [D-04 / RF-01] Single Source of Truth
    Classifie le score brut (0.00 - 5.00) en RiskClass en se basant EXCLUSIVEMENT 
    on the thresholds defined in the global PolicyConfigurationSchema injection.
    """
    
    # Policy Schema determines dict parsing
    # Default behavior modeled from traditional policy, but using the policy schema limits securely.
    thresholds = policy.scoring.risk_bands
    
    if score >= Decimal(str(thresholds.get("safe", "4.0"))):
        return RiskClass.LOW
    elif score >= Decimal(str(thresholds.get("medium", "3.0"))):
        return RiskClass.MODERATE
    elif score >= Decimal(str(thresholds.get("high", "2.0"))):
        return RiskClass.HIGH
        
    return RiskClass.CRITICAL
