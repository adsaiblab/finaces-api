from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal
from typing import Optional, Any

class GateRequirementsSchema(BaseModel):
    required_doc_types: list[str] = ["FINANCIAL_STATEMENTS", "AUDITOR_OPINION"]
    optional_doc_types: list[str] = ["NOTES_ANNEXES", "TAX_DECLARATION", "BANK_REFERENCES"]
    reliability_weights: dict[str, Decimal] = {
        "HIGH": Decimal("1.00"),
        "MEDIUM": Decimal("0.75"),
        "LOW": Decimal("0.40"),
        "UNAUDITED": Decimal("0.20"),
    }
    dd_levels: dict[int, str] = {
        1: "Financial document authenticity",
        2: "Overall financial consistency",
        3: "Reputation and track record",
        4: "Structural risks and governance",
    }
    verdict_priority: dict[str, int] = {"BLOCKING": 3, "RESERVE": 2, "OK": 1}

class InterpretationMatrixSchema(BaseModel):
    # Dictionary mapping pillar -> list of tuples (ratio_name, threshold_ranges)
    # Ex: { "liquidity": [ ("current_ratio", {"STRONG": (Decimal("1.5"), Decimal("2.0"))}) ] }
    pillar_ratio_map: dict[str, list[tuple[Optional[str], Optional[dict[str, tuple[Optional[Decimal], Optional[Decimal]]]]]]] = {}

class DynamicScoringWeightsSchema(BaseModel):
    liquidity: Decimal = Decimal("0.25")
    solvency: Decimal = Decimal("0.25")
    profitability: Decimal = Decimal("0.15")
    capacity: Decimal = Decimal("0.25")
    quality: Decimal = Decimal("0.10")

class MarketSizeLimitsSchema(BaseModel):
    medium_threshold: Decimal = Decimal("1000000.00")
    large_threshold: Decimal = Decimal("10000000.00")

class IntraPillarWeightsSchema(BaseModel):
    liquidity: dict[str, Decimal] = {"primary": Decimal("0.6"), "secondary": Decimal("0.4")}
    solvency: dict[str, Decimal] = {"primary": Decimal("0.55"), "secondary": Decimal("0.45")}
    profitability: dict[str, Decimal] = {"primary": Decimal("0.6"), "secondary": Decimal("0.4")}
    capacity: dict[str, Decimal] = {"primary": Decimal("0.5"), "secondary": Decimal("0.5")}

class ScoringConfigurationSchema(BaseModel):
    default_weights: DynamicScoringWeightsSchema = DynamicScoringWeightsSchema()
    intra_pillar_weights: IntraPillarWeightsSchema = IntraPillarWeightsSchema() # <-- AJOUT P1-HARDCODE-03
    market_size_limits: MarketSizeLimitsSchema = MarketSizeLimitsSchema()
    risk_bands: dict[str, str] = {"safe": "4.0", "medium": "3.0", "high": "2.0", "critical": "0.0"}
    # Map of market sizes to specific weights
    dynamic_weights: dict[str, DynamicScoringWeightsSchema] = {
        "SMALL": DynamicScoringWeightsSchema(),
        "MEDIUM": DynamicScoringWeightsSchema(),  # Can be customized via the Policy DB
        "LARGE": DynamicScoringWeightsSchema()
    }

class AlertThresholdMinMaxSchema(BaseModel):
    min: Optional[Decimal] = None
    max: Optional[Decimal] = None
    warn: Optional[Decimal] = None

class StressConfigurationSchema(BaseModel):
    cost_curve_ratio: Decimal = Decimal("0.85")

class CrossPillarThresholdsSchema(BaseModel):
    false_liquidity_cr_min: Decimal = Decimal("1.5")
    false_liquidity_qr_max: Decimal = Decimal("0.8")
    overleverage_roe_min: Decimal = Decimal("15.0")
    overleverage_dte_min: Decimal = Decimal("2.0")
    toxic_wcr_pct_min: Decimal = Decimal("30.0")
    scissors_margin_drop: Decimal = Decimal("2.0")
    scissors_wcr_rise: Decimal = Decimal("5.0")

class RatioConfigurationSchema(BaseModel):
    z_score_safe_threshold: Decimal = Decimal("2.99")
    z_score_grey_threshold: Decimal = Decimal("1.81")
    # <-- AJOUT P1
    balance_sheet_tolerance_pct: Decimal = Decimal("0.02")
    very_low_current_ratio: Decimal = Decimal("0.5")
    z_score_coefficients: dict[str, Decimal] = { # <-- AJOUT P1-HARDCODE-01
        "x1": Decimal("6.56"),
        "x2": Decimal("3.26"),
        "x3": Decimal("6.72"),
        "x4": Decimal("1.05")
    }

class ConsortiumConfigurationSchema(BaseModel):
    synergy_limits: dict[str, Decimal] = {"high": Decimal("0.30"), "medium": Decimal("0.15")}
    synergy_bonus: dict[str, Decimal] = {"high": Decimal("0.50"), "medium": Decimal("0.25")}

class PolicyConfigurationSchema(BaseModel):
    version_id: str
    version_label: str = "1.0.0"
    gate: GateRequirementsSchema = GateRequirementsSchema()
    interpretation: InterpretationMatrixSchema = InterpretationMatrixSchema()
    scoring: ScoringConfigurationSchema = ScoringConfigurationSchema()
    stress: StressConfigurationSchema = StressConfigurationSchema()
    ratio: RatioConfigurationSchema = RatioConfigurationSchema()
    consortium: ConsortiumConfigurationSchema = ConsortiumConfigurationSchema()
    cross_pillar: CrossPillarThresholdsSchema = CrossPillarThresholdsSchema() # <-- AJOUT P1
    
    alert_thresholds: dict[str, AlertThresholdMinMaxSchema] = {}
    alert_labels: dict[str, str] = {}
    
    stale_data_months_limit: int = 18
    max_score_if_missing_pillar: str = "MEDIUM" # Default mapped fallback RiskClass string
    
    # Benchmarks & Comparisons
    sector_benchmarks: dict[str, dict[str, dict[str, Decimal | str]]] = Field(
        default_factory=lambda: {
            "BTP": {
                "debt_to_equity": {"max_tolerated": 4.0, "name": "Debt to Equity (D/E)"},
                "dso_days": {"max_tolerated": 150.0, "name": "Days Sales Outstanding (DSO)"},
                "net_margin": {"min_tolerated": 0.5, "name": "Net Margin (%)"}
            },
            "SERVICES": {
                "debt_to_equity": {"max_tolerated": 2.0, "name": "Debt to Equity (D/E)"},
                "dso_days": {"max_tolerated": 120.0, "name": "Days Sales Outstanding (DSO)"},
                "net_margin": {"min_tolerated": 1.0, "name": "Net Margin (%)"}
            },
            "DEFAULT": {
                "debt_to_equity": {"max_tolerated": 3.0, "name": "Debt to Equity (D/E)"},
                "dso_days": {"max_tolerated": 120.0, "name": "Days Sales Outstanding (DSO)"},
                "net_margin": {"min_tolerated": 1.0, "name": "Net Margin (%)"}
            }
        }
    )

    # Consortium Rules
    consortium_aggregation_methods: dict[str, str] = Field(
        default_factory=lambda: {
            "JOINT_AND_SEVERAL": "weighted_average_participation",
            "JOINT": "weighted_average_technical_financial",
            "SEPARATE": "leader_only"
        }
    )

    risk_priority_map: dict[str, int] = Field(
        default_factory=lambda: {
            "LOW": 4,
            "MEDIUM": 3,
            "HIGH": 2,
            "CRITICAL": 1,
            "NOT_EVALUATED": 0
        }
    )
    
    model_config = ConfigDict(from_attributes=True)
