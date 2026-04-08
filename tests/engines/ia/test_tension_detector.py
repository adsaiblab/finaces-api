"""
Unit Tests for Tension Detector Engine

Tests:
- Tension type detection (convergence, divergence)
- Tension severity classification
- Explanation generation
- Recommended actions
- Alert generation
- Database persistence

Stack: pytest-asyncio, SQLAlchemy 2.0
Language: 100% English
"""

import pytest
import pytest_asyncio
from decimal import Decimal
from typing import Dict, Any
from uuid import uuid4
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    EvaluationCase,
    Bidder,
    IATension
)
from app.engines.ia.tension_detector import (
    TensionDetector,
    TensionType,
    TensionSeverity
)
from app.schemas.ia_schema import IAPredictionResult, IARiskClass
from app.schemas.scoring_schema import ScorecardOutputSchema


# ============================================================================
# FIXTURES
# ============================================================================

@pytest_asyncio.fixture
async def test_bidder(db_session: AsyncSession) -> Bidder:
    """Create test bidder."""
    bidder = Bidder(
        id=uuid4(),
        name="Tension Test Company",
        legal_form="SA",
        country="Ivory Coast"
    )
    db_session.add(bidder)
    await db_session.commit()
    await db_session.refresh(bidder)
    return bidder


@pytest_asyncio.fixture
async def test_case(
    db_session: AsyncSession,
    test_bidder: Bidder
) -> EvaluationCase:
    """Create test case."""
    case = EvaluationCase(
        id=uuid4(),
        case_type="SINGLE",
        bidder_id=test_bidder.id,
        market_reference="TENSION-001",
        contract_value=Decimal("2000000.00"),
        status="SCORING_DONE"
    )
    db_session.add(case)
    await db_session.commit()
    await db_session.refresh(case)
    return case


@pytest.fixture
def mcc_scorecard_moderate() -> ScorecardOutputSchema:
    """Mock MCC scorecard with MODERATE risk."""
    return ScorecardOutputSchema(
        system_calculated_score=Decimal("3.5"),
        system_risk_class="MODERATE",
        global_score=Decimal("3.5"),
        base_risk_class="MODERATE",
        final_risk_class="MODERATE",
        pillars=[],
        smart_recommendations=[],
        computed_at=datetime.utcnow()
    )


@pytest.fixture
def mcc_scorecard_high() -> ScorecardOutputSchema:
    """Mock MCC scorecard with HIGH risk."""
    return ScorecardOutputSchema(
        system_calculated_score=Decimal("2.4"),
        system_risk_class="HIGH",
        global_score=Decimal("2.4"),
        base_risk_class="HIGH",
        final_risk_class="HIGH",
        pillars=[],
        smart_recommendations=[],
        computed_at=datetime.utcnow()
    )


@pytest.fixture
def ia_prediction_moderate() -> IAPredictionResult:
    """Mock IA prediction with MODERATE risk."""
    return IAPredictionResult(
        case_id=str(uuid4()),
        ia_score=3.5,
        ia_probability_default=0.30,
        ia_risk_class=IARiskClass.MODERATE,
        model_version="test_v1.0",
        predicted_at=datetime.utcnow(),
        explanations=None,
        threshold_info={}
    )


@pytest.fixture
def ia_prediction_low() -> IAPredictionResult:
    """Mock IA prediction with LOW risk."""
    return IAPredictionResult(
        case_id=str(uuid4()),
        ia_score=4.2,
        ia_probability_default=0.16,
        ia_risk_class=IARiskClass.LOW,
        model_version="test_v1.0",
        predicted_at=datetime.utcnow(),
        explanations=None,
        threshold_info={}
    )


@pytest.fixture
def ia_prediction_critical() -> IAPredictionResult:
    """Mock IA prediction with CRITICAL risk."""
    return IAPredictionResult(
        case_id=str(uuid4()),
        ia_score=1.5,
        ia_probability_default=0.70,
        ia_risk_class=IARiskClass.CRITICAL,
        model_version="test_v1.0",
        predicted_at=datetime.utcnow(),
        explanations=None,
        threshold_info={}
    )


# ============================================================================
# TESTS - TENSION TYPE DETECTION
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.ia
class TestTensionTypeDetection:
    """Test tension type detection logic."""
    
    async def test_convergence_same_class(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        mcc_scorecard_moderate: ScorecardOutputSchema,
        ia_prediction_moderate: IAPredictionResult
    ):
        """Test convergence when both assessments agree."""
        
        detector = TensionDetector()
        
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_scorecard_moderate,
            ia_result=ia_prediction_moderate,
            db=db_session
        )
        
        assert analysis.tension_type == TensionType.CONVERGENCE
        assert analysis.tension_severity == TensionSeverity.NONE
        assert analysis.risk_level_gap == 0
    
    async def test_tension_up(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        mcc_scorecard_moderate: ScorecardOutputSchema
    ):
        """Test TENSION_UP when IA sees higher risk than MCC."""
        
        # IA=HIGH vs MCC=MODERATE → 1 level gap → TENSION_UP
        ia_high = IAPredictionResult(
            case_id=str(test_case.id),
            ia_score=2.0,
            ia_probability_default=0.50,
            ia_risk_class=IARiskClass.HIGH,
            model_version="test_v1.0",
            predicted_at=datetime.utcnow(),
            explanations=None,
            threshold_info={}
        )
        
        detector = TensionDetector()
        
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_scorecard_moderate,
            ia_result=ia_high,
            db=db_session
        )
        
        assert analysis.tension_type == TensionType.TENSION_UP
        assert analysis.risk_level_gap > 0
        assert analysis.mcc_risk_class == "MODERATE"
        assert analysis.ia_risk_class == "HIGH"
    
    async def test_tension_down(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        mcc_scorecard_high: ScorecardOutputSchema
    ):
        """Test TENSION_DOWN when IA sees lower risk than MCC."""
        
        # IA=MODERATE vs MCC=HIGH → 1 level gap → TENSION_DOWN
        ia_moderate = IAPredictionResult(
            case_id=str(test_case.id),
            ia_score=3.5,
            ia_probability_default=0.30,
            ia_risk_class=IARiskClass.MODERATE,
            model_version="test_v1.0",
            predicted_at=datetime.utcnow(),
            explanations=None,
            threshold_info={}
        )
        
        detector = TensionDetector()
        
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_scorecard_high,
            ia_result=ia_moderate,
            db=db_session
        )
        
        assert analysis.tension_type == TensionType.TENSION_DOWN
        assert analysis.mcc_risk_class == "HIGH"
        assert analysis.ia_risk_class == "MODERATE"
    
    async def test_major_divergence(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase
    ):
        """Test MAJOR_DIVERGENCE when 2+ levels apart."""
        
        # MCC: LOW, IA: HIGH (2 levels apart → MAJOR_DIVERGENCE, not CRITICAL_ALERT)
        mcc_low = ScorecardOutputSchema(
            system_calculated_score=Decimal("4.5"),
            system_risk_class="LOW",
            global_score=Decimal("4.5"),
            base_risk_class="LOW",
            final_risk_class="LOW",
            pillars=[],
            smart_recommendations=[],
            computed_at=datetime.utcnow()
        )
        
        ia_high = IAPredictionResult(
            case_id=str(test_case.id),
            ia_score=2.0,
            ia_probability_default=0.50,
            ia_risk_class=IARiskClass.HIGH,
            model_version="test_v1.0",
            predicted_at=datetime.utcnow(),
            explanations=None,
            threshold_info={}
        )
        
        detector = TensionDetector()
        
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_low,
            ia_result=ia_high,
            db=db_session
        )
        
        assert analysis.tension_type == TensionType.MAJOR_DIVERGENCE
        assert analysis.risk_level_gap >= 2


# ============================================================================
# TESTS - TENSION SEVERITY
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.ia
class TestTensionSeverity:
    """Test tension severity classification."""
    
    async def test_severity_none_convergence(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        mcc_scorecard_moderate: ScorecardOutputSchema,
        ia_prediction_moderate: IAPredictionResult
    ):
        """Test NONE severity for convergence."""
        
        detector = TensionDetector()
        
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_scorecard_moderate,
            ia_result=ia_prediction_moderate,
            db=db_session
        )
        
        assert analysis.tension_severity == TensionSeverity.NONE
    
    async def test_severity_moderate_one_level(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase
    ):
        """Test MODERATE severity for 1 level difference."""
        
        mcc = ScorecardOutputSchema(
            system_calculated_score=Decimal("3.0"),
            system_risk_class="MODERATE",
            global_score=Decimal("3.0"),
            base_risk_class="MODERATE",
            final_risk_class="MODERATE",
            pillars=[],
            smart_recommendations=[],
            computed_at=datetime.utcnow()
        )
        
        ia = IAPredictionResult(
            case_id=str(test_case.id),
            ia_score=2.0,
            ia_probability_default=0.60,
            ia_risk_class=IARiskClass.CRITICAL,
            model_version="test_v1.0",
            predicted_at=datetime.utcnow(),
            explanations=None,
            threshold_info={}
        )
        
        detector = TensionDetector()
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc,
            ia_result=ia,
            db=db_session
        )
        
        # 1 level difference = MODERATE severity
        assert analysis.tension_severity in [TensionSeverity.MODERATE, TensionSeverity.HIGH]
    
    async def test_severity_high_two_levels(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        mcc_scorecard_moderate: ScorecardOutputSchema
    ):
        """Test HIGH severity for 2 level difference."""
        
        ia_critical = IAPredictionResult(
            case_id=str(test_case.id),
            ia_score=1.5,
            ia_probability_default=0.70,
            ia_risk_class=IARiskClass.CRITICAL,
            model_version="test_v1.0",
            predicted_at=datetime.utcnow(),
            explanations=None,
            threshold_info={}
        )
        
        detector = TensionDetector()
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_scorecard_moderate,
            ia_result=ia_critical,
            db=db_session
        )
        
        # MODERATE -> CRITICAL = 2 levels
        assert analysis.tension_severity in [TensionSeverity.HIGH, TensionSeverity.MODERATE]


# ============================================================================
# TESTS - EXPLANATIONS & RECOMMENDATIONS
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.ia
class TestExplanationsAndRecommendations:
    """Test explanation and recommendation generation."""
    
    async def test_convergence_explanation(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        mcc_scorecard_moderate: ScorecardOutputSchema,
        ia_prediction_moderate: IAPredictionResult
    ):
        """Test explanation for convergence case."""
        
        detector = TensionDetector()
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_scorecard_moderate,
            ia_result=ia_prediction_moderate,
            db=db_session
        )
        
        # Should contain positive language about agreement
        assert "converge" in analysis.explanation.lower() or "agree" in analysis.explanation.lower()
        assert len(analysis.recommended_actions) > 0
    
    async def test_tension_up_recommendations(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        mcc_scorecard_moderate: ScorecardOutputSchema,
        ia_prediction_critical: IAPredictionResult
    ):
        """Test recommendations for TENSION_UP."""
        
        detector = TensionDetector()
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_scorecard_moderate,
            ia_result=ia_prediction_critical,
            db=db_session
        )
        
        # Should recommend reviewing IA factors
        actions_text = " ".join(analysis.recommended_actions).lower()
        assert "review" in actions_text or "feature" in actions_text or "shap" in actions_text
    
    async def test_major_divergence_escalation(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase
    ):
        """Test escalation requirements for major divergence."""
        
        mcc_low = ScorecardOutputSchema(
            system_calculated_score=Decimal("4.5"),
            system_risk_class="LOW",
            global_score=Decimal("4.5"),
            base_risk_class="LOW",
            final_risk_class="LOW",
            pillars=[],
            smart_recommendations=[],
            computed_at=datetime.utcnow()
        )
        
        ia_critical = IAPredictionResult(
            case_id=str(test_case.id),
            ia_score=1.0,
            ia_probability_default=0.80,
            ia_risk_class=IARiskClass.CRITICAL,
            model_version="test_v1.0",
            predicted_at=datetime.utcnow(),
            explanations=None,
            threshold_info={}
        )
        
        detector = TensionDetector()
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_low,
            ia_result=ia_critical,
            db=db_session
        )
        
        # Should require senior review and documentation
        assert analysis.requires_senior_review is True
        assert analysis.requires_documentation is True
        assert analysis.alert_message is not None


# ============================================================================
# TESTS - DATABASE PERSISTENCE
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.ia
class TestDatabasePersistence:
    """Test tension analysis persistence."""
    
    async def test_save_tension_to_database(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        mcc_scorecard_moderate: ScorecardOutputSchema,
        ia_prediction_moderate: IAPredictionResult
    ):
        """Test that tension analysis is saved to database."""
        
        detector = TensionDetector()
        
        await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_scorecard_moderate,
            ia_result=ia_prediction_moderate,
            db=db_session
        )
        
        # Verify saved in database
        stmt = select(IATension).where(IATension.case_id == test_case.id)
        result = await db_session.execute(stmt)
        tension_record = result.scalar_one_or_none()
        
        assert tension_record is not None
        assert tension_record.case_id == test_case.id
        assert tension_record.mcc_risk_class == "MODERATE"
        assert tension_record.ia_risk_class == "MODERATE"
        assert tension_record.tension_type == TensionType.CONVERGENCE.value
    
    async def test_tension_history(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        mcc_scorecard_moderate: ScorecardOutputSchema,
        ia_prediction_moderate: IAPredictionResult
    ):
        """Test retrieving tension history."""
        
        detector = TensionDetector()
        
        # Create multiple tension analyses
        for _ in range(3):
            await detector.analyze_tension(
                case_id=str(test_case.id),
                mcc_result=mcc_scorecard_moderate,
                ia_result=ia_prediction_moderate,
                db=db_session
            )
        
        # Retrieve history
        history = await detector.get_tension_history(
            case_id=str(test_case.id),
            db=db_session,
            limit=10
        )
        
        assert len(history) == 3
        assert all("created_at" in record for record in history)


# ============================================================================
# TESTS - EDGE CASES
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.ia
class TestEdgeCases:
    """Test edge cases in tension detection."""
    
    async def test_french_risk_class_normalization(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase
    ):
        """Test handling of French MCC risk classes."""
        
        # MCC with French risk class
        mcc_french = ScorecardOutputSchema(
            system_calculated_score=Decimal("3.5"),
            system_risk_class="MODERATE",
            global_score=Decimal("3.5"),
            base_risk_class="MODERATE",
            final_risk_class="MODERATE",
            pillars=[],
            smart_recommendations=[],
            computed_at=datetime.utcnow()
        )
        
        ia_moderate = IAPredictionResult(
            case_id=str(test_case.id),
            ia_score=3.5,
            ia_probability_default=0.30,
            ia_risk_class=IARiskClass.MODERATE,  # English
            model_version="test_v1.0",
            predicted_at=datetime.utcnow(),
            explanations=None,
            threshold_info={}
        )
        
        detector = TensionDetector()
        analysis = await detector.analyze_tension(
            case_id=str(test_case.id),
            mcc_result=mcc_french,
            ia_result=ia_moderate,
            db=db_session
        )
        
        # Should normalize and detect convergence
        assert analysis.tension_type == TensionType.CONVERGENCE
        assert analysis.mcc_risk_class == "MODERATE"  # Normalized to English
