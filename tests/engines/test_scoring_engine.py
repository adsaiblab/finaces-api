import pytest
from decimal import Decimal
from typing import Dict

from app.engines.scoring_engine import compute_pure_scorecard
from app.schemas.scoring_schema import ScorecardInputSchema, ScorecardOutputSchema, RiskClass
from app.schemas.policy_schema import PolicyConfigurationSchema, ScoringConfigurationSchema

def test_scoring_engine_pure_math_and_typing():
    """
    Test prouvant que le refactoring du Scoring Engine traite 
    l'intégralité du calcul en Decimal pur, en lisant la politique Pydantic
    sans provoquer de ValueError ni de NameError, et retourne une RiskClass Native.
    """
    
    # Étape A: Instanciation PolicyConfigurationSchema strict (D-04, P-02)
    fake_policy = PolicyConfigurationSchema(
        version_id="1.5bis_audit",
        scoring=ScoringConfigurationSchema(
            risk_bands={"safe": "4.0", "medium": "3.0", "high": "2.0", "critical": "0.0"}
        )
    )
    
    # Manipulation pour être certain des pondérations dynamiques testées
    fake_policy.scoring.default_weights.liquidity = Decimal("0.20")
    fake_policy.scoring.default_weights.solvency = Decimal("0.25")
    fake_policy.scoring.default_weights.profitability = Decimal("0.20")
    fake_policy.scoring.default_weights.capacity = Decimal("0.20")
    fake_policy.scoring.default_weights.quality = Decimal("0.15")

    # IMPORTANT: Force sync in dynamic dictionary
    fake_policy.scoring.dynamic_weights["SMALL"].liquidity = Decimal("0.20")
    fake_policy.scoring.dynamic_weights["SMALL"].solvency = Decimal("0.25")
    fake_policy.scoring.dynamic_weights["SMALL"].profitability = Decimal("0.20")
    fake_policy.scoring.dynamic_weights["SMALL"].capacity = Decimal("0.20")
    fake_policy.scoring.dynamic_weights["SMALL"].quality = Decimal("0.15")
    
    # Étape B: Instanciation ScorecardInputSchema en Anglais IFRS (REG-04)
    fake_inputs = ScorecardInputSchema(
        liquidity_score=Decimal("4.50"),
        solvency_score=Decimal("3.80"),
        profitability_score=Decimal("2.90"),
        capacity_score=Decimal("4.10"),
        quality_score=Decimal("4.80"),
        is_gate_blocking=False,
        gate_blocking_reasons=[],
        has_negative_equity=False,
        contract_value=Decimal("500000.00") # Small Threshold => default_weights
    )

    # Étape C: Exécution Moteur Pur
    result = compute_pure_scorecard(inputs=fake_inputs, policy=fake_policy, overrides=[])

    # Étape D: Assertions strictes (REG-02 / Type Safety)
    assert isinstance(result, ScorecardOutputSchema)
    
    # Assertion Math : 
    # (4.50 * 0.20) + (3.80 * 0.25) + (2.90 * 0.20) + (4.10 * 0.20) + (4.80 * 0.15)
    # = (0.90) + (0.95) + (0.58) + (0.82) + (0.72)
    # = 3.97 -> arrondi à '.001' => Decimal('3.970')
    assert isinstance(result.global_score, Decimal)
    assert result.global_score == Decimal("3.970")

    assert isinstance(result.final_risk_class, RiskClass)
    
    # 3.970 >= 3.0 (medium_threshold) && < 4.0 (safe_threshold). RiskUtils map says MEDIUM.
    assert result.final_risk_class == RiskClass.MODERATE
    
    # Test Override Mappings (A-01 / P-01)
    # No overrides applied, final risk should equal base.
    assert result.is_overridden is False
    assert result.system_calculated_score == Decimal("3.970")
    assert result.system_risk_class == RiskClass.MODERATE
