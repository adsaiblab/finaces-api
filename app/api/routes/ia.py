"""
AI Module API Routes

FastAPI routes for AI scoring functionality including:
- Feature computation
- AI predictions
- Tension detection (MCC vs IA comparison)
- Model management
- Historical analysis

Stack: FastAPI, SQLAlchemy 2.0 Async, Pydantic V2, PostgreSQL
Language: 100% English
"""

from typing import List, Optional, Dict, Any
from pathlib import Path
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.database import get_db
from app.core.security import get_current_user
from app.db.models import (
    EvaluationCase,
    IAModel,
    IAPrediction,
    IAFeatures,
    IATension,
    Scorecard
)
from app.engines.ia.feature_engineering import FeatureEngineeringEngine
from app.engines.ia.predictor import IAPredictor
from app.engines.ia.tension_detector import TensionDetector
from app.services.ia_service import generate_and_save_ia_features
from app.schemas.ia_schema import (
    IAPredictionResult,
    IAFeaturesResponse,
    IARiskClass
)
from app.exceptions.finaces_exceptions import (
    MissingFinancialDataError,
    InsufficientFiscalYearsError,
    CaseNotFoundError
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ia", tags=["AI Scoring"])


# ============================================================================
# FEATURE ENGINEERING ENDPOINTS
# ============================================================================

@router.post(
    "/features/{case_id}",
    response_model=IAFeaturesResponse,
    status_code=status.HTTP_200_OK,
    summary="Compute AI features for a case",
    description=(
        "Compute all 40+ financial features from normalized accounting data. "
        "Features are automatically cached in the database for future use."
    )
)
async def compute_features(
    case_id: str,
    force_recompute: bool = Query(
        False,
        description="Force recomputation even if cached features exist"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> IAFeaturesResponse:
    """
    Compute AI features for a given evaluation case.
    
    Features include:
    - Liquidity ratios (current_ratio, quick_ratio, cash_ratio, etc.)
    - Solvency ratios (debt_to_equity, equity_ratio, etc.)
    - Profitability metrics (ROA, ROE, margins, etc.)
    - Contractual capacity indicators
    - Quality/reliability scores
    - Trend analysis (multi-year)
    
    Args:
        case_id: Unique identifier of the evaluation case
        force_recompute: If True, ignore cached features and recompute
        db: Database session (injected)
        current_user: Authenticated user (injected)
        
    Returns:
        IAFeaturesResponse with all computed features and metadata
        
    Raises:
        404: Case not found
        400: Insufficient data (less than 2 fiscal years)
        500: Feature computation error
    """
    logger.info(
        f"Feature computation requested for case {case_id} by user {current_user.get('email')}"
    )
    
    # Verify case exists
    case = await _get_case_or_404(case_id, db)
    
    # Check for cached features if not forcing recompute
    if not force_recompute:
        cached_features = await _get_cached_features(case_id, db)
        if cached_features:
            logger.info(f"Returning cached features for case {case_id}")
            return IAFeaturesResponse(**cached_features.features)
    
    # Compute features
    try:
        # Call the service that computes AND saves features
        features_data = await generate_and_save_ia_features(uuid.UUID(case_id), db)

        logger.info(
            f"Features computed successfully for case {case_id}. "
            f"Count: {features_data['metadata']['feature_count']}"
        )

        return IAFeaturesResponse(**features_data)
    
    except InsufficientFiscalYearsError as e:
        logger.warning(f"Insufficient data for case {case_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "insufficient_data",
                "message": str(e),
                "requirement": "At least 2 fiscal years of financial statements required"
            }
        )
    
    except MissingFinancialDataError as e:
        logger.error(f"Missing financial data for case {case_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "missing_financial_data",
                "message": str(e)
            }
        )
    
    except Exception as e:
        logger.exception(f"Feature computation failed for case {case_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "feature_computation_failed",
                "message": "An error occurred during feature computation",
                "details": str(e)
            }
        )


@router.get(
    "/features/{case_id}",
    response_model=IAFeaturesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get cached AI features",
    description="Retrieve previously computed features from cache"
)
async def get_cached_features(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> IAFeaturesResponse:
    """
    Retrieve cached features for a case.
    
    Args:
        case_id: Case identifier
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Cached features if available
        
    Raises:
        404: Case not found or no cached features
    """
    cached_features = await _get_cached_features(case_id, db)
    
    if not cached_features:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no_cached_features",
                "message": f"No cached features found for case {case_id}",
                "hint": "Use POST /ia/features/{case_id} to compute features"
            }
        )
    
    return IAFeaturesResponse(**cached_features.features)


# ============================================================================
# AI PREDICTION ENDPOINTS
# ============================================================================

@router.post(
    "/predict/{case_id}",
    response_model=IAPredictionResult,
    status_code=status.HTTP_200_OK,
    summary="Generate AI prediction",
    description=(
        "Generate AI-based risk prediction using trained ML model. "
        "Returns probability of default, risk classification, and explanations."
    )
)
async def predict_risk(
    case_id: str,
    use_cached_features: bool = Query(
        True,
        description="Use cached features if available"
    ),
    enable_explanations: bool = Query(
        True,
        description="Generate SHAP explanations (may be slower)"
    ),
    model_version: Optional[str] = Query(
        None,
        description="Specific model version to use (defaults to active model)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> IAPredictionResult:
    """
    Generate AI risk prediction for a case.
    
    The AI prediction:
    - Uses XGBoost/LightGBM trained on historical data
    - Outputs probability of default (0-1 scale)
    - Classifies risk as LOW/MODERATE/HIGH/CRITICAL
    - Provides SHAP-based feature importance explanations
    
    **Important**: This is a supplementary assessment only.
    The official MCC scoring remains the decision basis.
    
    Args:
        case_id: Case identifier
        use_cached_features: Whether to use cached features
        enable_explanations: Whether to compute SHAP values
        model_version: Optional specific model version
        db: Database session
        current_user: Authenticated user
        
    Returns:
        IAPredictionResult with score, risk class, and explanations
        
    Raises:
        404: Case not found or no active model
        400: Insufficient data or features
        500: Prediction error
    """
    logger.info(
        f"AI prediction requested for case {case_id} by user {current_user.get('email')}"
    )
    
    # Verify case exists
    case = await _get_case_or_404(case_id, db)
    
    try:
        # Initialize predictor
        predictor = IAPredictor(
            model_type="xgboost",  # Could be configurable
            enable_explanations=enable_explanations
        )
        
        # Load specific model version if requested
        if model_version:
            model = await _get_model_by_version(model_version, db)
            if not model:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Model version {model_version} not found"
                )
            predictor.model_manager.load(Path(model.file_path))
        
        # Generate prediction
        result = await predictor.predict(
            case_id=case_id,
            db=db,
            use_cached_features=use_cached_features
        )
        
        logger.info(
            f"Prediction completed for case {case_id}. "
            f"Risk: {result.ia_risk_class}, Probability: {result.ia_probability_default:.4f}"
        )
        
        return result
    
    except InsufficientFiscalYearsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "insufficient_data",
                "message": str(e)
            }
        )
    
    except FileNotFoundError as e:
        logger.error(f"Model file not found: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "model_not_found",
                "message": "No trained model available. Contact administrator.",
                "hint": "Models must be trained and registered before use"
            }
        )
    
    except Exception as e:
        logger.exception(f"Prediction failed for case {case_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "prediction_failed",
                "message": "An error occurred during AI prediction",
                "details": str(e)
            }
        )


@router.get(
    "/predict/{case_id}",
    response_model=IAPredictionResult,
    status_code=status.HTTP_200_OK,
    summary="Get latest AI prediction",
    description="Retrieve the most recent AI prediction from database"
)
async def get_latest_prediction(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> IAPredictionResult:
    """
    Retrieve the latest cached prediction for a case.
    
    Args:
        case_id: Case identifier
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Latest prediction result
        
    Raises:
        404: No prediction found for case
    """
    stmt = (
        select(IAPrediction)
        .where(IAPrediction.case_id == uuid.UUID(case_id))
        .order_by(IAPrediction.created_at.desc())
    )
    
    result = await db.execute(stmt)
    prediction = result.scalars().first()
    
    if not prediction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no_prediction",
                "message": f"No AI prediction found for case {case_id}",
                "hint": "Use POST /ia/predict/{case_id} to generate a prediction"
            }
        )
    
    # Convert to response schema
    return IAPredictionResult(
        case_id=str(prediction.case_id),
        ia_score=float(prediction.ia_score),
        ia_probability_default=float(prediction.ia_probability_default),
        ia_risk_class=IARiskClass(prediction.ia_risk_class),
        model_version=prediction.model_version,
        predicted_at=prediction.created_at,
        explanations=None,  # Explanations not stored in DB
        threshold_info={}
    )


# ============================================================================
# DUAL SCORING ENDPOINT (MCC + IA + TENSION)
# ============================================================================

@router.post(
    "/dual-scoring/{case_id}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Complete dual scoring (MCC + IA)",
    description=(
        "Execute both MCC and AI scoring, then perform tension analysis. "
        "This is the main endpoint for integrated risk assessment."
    )
)
async def dual_scoring(
    case_id: str,
    force_recompute_mcc: bool = Query(
        False,
        description="Force MCC scorecard recomputation"
    ),
    force_recompute_ia: bool = Query(
        False,
        description="Force IA prediction recomputation"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Execute complete dual scoring pipeline.
    
    **Pipeline:**
    1. MCC Official Scoring (5 pillars)
    2. AI Risk Prediction (ML model)
    3. Tension Detection (MCC vs IA comparison)
    4. Recommendations generation
    
    **Use Case:**
    This endpoint provides the complete view needed for analyst
    decision-making, showing both traditional and AI-based assessments
    side-by-side with automatic conflict detection.
    
    Args:
        case_id: Case identifier
        force_recompute_mcc: Recompute MCC scorecard
        force_recompute_ia: Recompute IA prediction
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Complete dual scoring result with:
        - mcc: Official MCC scorecard
        - ia: AI prediction with explanations
        - tension: Tension analysis and recommendations
        - metadata: Processing timestamps and versions
        
    Raises:
        404: Case not found
        400: Insufficient data
        500: Processing error
    """
    logger.info(
        f"Dual scoring requested for case {case_id} by user {current_user.get('email')}"
    )
    
    # Verify case exists
    case = await _get_case_or_404(case_id, db)
    
    try:
        # 1. MCC Official Scoring
        mcc_result = await _get_or_compute_mcc_scorecard(
            case_id, db, force_recompute_mcc
        )
        
        # 2. AI Prediction
        ia_predictor = IAPredictor(enable_explanations=True)
        ia_result = await ia_predictor.predict(
            case_id=case_id,
            db=db,
            use_cached_features=not force_recompute_ia
        )
        
        # 3. Tension Detection
        tension_detector = TensionDetector()
        tension_analysis = await tension_detector.analyze_tension(
            case_id=case_id,
            mcc_result=mcc_result,
            ia_result=ia_result,
            db=db
        )
        
        # 4. Assemble response
        response = {
            "case_id": case_id,
            "mcc_assessment": {
                "global_score": mcc_result.global_score,
                "risk_class": mcc_result.final_risk_class,
                "pillar_scores": mcc_result.pillar_scores,
                "overrides_applied": mcc_result.overrides_applied or []
            },
            "ia_assessment": {
                "score": ia_result.ia_score,
                "probability_default": ia_result.ia_probability_default,
                "risk_class": ia_result.ia_risk_class.value,
                "model_version": ia_result.model_version,
                "explanations": ia_result.explanations.dict() if ia_result.explanations else None
            },
            "tension_analysis": tension_analysis.to_dict(),
            "metadata": {
                "computed_at": datetime.utcnow().isoformat(),
                "mcc_version": mcc_result.policy_version_id,
                "ia_model_version": ia_result.model_version,
                "user": current_user.get("email")
            }
        }
        
        logger.info(
            f"Dual scoring completed for case {case_id}. "
            f"MCC: {mcc_result.final_risk_class}, IA: {ia_result.ia_risk_class.value}, "
            f"Tension: {tension_analysis.tension_type.value}"
        )
        
        return response
    
    except Exception as e:
        logger.exception(f"Dual scoring failed for case {case_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "dual_scoring_failed",
                "message": str(e)
            }
        )


# ============================================================================
# TENSION ANALYSIS ENDPOINTS
# ============================================================================

@router.get(
    "/tension/{case_id}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get latest tension analysis",
    description="Retrieve the most recent MCC vs IA tension analysis"
)
async def get_tension_analysis(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Retrieve latest tension analysis for a case.
    
    Args:
        case_id: Case identifier
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Latest tension analysis
        
    Raises:
        404: No tension analysis found
    """
    stmt = (
        select(IATension)
        .where(IATension.case_id == uuid.UUID(case_id))
        .order_by(IATension.created_at.desc())
    )
    
    result = await db.execute(stmt)
    tension = result.scalars().first()
    
    if not tension:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no_tension_analysis",
                "message": f"No tension analysis found for case {case_id}",
                "hint": "Use POST /ia/dual-scoring/{case_id} to generate analysis"
            }
        )
    
    return {
        "case_id": str(tension.case_id),
        "mcc_risk_class": tension.mcc_risk_class,
        "ia_risk_class": tension.ia_risk_class,
        "tension_type": tension.tension_type,
        "explanation": tension.explanation,
        "created_at": tension.created_at.isoformat()
    }


@router.get(
    "/tension/{case_id}/history",
    response_model=List[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="Get tension history",
    description="Retrieve historical tension analyses for trend tracking"
)
async def get_tension_history(
    case_id: str,
    limit: int = Query(10, ge=1, le=100, description="Maximum records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Retrieve tension analysis history for a case.
    
    Useful for tracking how assessments evolved over time,
    especially if data or models were updated.
    
    Args:
        case_id: Case identifier
        limit: Maximum number of records
        db: Database session
        current_user: Authenticated user
        
    Returns:
        List of historical tension analyses
    """
    detector = TensionDetector()
    history = await detector.get_tension_history(case_id, db, limit)
    
    return history


# ============================================================================
# MODEL MANAGEMENT ENDPOINTS
# ============================================================================

@router.get(
    "/models",
    response_model=List[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="List available AI models",
    description="List all registered AI models with their metadata"
)
async def list_models(
    active_only: bool = Query(False, description="Return only active models"),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    List available AI models.
    
    Args:
        active_only: Filter to active models only
        db: Database session
        current_user: Authenticated user
        
    Returns:
        List of model metadata
    """
    stmt = select(IAModel).order_by(IAModel.created_at.desc())
    
    if active_only:
        stmt = stmt.where(IAModel.is_active == True)
    
    result = await db.execute(stmt)
    models = result.scalars().all()
    
    return [
        {
            "id": str(model.id),
            "model_name": model.model_name,
            "version": model.version,
            "file_path": model.file_path,
            "metrics": model.metrics,
            "is_active": model.is_active,
            "created_at": model.created_at.isoformat()
        }
        for model in models
    ]


@router.get(
    "/models/active",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get active model",
    description="Get currently active AI model information"
)
async def get_active_model(
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get currently active model.
    
    Args:
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Active model metadata
        
    Raises:
        404: No active model found
    """
    stmt = (
        select(IAModel)
        .where(IAModel.is_active == True)
        .order_by(IAModel.created_at.desc())
    )
    
    result = await db.execute(stmt)
    model = result.scalars().first()
    
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no_active_model",
                "message": "No active AI model found. Contact administrator."
            }
        )
    
    return {
        "id": str(model.id),
        "model_name": model.model_name,
        "version": model.version,
        "metrics": model.metrics,
        "created_at": model.created_at.isoformat()
    }


# ============================================================================
# STATISTICS ENDPOINTS
# ============================================================================

@router.get(
    "/stats/predictions",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get prediction statistics",
    description="Get aggregate statistics on AI predictions"
)
async def get_prediction_stats(
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get aggregate prediction statistics.
    
    Returns distribution of risk classes, average scores,
    and prediction counts.
    
    Args:
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Statistics dictionary
    """
    # Total predictions
    total_stmt = select(func.count(IAPrediction.id))
    total_result = await db.execute(total_stmt)
    total_count = total_result.scalar()
    
    # Distribution by risk class
    dist_stmt = (
        select(
            IAPrediction.ia_risk_class,
            func.count(IAPrediction.id).label("count")
        )
        .group_by(IAPrediction.ia_risk_class)
    )
    dist_result = await db.execute(dist_stmt)
    distribution = {row[0]: row[1] for row in dist_result}
    
    # Average probability
    avg_stmt = select(func.avg(IAPrediction.ia_probability_default))
    avg_result = await db.execute(avg_stmt)
    avg_probability = avg_result.scalar() or 0.0
    
    return {
        "total_predictions": total_count,
        "risk_class_distribution": distribution,
        "average_default_probability": round(float(avg_probability), 4)
    }


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

async def _get_case_or_404(
    case_id: str,
    db: AsyncSession
) -> EvaluationCase:
    """Get case or raise 404."""
    stmt = select(EvaluationCase).where(EvaluationCase.id == uuid.UUID(case_id))
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "case_not_found",
                "message": f"Evaluation case {case_id} not found"
            }
        )
    
    return case


async def _get_cached_features(
    case_id: str,
    db: AsyncSession
) -> Optional[IAFeatures]:
    """Get most recent cached features."""
    stmt = (
        select(IAFeatures)
        .where(IAFeatures.case_id == uuid.UUID(case_id))
        .order_by(IAFeatures.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_model_by_version(
    version: str,
    db: AsyncSession
) -> Optional[IAModel]:
    """Get model by version string."""
    stmt = select(IAModel).where(IAModel.version == version)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_or_compute_mcc_scorecard(
    case_id: str,
    db: AsyncSession,
    force_recompute: bool
):
    """Get cached scorecard or compute new one."""
    from app.services.scoring_service import ScoringService
    
    if not force_recompute:
        # Try to get cached
        stmt = (
            select(Scorecard)
            .where(Scorecard.case_id == uuid.UUID(case_id))
            .order_by(Scorecard.created_at.desc())
        )
        result = await db.execute(stmt)
        scorecard = result.scalars().first()
        
        if scorecard:
            # Convert to response schema
            from app.schemas.scoring_schema import ScorecardOutputSchema
            return ScorecardOutputSchema.model_validate(scorecard)
    
    # Compute fresh
    scoring_service = ScoringService()
    return await scoring_service.compute_scorecard(case_id, db)
