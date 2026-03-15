from decimal import Decimal
from typing import Optional, List, Dict
from collections import Counter

from app.schemas.interpretation_schema import InterpretationInputSchema, InterpretationValidationSchema
from app.schemas.ratio_schema import RatioSetSchema
from app.schemas.policy_schema import PolicyConfigurationSchema


VALID_LABELS = ["INADEQUATE", "WEAK", "MODERATE", "STRONG", "VERY_STRONG", "NOT_EVALUATED"]

def _get_expected_label(value: Optional[Decimal], ranges: Dict[str, tuple]) -> Optional[str]:
    """Pure Function: Searches in which Decimal interval the value falls."""
    if value is None:
        return "NOT_EVALUATED"
        
    for label, (low, high) in ranges.items():
        if low is None and high is not None and value < high:
            return label
        if high is None and low is not None and value >= low:
            return label
        if low is not None and high is not None and low <= value < high:
            return label
    return None

def validate_interpretation_coherence(
    ratios: Optional[RatioSetSchema],
    inputs: InterpretationInputSchema,
    policy: PolicyConfigurationSchema,
) -> InterpretationValidationSchema:
    """
    Pure Function: 
    Receives Ratios, Pydantic Input, and Policy via PolicyConfigurationSchema.
    Verifies mathematical/business rules coherence and returns mappings.
    """
    all_warnings = []
    coherence_ok = True
    suggested_labels = {}

    input_dict = inputs.model_dump()
    ratios_dict = ratios.model_dump() if ratios else {}

    piliers = ["liquidity", "solvency", "profitability", "capacity", "quality"]
    pilier_ratio_map = policy.interpretation.pilier_ratio_map

    for pilier in piliers:
        label = input_dict.get(f"{pilier}_label")
        if not label or label not in VALID_LABELS:
            continue

        rules = pilier_ratio_map.get(pilier, [])
        labels_votes = []
        
        for ratio_key, ranges in rules:
            if ratio_key and ranges and ratios_dict:
                value = ratios_dict.get(ratio_key)
                
                # Handling missing values correctly to project NOT_EVALUATED directly
                expected = _get_expected_label(value, ranges)
                if expected:
                    labels_votes.append(expected)
        
        if labels_votes:
            majority_expected = Counter(labels_votes).most_common(1)[0][0]
            
            if majority_expected != label:
                coherence_ok = False
                suggested_labels[pilier] = majority_expected
                ratio_names = [r[0] for r in rules]
                all_warnings.append(
                    f"Inconsistency on {pilier.capitalize()}: the majority of ratios ({', '.join(ratio_names)}) "
                    f"suggests '{majority_expected}' but '{label}' was entered."
                )

        # Special case: capacity pillar — based on CFO (int/bool value)
        if pilier == "capacity" and ratios_dict:
            cfo_neg = ratios_dict.get("negative_operating_cash_flow", 0)
            if cfo_neg == 1 and label == "STRONG":
                coherence_ok = False
                suggested_labels[pilier] = "LOW"
                all_warnings.append(
                    "Inconsistency on Capacity: Negative CFO detected. "
                    "STRONG label incompatible with negative operating cash flow."
                )

    return InterpretationValidationSchema(
        valid=True,
        coherence_ok=coherence_ok,
        warnings=all_warnings,
        suggested_labels=suggested_labels
    )
