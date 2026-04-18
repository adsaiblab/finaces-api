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
from datetime import datetime
import logging
import uuid
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi_limiter.depends import RateLimiter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.database import get_db
from app.core.security import get_current_user
from app.core.audit import data_access_sensitive
from app.db.models import (
    EvaluationCase,
    IAModel,
    IAPrediction,
    IAFeatures,
    IATension,
    Scorecard
)
from app.engines.ia.feature_engineering import FeatureEngineeringEngine
from app.engines.ia.predictor import IAPredictor, IARiskClassifier
from app.engines.ia.tension_detector import TensionDetector
from app.services.ia_service import generate_and_save_ia_features
from app.schemas.ia_schema import (
    IAPredictionResult,
    IAFeaturesResponse,
    IARiskClass,
    IAFeatureContribution,
    WhatIfInput,
    WhatIfResult,
)
from app.exceptions.finaces_exceptions import (
    MissingFinancialDataError,
    InsufficientFiscalYearsError,
    CaseNotFoundError
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ia", tags=["AI Scoring"])

# Rate limit applied to all costly POST routes (ML inference, feature computation).
# Keys on client IP — see NOTE in auth.py about reverse proxy X-Forwarded-For.
_IA_RATE_LIMIT = [Depends(RateLimiter(times=20, seconds=60))]


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
    ),
    dependencies=_IA_RATE_LIMIT,
)
async def compute_features(
    case_id: uuid.UUID,
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
        features_data = await generate_and_save_ia_features(str(case_id), db)
        
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
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> IAFeaturesResponse:
    """
    Retrieve cached features for a case.
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
    ),
    dependencies=_IA_RATE_LIMIT,
)
async def predict_risk(
    case_id: uuid.UUID,
    request: Request,
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
    """
    logger.info(
        f"AI prediction requested for case {case_id} by user {current_user.get('sub')}"
    )

    data_access_sensitive(
        user_email=current_user.get("sub", "unknown"),
        path=request.url.path,
        case_id=str(case_id),
    )
    
    # Verify case exists
    case = await _get_case_or_404(case_id, db)
    
    try:
        # Initialize predictor
        predictor = IAPredictor(
            model_type="xgboost",
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
    except Exception as e:
        logger.exception(f"Prediction failed for case {case_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "prediction_failed", "message": str(e)}
        )


@router.get(
    "/predict/{case_id}",
    response_model=IAPredictionResult,
    status_code=status.HTTP_200_OK,
    summary="Get latest AI prediction",
    description="Retrieve the most recent AI prediction from database"
)
async def get_latest_prediction(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> IAPredictionResult:
    """
    Retrieve the latest cached prediction for a case.
    """
    stmt = (
        select(IAPrediction)
        .where(IAPrediction.case_id == case_id)
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
    
    return IAPredictionResult(
        case_id=str(prediction.case_id),
        ia_score=float(prediction.ia_score or 0),
        ia_probability_default=float(prediction.ia_probability_default or 0),
        ia_risk_class=IARiskClass(prediction.ia_risk_class),
        model_version=prediction.model_version,
        predicted_at=prediction.created_at,
        explanations=None,
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
    ),
    dependencies=_IA_RATE_LIMIT,
)
async def dual_scoring(
    case_id: uuid.UUID,
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
    """
    logger.info(
        f"Dual scoring requested for case {case_id} by user {current_user.get('sub')}"
    )
    
    case = await _get_case_or_404(case_id, db)
    
    try:
        mcc_result = await _get_or_compute_mcc_scorecard(
            case_id, db, force_recompute_mcc
        )
        
        ia_predictor = IAPredictor(enable_explanations=True)
        ia_result = await ia_predictor.predict(
            case_id=case_id,
            db=db,
            use_cached_features=not force_recompute_ia
        )
        
        tension_detector = TensionDetector()
        tension_analysis = await tension_detector.analyze_tension(
            case_id=case_id,
            mcc_result=mcc_result,
            ia_result=ia_result,
            db=db
        )
        
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
                "explanations": ia_result.explanations.model_dump() if ia_result.explanations else None
            },
            "tension_analysis": tension_analysis.to_dict(),
            "metadata": {
                "computed_at": datetime.utcnow().isoformat(),
                "mcc_version": mcc_result.policy_version_id,
                "ia_model_version": ia_result.model_version,
                "user": current_user.get("sub")
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
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> Dict[str, Any]:
    stmt = (
        select(IATension)
        .where(IATension.case_id == case_id)
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
    case_id: uuid.UUID,
    limit: int = Query(10, ge=1, le=100, description="Maximum records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    detector = TensionDetector()
    history = await detector.get_tension_history(str(case_id), db, limit)
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
    total_stmt = select(func.count(IAPrediction.id))
    total_result = await db.execute(total_stmt)
    total_count = total_result.scalar()
    
    dist_stmt = (
        select(
            IAPrediction.ia_risk_class,
            func.count(IAPrediction.id).label("count")
        )
        .group_by(IAPrediction.ia_risk_class)
    )
    dist_result = await db.execute(dist_stmt)
    distribution = {row[0]: row[1] for row in dist_result}
    
    avg_stmt = select(func.avg(IAPrediction.ia_probability_default))
    avg_result = await db.execute(avg_stmt)
    avg_probability = avg_result.scalar() or 0.0
    
    return {
        "total_predictions": total_count,
        "risk_class_distribution": distribution,
        "average_default_probability": round(float(avg_probability), 4)
    }


# ============================================================================
# WHAT-IF SIMULATION ENDPOINT
# ============================================================================

@router.post(
    "/cases/{case_id}/simulate",
    response_model=WhatIfResult,
    status_code=status.HTTP_200_OK,
    summary="What-If simulation for IA prediction",
    description=(
        "Run a What-If scenario by overriding specific financial features "
        "and observing the impact on the AI risk score without persisting any result. "
        "Requires at least one parameter override."
    ),
    dependencies=_IA_RATE_LIMIT,
)
async def simulate_what_if(
    case_id: uuid.UUID,
    payload: WhatIfInput,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
) -> WhatIfResult:
    """
    Execute a What-If simulation on AI features.

    Pipeline:
    1. Load baseline features from cache (or compute if absent)
    2. Compute baseline prediction (probability + risk class) — no DB persist
    3. Apply parameter_overrides on top of baseline features
    4. Run model inference on the overridden features — no DB persist
    5. Classify overridden result and compute delta
    6. Build feature_impacts from SHAP values on overridden features

    Nothing is written to the database: this is a simulation only.
    """
    logger.info(
        f"What-If simulation '{payload.scenario_name}' requested for case {case_id} "
        f"by user {current_user.get('sub')} "
        f"with {len(payload.parameter_overrides)} override(s)"
    )

    await _get_case_or_404(case_id, db)

    try:
        predictor = IAPredictor(model_type="xgboost", enable_explanations=False)
        await predictor._load_active_model(db)

        features_data = await predictor._get_or_compute_features(
            case_id, db, use_cached=True
        )
        baseline_features: Dict[str, Any] = dict(features_data["features"])

        baseline_probability = predictor.model_manager.predict_proba(baseline_features)
        baseline_score = round(baseline_probability * 100, 2)
        baseline_class = IARiskClassifier.classify(baseline_probability)

        known_features = set(predictor.model_manager.feature_names or [])
        effective_overrides: Dict[str, float] = {
            k: v
            for k, v in payload.parameter_overrides.items()
            if not known_features or k in known_features
        }
        overridden_features = dict(baseline_features)
        overridden_features.update(effective_overrides)

        sim_probability = predictor.model_manager.predict_proba(overridden_features)
        sim_score = round(sim_probability * 100, 2)
        sim_class = IARiskClassifier.classify(sim_probability)
        delta_score = round(sim_score - baseline_score, 2)

        feature_impacts: List[IAFeatureContribution] = []
        try:
            import shap
            if predictor.explainer is None:
                predictor.explainer = shap.TreeExplainer(predictor.model_manager.model)

            feature_names = predictor.model_manager.feature_names or list(overridden_features.keys())
            feature_array = np.array(
                [overridden_features.get(fname, 0.0) for fname in feature_names]
            ).reshape(1, -1)
            feature_array = np.nan_to_num(feature_array, nan=0.0)

            if predictor.model_manager.scaler is not None:
                feature_array = predictor.model_manager.scaler.transform(feature_array)

            shap_values = predictor.explainer.shap_values(feature_array)
            shap_abs = np.abs(shap_values[0])
            top_indices = np.argsort(shap_abs)[-5:][::-1]

            for idx in top_indices:
                fname = feature_names[idx]
                fval = float(overridden_features.get(fname, 0.0))
                sval = float(shap_values[0][idx])
                feature_impacts.append(
                    IAFeatureContribution.from_raw(fname, fval, round(sval, 4))
                )
        except Exception as shap_err:
            logger.warning(
                f"SHAP computation skipped for What-If simulation on case {case_id}: {shap_err}"
            )

        logger.info(
            f"What-If simulation completed for case {case_id}. "
            f"Baseline: {baseline_class} ({baseline_score}), "
            f"Simulated: {sim_class} ({sim_score}), Delta: {delta_score:+.2f}"
        )

        return WhatIfResult(
            scenario_name=payload.scenario_name,
            baseline_score=baseline_score,
            baseline_class=baseline_class,
            predicted_score_if=sim_score,
            predicted_class_if=sim_class,
            delta_score=delta_score,
            feature_impacts=feature_impacts,
            overridden_features=effective_overrides,
        )

    except InsufficientFiscalYearsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "insufficient_data", "message": str(e)}
        )

    except MissingFinancialDataError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "missing_financial_data", "message": str(e)}
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "model_not_found", "message": "No trained model available."}
        )

    except Exception as e:
        logger.exception(f"What-If simulation failed for case {case_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "simulation_failed", "message": str(e)}
        )


# ============================================================================
# ANALYTICS ENDPOINTS (T43 — câblage complet en Phase 3)
# ============================================================================

@router.get(
    "/analytics/convergence",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="MCC vs IA convergence analytics",
    description=(
        "Returns convergence rate between MCC Rail 1 and IA Rail 2 over time. "
        "⚠️ Stub — full implementation in Phase 3 (T43)."
    ),
)
async def get_convergence_analytics(
    days: int = Query(30, ge=1, le=365, description="Lookback period in days"),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Convergence analytics between MCC (Rail 1) and IA (Rail 2).

    Computes how often both rails agree on the risk classification
    over the requested period.

    TODO T43 (Phase 3): replace stub with real DB aggregation on IATension.
    """
    # Real query on IATension table — counts agreements vs total
    from datetime import timedelta
    from sqlalchemy import case as sa_case

    since = datetime.utcnow() - timedelta(days=days)

    stmt = select(
        func.count(IATension.id).label("total"),
        func.sum(
            sa_case((IATension.tension_type == "NONE", 1), else_=0)
        ).label("converged"),
    ).where(IATension.created_at >= since)

    result = await db.execute(stmt)
    row = result.one()
    total: int = row.total or 0
    converged: int = row.converged or 0
    rate = round((converged / total * 100), 1) if total > 0 else 0.0

    return {
        "period_days": days,
        "total_analyses": total,
        "converged": converged,
        "diverged": total - converged,
        "convergence_rate_pct": rate,
        "computed_at": datetime.utcnow().isoformat(),
        # T43 Phase 3 : ajouter séries temporelles jour par jour ici
        "timeseries": [],
    }


# ============================================================================
# PRIVATE HELPERS
# ============================================================================

async def _get_case_or_404(case_id: Any, db: AsyncSession) -> EvaluationCase:
    """Fetch case or raise 404."""
    if not isinstance(case_id, uuid.UUID):
        try:
            case_id = uuid.UUID(str(case_id))
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_uuid", "message": f"Invalid UUID format: {case_id}"}
            )

    stmt = select(EvaluationCase).where(EvaluationCase.id == case_id)
    result = await db.execute(stmt)
    case = result.scalars().first()
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "case_not_found", "message": f"Case {case_id} not found"}
        )
    return case


async def _get_cached_features(case_id: Any, db: AsyncSession) -> Optional[IAFeatures]:
    """Retrieve cached features for a case."""
    if not isinstance(case_id, uuid.UUID):
        case_id = uuid.UUID(str(case_id))

    stmt = (
        select(IAFeatures)
        .where(IAFeatures.case_id == case_id)
        .order_by(IAFeatures.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_model_by_version(version: str, db: AsyncSession) -> Optional[IAModel]:
    """Retrieve a model by version string."""
    stmt = select(IAModel).where(IAModel.version == version)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_or_compute_mcc_scorecard(case_id: Any, db: AsyncSession, force_recompute: bool):
    """Get or compute MCC scorecard for dual scoring."""
    from app.services.scoring_service import process_scoring
    from uuid import UUID as PUUID
    
    uid = case_id if isinstance(case_id, uuid.UUID) else PUUID(str(case_id))
    return await process_scoring(case_id=uid, db=db)
