"""
Tension Detection Engine - MCC vs IA Comparison

This module detects and analyzes divergences between the official MCC scoring
and the AI-generated risk assessment. It generates alerts, explanations, and
recommendations when significant tensions are detected.

The tension detector NEVER overrides MCC decisions - it only provides
additional information to support analyst decision-making.

Stack: SQLAlchemy 2.0 Async, Pydantic V2, FastAPI, PostgreSQL
Language: 100% English
"""

from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from datetime import datetime
from dataclasses import dataclass
import logging
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import Scorecard, IAPrediction, IATension
from app.schemas.ia_schema import IAPredictionResult
from app.schemas.scoring_schema import ScorecardOutputSchema

logger = logging.getLogger(__name__)


class TensionType(str, Enum):
    """Types of tension between MCC and IA assessments."""
    CONVERGENCE = "CONVERGENCE"          # Both agree
    TENSION_UP = "TENSION_UP"            # IA sees higher risk than MCC
    TENSION_DOWN = "TENSION_DOWN"        # IA sees lower risk than MCC
    MAJOR_DIVERGENCE = "MAJOR_DIVERGENCE"  # 2+ risk levels apart
    CRITICAL_ALERT = "CRITICAL_ALERT"    # One says CRITICAL, other says LOW


class TensionSeverity(str, Enum):
    """Severity level of detected tension."""
    NONE = "NONE"              # Perfect alignment
    LOW = "LOW"                # 1 level difference, acceptable
    MODERATE = "MODERATE"      # 1 level difference, worth noting
    HIGH = "HIGH"              # 2 levels difference
    CRITICAL = "CRITICAL"      # 3 levels difference or extreme mismatch


@dataclass
class TensionAnalysis:
    """
    Complete tension analysis result.
    
    Contains all information about MCC vs IA comparison including
    tension type, severity, explanations, and recommended actions.
    """
    case_id: str
    mcc_risk_class: str
    ia_risk_class: str
    mcc_score: float
    ia_score: float
    tension_type: TensionType
    tension_severity: TensionSeverity
    risk_level_gap: int
    explanation: str
    detailed_explanation: str
    recommended_actions: List[str]
    requires_documentation: bool
    requires_senior_review: bool
    alert_message: Optional[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "case_id": self.case_id,
            "mcc_assessment": {
                "risk_class": self.mcc_risk_class,
                "score": round(self.mcc_score, 2)
            },
            "ia_assessment": {
                "risk_class": self.ia_risk_class,
                "score": round(self.ia_score, 2)
            },
            "tension": {
                "type": self.tension_type.value,
                "severity": self.tension_severity.value,
                "risk_level_gap": self.risk_level_gap
            },
            "explanation": self.explanation,
            "detailed_explanation": self.detailed_explanation,
            "recommended_actions": self.recommended_actions,
            "flags": {
                "requires_documentation": self.requires_documentation,
                "requires_senior_review": self.requires_senior_review,
                "has_alert": self.alert_message is not None
            },
            "alert_message": self.alert_message
        }


class TensionDetector:
    """
    Tension detection and analysis engine.
    
    Compares MCC and IA risk assessments to identify divergences,
    classify their severity, and generate actionable recommendations.
    """
    
    # Risk class hierarchy (for computing gaps)
    RISK_HIERARCHY = {
        "LOW": 0,
        "FAIBLE": 0,  # MCC French equivalent
        "MEDIUM": 1,   # RiskClass enum value
        "MODERATE": 1,
        "MODERE": 1,  # MCC French equivalent
        "HIGH": 2,
        "ELEVE": 2,  # MCC French equivalent
        "CRITICAL": 3,
        "CRITIQUE": 3  # MCC French equivalent
    }
    
    # Standardized templates for explanations
    EXPLANATION_TEMPLATES = {
        "CONVERGENCE": (
            "The AI assessment converges with the MCC official scoring. "
            "Both methodologies classify the risk as {risk_class}."
        ),
        "TENSION_UP": (
            "⚠️ The AI model estimates a HIGHER risk ({ia_class}) than the MCC scoring ({mcc_class}). "
            "This suggests potential hidden vulnerabilities not fully captured by traditional ratios."
        ),
        "TENSION_DOWN": (
            "ℹ️ The AI model estimates a LOWER risk ({ia_class}) than the MCC scoring ({mcc_class}). "
            "The AI may be identifying positive patterns or compensating factors."
        ),
        "MAJOR_DIVERGENCE": (
            "🚨 MAJOR DIVERGENCE DETECTED: The AI and MCC assessments differ by {gap} risk levels. "
            "This requires careful investigation of the underlying data and assumptions."
        ),
        "CRITICAL_ALERT": (
            "🔴 CRITICAL ALERT: Extreme mismatch between AI ({ia_class}) and MCC ({mcc_class}) assessments. "
            "Immediate senior review required before proceeding with any decision."
        )
    }
    
    def __init__(self):
        """Initialize the tension detector."""
        logger.info("TensionDetector initialized")
    
    async def analyze_tension(
        self,
        case_id: str,
        mcc_result: ScorecardOutputSchema,
        ia_result: IAPredictionResult,
        db: AsyncSession
    ) -> TensionAnalysis:
        """
        Perform complete tension analysis between MCC and IA.
        
        Args:
            case_id: Evaluation case identifier
            mcc_result: Official MCC scorecard result
            ia_result: AI prediction result
            db: Database session
            
        Returns:
            TensionAnalysis with complete comparison data
        """
        logger.info(f"Starting tension analysis for case {case_id}")
        
        # Normalize risk classes to common scale
        mcc_risk_raw = mcc_result.final_risk_class
        if hasattr(mcc_risk_raw, 'value'):
            mcc_risk_raw = mcc_risk_raw.value
        mcc_risk_normalized = self._normalize_mcc_risk_class(mcc_risk_raw)
        ia_risk_raw = ia_result.ia_risk_class
        if hasattr(ia_risk_raw, 'value'):
            ia_risk_raw = ia_risk_raw.value
        ia_risk_normalized = ia_risk_raw
        
        # Compute risk level gap
        risk_gap = self._compute_risk_gap(
            mcc_risk_normalized,
            ia_risk_normalized
        )
        
        # Determine tension type
        tension_type = self._determine_tension_type(
            mcc_risk_normalized,
            ia_risk_normalized,
            risk_gap
        )
        
        # Determine tension severity
        tension_severity = self._determine_tension_severity(
            tension_type,
            risk_gap
        )
        
        # Generate explanations
        explanation = self._generate_explanation(
            tension_type,
            mcc_risk_normalized,
            ia_risk_normalized,
            risk_gap
        )
        
        detailed_explanation = self._generate_detailed_explanation(
            mcc_result,
            ia_result,
            tension_type,
            risk_gap
        )
        
        # Generate recommended actions
        recommended_actions = self._generate_recommendations(
            tension_type,
            tension_severity,
            mcc_risk_normalized,
            ia_risk_normalized
        )
        
        # Determine if documentation/review required
        requires_documentation = self._requires_documentation(
            tension_severity,
            tension_type
        )
        
        requires_senior_review = self._requires_senior_review(
            tension_severity,
            tension_type
        )
        
        # Generate alert message if applicable
        alert_message = self._generate_alert_message(
            tension_type,
            tension_severity,
            mcc_risk_normalized,
            ia_risk_normalized
        )
        
        # Build analysis result
        analysis = TensionAnalysis(
            case_id=case_id,
            mcc_risk_class=mcc_risk_normalized,
            ia_risk_class=ia_risk_normalized,
            mcc_score=mcc_result.global_score,
            ia_score=ia_result.ia_score,
            tension_type=tension_type,
            tension_severity=tension_severity,
            risk_level_gap=risk_gap,
            explanation=explanation,
            detailed_explanation=detailed_explanation,
            recommended_actions=recommended_actions,
            requires_documentation=requires_documentation,
            requires_senior_review=requires_senior_review,
            alert_message=alert_message
        )
        
        # Persist tension record
        await self._save_tension(analysis, ia_result.model_version, db)
        
        logger.info(
            f"Tension analysis completed for case {case_id}. "
            f"Type: {tension_type.value}, Severity: {tension_severity.value}"
        )
        
        return analysis
    
    async def get_tension_history(
        self,
        case_id: str,
        db: AsyncSession,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieve historical tension analyses for a case.
        
        Args:
            case_id: Case identifier
            db: Database session
            limit: Maximum number of records to retrieve
            
        Returns:
            List of tension analysis dictionaries
        """
        case_uuid = uuid.UUID(case_id)
        stmt = (
            select(IATension)
            .where(IATension.case_id == case_uuid)
            .order_by(IATension.created_at.desc())
            .limit(limit)
        )
        
        result = await db.execute(stmt)
        tensions = result.scalars().all()
        
        return [
            {
                "created_at": t.created_at.isoformat(),
                "mcc_risk_class": t.mcc_risk_class,
                "ia_risk_class": t.ia_risk_class,
                "tension_type": t.tension_type,
                "explanation": t.explanation
            }
            for t in tensions
        ]
    
    # ========================================================================
    # INTERNAL COMPUTATION METHODS
    # ========================================================================
    
    def _normalize_mcc_risk_class(self, mcc_risk_class: str) -> str:
        """
        Normalize MCC risk class to English standard format.
        
        Handles both French (FAIBLE/MODERE/ELEVE/CRITIQUE) and
        English (LOW/MODERATE/HIGH/CRITICAL) formats.
        
        Args:
            mcc_risk_class: Original MCC risk class
            
        Returns:
            Normalized English risk class
        """
        upper_class = mcc_risk_class.upper()
        
        mapping = {
            "FAIBLE": "LOW",
            "LOW": "LOW",
            "MEDIUM": "MODERATE",  # RiskClass enum value
            "MODERE": "MODERATE",
            "MODÉRÉ": "MODERATE",
            "MODERATE": "MODERATE",
            "ELEVE": "HIGH",
            "ÉLEVÉ": "HIGH",
            "HIGH": "HIGH",
            "CRITIQUE": "CRITICAL",
            "CRITICAL": "CRITICAL"
        }
        
        return mapping.get(upper_class, "MODERATE")
    
    def _compute_risk_gap(
        self,
        mcc_risk_class: str,
        ia_risk_class: str
    ) -> int:
        """
        Compute the gap between risk classes.
        
        Args:
            mcc_risk_class: MCC risk classification
            ia_risk_class: IA risk classification
            
        Returns:
            Absolute difference in risk levels (0-3)
        """
        mcc_level = self.RISK_HIERARCHY.get(mcc_risk_class.upper(), 1)
        ia_level = self.RISK_HIERARCHY.get(ia_risk_class.upper(), 1)
        
        return abs(ia_level - mcc_level)
    
    def _determine_tension_type(
        self,
        mcc_risk_class: str,
        ia_risk_class: str,
        risk_gap: int
    ) -> TensionType:
        """
        Determine the type of tension between assessments.
        
        Args:
            mcc_risk_class: MCC risk classification
            ia_risk_class: IA risk classification
            risk_gap: Computed risk level gap
            
        Returns:
            TensionType enum value
        """
        mcc_level = self.RISK_HIERARCHY[mcc_risk_class.upper()]
        ia_level = self.RISK_HIERARCHY[ia_risk_class.upper()]
        
        # Perfect alignment
        if risk_gap == 0:
            return TensionType.CONVERGENCE
        
        # Critical alert: extreme mismatch (CRITICAL vs LOW)
        if (mcc_level == 3 and ia_level == 0) or (mcc_level == 0 and ia_level == 3):
            return TensionType.CRITICAL_ALERT
        
        # Major divergence: 2+ levels apart
        if risk_gap >= 2:
            return TensionType.MAJOR_DIVERGENCE
        
        # IA sees higher risk
        if ia_level > mcc_level:
            return TensionType.TENSION_UP
        
        # IA sees lower risk
        if ia_level < mcc_level:
            return TensionType.TENSION_DOWN
        
        return TensionType.CONVERGENCE
    
    def _determine_tension_severity(
        self,
        tension_type: TensionType,
        risk_gap: int
    ) -> TensionSeverity:
        """
        Determine the severity level of detected tension.
        
        Args:
            tension_type: Type of tension
            risk_gap: Risk level gap
            
        Returns:
            TensionSeverity enum value
        """
        if tension_type == TensionType.CONVERGENCE:
            return TensionSeverity.NONE
        
        if tension_type == TensionType.CRITICAL_ALERT:
            return TensionSeverity.CRITICAL
        
        if tension_type == TensionType.MAJOR_DIVERGENCE:
            return TensionSeverity.HIGH
        
        # For TENSION_UP and TENSION_DOWN
        if risk_gap == 1:
            return TensionSeverity.MODERATE
        elif risk_gap == 2:
            return TensionSeverity.HIGH
        elif risk_gap >= 3:
            return TensionSeverity.CRITICAL
        
        return TensionSeverity.LOW
    
    def _generate_explanation(
        self,
        tension_type: TensionType,
        mcc_risk_class: str,
        ia_risk_class: str,
        risk_gap: int
    ) -> str:
        """
        Generate concise explanation of the tension.
        
        Args:
            tension_type: Type of tension detected
            mcc_risk_class: MCC risk classification
            ia_risk_class: IA risk classification
            risk_gap: Risk level gap
            
        Returns:
            Formatted explanation string
        """
        template = self.EXPLANATION_TEMPLATES.get(
            tension_type.value,
            "Risk assessment comparison completed."
        )
        
        if tension_type == TensionType.CONVERGENCE:
            return template.format(risk_class=mcc_risk_class)
        else:
            return template.format(
                mcc_class=mcc_risk_class,
                ia_class=ia_risk_class,
                gap=risk_gap
            )
    
    def _generate_detailed_explanation(
        self,
        mcc_result: ScorecardOutputSchema,
        ia_result: IAPredictionResult,
        tension_type: TensionType,
        risk_gap: int
    ) -> str:
        """
        Generate detailed multi-paragraph explanation.
        
        Args:
            mcc_result: MCC scorecard result
            ia_result: IA prediction result
            tension_type: Type of tension
            risk_gap: Risk level gap
            
        Returns:
            Detailed explanation string
        """
        parts = []
        
        # Assessment summary
        parts.append(
            f"MCC Official Assessment: {mcc_result.final_risk_class} "
            f"(Score: {mcc_result.global_score:.2f}/5.00)"
        )
        
        parts.append(
            f"AI Model Assessment: {ia_result.ia_risk_class.value} "
            f"(Default Probability: {ia_result.ia_probability_default:.1%})"
        )
        
        # Tension analysis
        if tension_type == TensionType.CONVERGENCE:
            parts.append(
                "The AI model and MCC methodology are in agreement. "
                "Both systems identify similar risk levels, which increases "
                "confidence in the assessment."
            )
        
        elif tension_type == TensionType.TENSION_UP:
            parts.append(
                "The AI model identifies higher risk than the MCC scoring system. "
                "This could indicate:\n"
                "• Hidden patterns in financial ratios not captured by linear rules\n"
                "• Historical patterns from similar cases that defaulted\n"
                "• Non-linear interactions between financial indicators\n\n"
                "Recommendation: Review the AI feature contributions to understand "
                "which specific factors are driving the higher risk assessment."
            )
        
        elif tension_type == TensionType.TENSION_DOWN:
            parts.append(
                "The AI model assesses lower risk than the MCC scoring system. "
                "This could indicate:\n"
                "• Compensating factors identified by the ML model\n"
                "• Positive historical patterns from similar successful cases\n"
                "• Context-specific adjustments based on sector/size\n\n"
                "Caution: Do NOT automatically reduce mitigations based solely on "
                "AI assessment. The MCC framework remains the primary decision basis."
            )
        
        elif tension_type in [TensionType.MAJOR_DIVERGENCE, TensionType.CRITICAL_ALERT]:
            parts.append(
                f"⚠️ SIGNIFICANT DIVERGENCE ({risk_gap} risk levels apart)\n\n"
                "This major discrepancy requires immediate investigation:\n"
                "1. Verify data quality and completeness\n"
                "2. Check for data entry errors or outliers\n"
                "3. Review both MCC pillar scores and AI feature contributions\n"
                "4. Document the rationale for following either assessment\n"
                "5. Escalate to senior fiduciary officer for final decision\n\n"
                "The MCC scoring remains the official basis, but such large "
                "divergences warrant extra scrutiny before finalizing."
            )
        
        # Add model version info
        parts.append(
            f"\nAI Model: {ia_result.model_version} | "
            f"Analysis Date: {ia_result.predicted_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        
        return "\n\n".join(parts)
    
    def _generate_recommendations(
        self,
        tension_type: TensionType,
        tension_severity: TensionSeverity,
        mcc_risk_class: str,
        ia_risk_class: str
    ) -> List[str]:
        """
        Generate actionable recommendations based on tension analysis.
        
        Args:
            tension_type: Type of tension
            tension_severity: Severity level
            mcc_risk_class: MCC risk classification
            ia_risk_class: IA risk classification
            
        Returns:
            List of recommended actions
        """
        recommendations = []
        
        # Always include this baseline
        recommendations.append(
            "The MCC scoring remains the official decision basis. "
            "AI assessment is for challenge and validation only."
        )
        
        if tension_type == TensionType.CONVERGENCE:
            recommendations.append(
                "Both assessments converge. Proceed with standard MCC workflow."
            )
        
        elif tension_type == TensionType.TENSION_UP:
            recommendations.extend([
                "Review AI feature contributions to identify specific risk drivers",
                "Verify data quality for features with high SHAP values",
                "Consider adding specific mitigations if AI concerns are validated",
                "Document rationale if proceeding despite higher AI risk estimate"
            ])
        
        elif tension_type == TensionType.TENSION_DOWN:
            recommendations.extend([
                "Review AI explanations to understand positive signals",
                "DO NOT reduce MCC mitigations without additional evidence",
                "Consider as supplementary information only",
                "Document analyst reasoning in evaluation note"
            ])
        
        elif tension_severity in [TensionSeverity.HIGH, TensionSeverity.CRITICAL]:
            recommendations.extend([
                "🚨 MANDATORY: Escalate to senior fiduciary officer",
                "Conduct full data quality audit",
                "Review all source financial statements",
                "Verify normalization process completed correctly",
                "Request additional documentation from bidder if needed",
                "Document detailed justification before final decision",
                "Consider requesting independent audit if not already available"
            ])
        
        return recommendations
    
    def _requires_documentation(
        self,
        tension_severity: TensionSeverity,
        tension_type: TensionType
    ) -> bool:
        """
        Determine if tension requires documented justification.
        
        Args:
            tension_severity: Severity level
            tension_type: Type of tension
            
        Returns:
            True if documentation is mandatory
        """
        # Any non-convergence with moderate+ severity requires docs
        if tension_type != TensionType.CONVERGENCE:
            if tension_severity in [
                TensionSeverity.MODERATE,
                TensionSeverity.HIGH,
                TensionSeverity.CRITICAL
            ]:
                return True
        
        return False
    
    def _requires_senior_review(
        self,
        tension_severity: TensionSeverity,
        tension_type: TensionType
    ) -> bool:
        """
        Determine if tension requires senior-level review.
        
        Args:
            tension_severity: Severity level
            tension_type: Type of tension
            
        Returns:
            True if senior review is mandatory
        """
        # HIGH or CRITICAL severity always requires senior review
        if tension_severity in [TensionSeverity.HIGH, TensionSeverity.CRITICAL]:
            return True
        
        # CRITICAL_ALERT and MAJOR_DIVERGENCE always require review
        if tension_type in [TensionType.CRITICAL_ALERT, TensionType.MAJOR_DIVERGENCE]:
            return True
        
        return False
    
    def _generate_alert_message(
        self,
        tension_type: TensionType,
        tension_severity: TensionSeverity,
        mcc_risk_class: str,
        ia_risk_class: str
    ) -> Optional[str]:
        """
        Generate alert message for UI notification.
        
        Args:
            tension_type: Type of tension
            tension_severity: Severity level
            mcc_risk_class: MCC classification
            ia_risk_class: IA classification
            
        Returns:
            Alert message string or None
        """
        if tension_severity == TensionSeverity.NONE:
            return None
        
        if tension_type == TensionType.CRITICAL_ALERT:
            return (
                f"🔴 CRITICAL: Extreme mismatch detected! "
                f"MCC={mcc_risk_class}, AI={ia_risk_class}. "
                f"Senior review MANDATORY before proceeding."
            )
        
        if tension_severity == TensionSeverity.CRITICAL:
            return (
                f"🚨 HIGH SEVERITY: Major divergence between assessments. "
                f"Investigation and documentation required."
            )
        
        if tension_type == TensionType.TENSION_UP:
            return (
                f"⚠️ AI detects higher risk ({ia_risk_class}) than MCC ({mcc_risk_class}). "
                f"Review recommended."
            )
        
        if tension_type == TensionType.TENSION_DOWN:
            return (
                f"ℹ️ AI suggests lower risk ({ia_risk_class}) than MCC ({mcc_risk_class}). "
                f"Do not reduce mitigations without justification."
            )
        
        return None
    
    async def _save_tension(
        self,
        analysis: TensionAnalysis,
        model_version: str,
        db: AsyncSession
    ) -> None:
        """
        Persist tension analysis to database.
        
        Args:
            analysis: Complete tension analysis result
            model_version: AI Model version
            db: Database session
        """
        tension = IATension(
            case_id=uuid.UUID(analysis.case_id),
            mcc_risk_class=analysis.mcc_risk_class,
            ia_risk_class=analysis.ia_risk_class,
            tension_type=analysis.tension_type.value,
            tension_severity=analysis.tension_severity.value,
            explanation=analysis.explanation,
            model_version=model_version,
            prediction_source="ML_ENGINE"
        )
        
        db.add(tension)
        await db.commit()
        
        logger.info(f"Tension analysis saved for case {analysis.case_id}")
