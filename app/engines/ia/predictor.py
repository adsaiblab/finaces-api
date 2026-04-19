"""
AI Predictor Module

This module orchestrates the complete AI scoring pipeline:
1. Load features from feature engineering
2. Load trained ML model
3. Predict default probability
4. Classify risk level
5. Generate explanations

Stack: SQLAlchemy 2.0 Async, Pydantic V2, FastAPI, PostgreSQL
Language: 100% English
"""

from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from datetime import datetime
from enum import Enum
import logging
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import shap

from app.engines.ia.feature_engineering import FeatureEngineeringEngine
from app.engines.ia.ml_models import MLModelManager
from app.services.ia_service import generate_and_save_ia_features
from app.db.models import IAModel, IAPrediction, IAFeatures
from app.schemas.ia_schema import (
    IARiskClass,
    IAPredictionResult,
    IAExplanation
)

logger = logging.getLogger(__name__)


class IARiskClassifier:
    """
    Risk classification based on default probability.
    
    Maps continuous probability to discrete risk classes
    according to MCC-aligned thresholds.
    """
    
    # Risk thresholds (probability of default)
    THRESHOLDS = {
        "LOW": 0.05,        # 0-5%
        "MODERATE": 0.15,   # 5-15%
        "HIGH": 0.30,       # 15-30%
        "CRITICAL": 1.0     # >30%
    }
    
    @classmethod
    def classify(cls, probability: float) -> str:
        """
        Classify risk level from probability.
        
        Args:
            probability: Default probability (0.0 - 1.0)
            
        Returns:
            Risk class string (LOW/MODERATE/HIGH/CRITICAL)
        """
        if probability < cls.THRESHOLDS["LOW"]:
            return "LOW"
        elif probability < cls.THRESHOLDS["MODERATE"]:
            return "MODERATE"
        elif probability < cls.THRESHOLDS["HIGH"]:
            return "HIGH"
        else:
            return "CRITICAL"
    
    @classmethod
    def get_threshold_info(cls, risk_class: str) -> Dict[str, float]:
        """Get threshold boundaries for a risk class."""
        thresholds_list = list(cls.THRESHOLDS.items())
        
        for i, (rclass, upper) in enumerate(thresholds_list):
            if rclass == risk_class:
                lower = thresholds_list[i-1][1] if i > 0 else 0.0
                return {
                    "lower_bound": lower,
                    "upper_bound": upper,
                    "midpoint": (lower + upper) / 2
                }
        
        return {"lower_bound": 0.0, "upper_bound": 1.0, "midpoint": 0.5}


class IAPredictor:
    """
    Main AI prediction engine.
    
    Orchestrates feature engineering, model inference, risk classification,
    and explanation generation for a given evaluation case.
    """
    
    def __init__(
        self,
        model_dir: Path = Path("ml/models"),
        model_type: str = "xgboost",
        enable_explanations: bool = True
    ):
        """
        Initialize AI predictor.
        
        Args:
            model_dir: Directory containing trained models
            model_type: Type of model to use
            enable_explanations: Whether to compute SHAP explanations
        """
        self.feature_engine = FeatureEngineeringEngine()
        self.model_manager = MLModelManager(
            model_dir=model_dir,
            model_type=model_type
        )
        self.enable_explanations = enable_explanations
        self.explainer: Optional[shap.Explainer] = None
        
        logger.info(f"IAPredictor initialized with model type: {model_type}")
    
    async def predict(
        self,
        case_id: str,
        db: AsyncSession,
        use_cached_features: bool = True
    ) -> IAPredictionResult:
        """
        Generate AI prediction for a case.
        
        Args:
            case_id: Evaluation case identifier
            db: Async database session
            use_cached_features: Whether to use cached features if available
            
        Returns:
            IAPredictionResult with score, risk class, and explanations
        """
        case_uuid = uuid.UUID(str(case_id))
        logger.info(f"Starting AI prediction for case {case_id}")
        
        # 1. Load or compute features
        features_data = await self._get_or_compute_features(
            case_uuid, db, use_cached_features
        )
        
        features = features_data["features"]
        
        # 2. Load active model if not already loaded
        if self.model_manager.model is None:
            await self._load_active_model(db)
        
        # 3. Predict default probability
        probability = self.model_manager.predict_proba(features)
        
        # 4. Classify risk level
        risk_class = IARiskClassifier.classify(probability)
        
        # 5. Generate explanations (if enabled)
        explanations = None
        if self.enable_explanations:
            explanations = self._generate_explanations(features, probability)
        
        # 6. Persist prediction
        await self._save_prediction(
            case_id=case_uuid,
            probability=probability,
            risk_class=risk_class,
            model_version=self.model_manager.version or "unknown",
            db=db,
            features=features,
            explanations=explanations,
        )
        
        # 7. Build result
        result = IAPredictionResult(
            case_id=str(case_id),
            ia_score=round(probability * 100, 2),  # Convert to 0-100 scale
            ia_probability_default=round(probability, 4),
            ia_risk_class=risk_class,
            model_version=self.model_manager.version or "unknown",
            predicted_at=datetime.utcnow(),
            explanations=explanations,
            threshold_info=IARiskClassifier.get_threshold_info(risk_class)
        )
        
        logger.info(
            f"Prediction completed for case {case_id}. "
            f"Probability: {probability:.4f}, Risk: {risk_class}"
        )
        
        return result
    
    async def _get_or_compute_features(
        self,
        case_id: uuid.UUID,
        db: AsyncSession,
        use_cached: bool
    ) -> Dict[str, Any]:
        """
        Get features from cache or compute fresh.
        
        Args:
            case_id: Case identifier
            db: Database session
            use_cached: Whether to use cached features
            
        Returns:
            Features dictionary
        """
        case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
        
        if use_cached:
            stmt = (
                select(IAFeatures)
                .where(IAFeatures.case_id == case_uuid)
                .order_by(IAFeatures.created_at.desc())
            )
            result = await db.execute(stmt)
            cached_features = result.scalars().first()
            
            if cached_features:
                logger.info(f"Using cached features for case {case_id}")
                # cached_features.features contains the actual dict of values
                return {"features": cached_features.features} 
        
        logger.info(f"Computing fresh features for case {case_id}")
        # Call the service which handles computation AND database saving
        features_data = await generate_and_save_ia_features(case_uuid, db)
        return features_data
    
    async def _load_active_model(
        self,
        db: AsyncSession
    ) -> None:
        """
        Load the currently active model from database.
        
        Args:
            db: Database session
        """
        # Find active model in database
        stmt = (
            select(IAModel)
            .where(IAModel.is_active == True)
            .order_by(IAModel.created_at.desc())
        )
        result = await db.execute(stmt)
        active_model = result.scalars().first()
        
        if not active_model:
            logger.warning("No active model found in database. Loading latest from disk.")
            self.model_manager.load_latest()
        else:
            model_path = Path(active_model.file_path)
            logger.info(f"Loading active model: {active_model.model_name} v{active_model.version}")
            self.model_manager.load(model_path)
    
    def _generate_explanations(
        self,
        features: Dict[str, Any],
        probability: float
    ) -> Optional[IAExplanation]:
        """
        Generate SHAP-based explanations for the prediction.
        
        Args:
            features: Computed features
            probability: Predicted probability
            
        Returns:
            IAExplanation object with top contributing features
        """
        try:
            # Initialize SHAP explainer if not already done
            if self.explainer is None:
                self.explainer = shap.TreeExplainer(self.model_manager.model)
            
            # Prepare features array
            import numpy as np
            feature_array = np.array([
                features.get(fname, 0.0)
                for fname in self.model_manager.feature_names
            ]).reshape(1, -1)
            
            # Handle missing values
            feature_array = np.nan_to_num(feature_array, nan=0.0)
            
            # Scale only if scaler exists (tree models don't need scaling)
            if self.model_manager.scaler is not None:
                feature_array_scaled = self.model_manager.scaler.transform(feature_array)
            else:
                feature_array_scaled = feature_array
            
            # Compute SHAP values
            shap_values = self.explainer.shap_values(feature_array_scaled)
            
            # Get top contributing features
            shap_abs = np.abs(shap_values[0])
            top_indices = np.argsort(shap_abs)[-5:][::-1]  # Top 5
            
            top_features = []
            for idx in top_indices:
                feature_name = self.model_manager.feature_names[idx]
                feature_value = features.get(feature_name)
                shap_value = float(shap_values[0][idx])
                
                top_features.append({
                    "feature_name": feature_name,
                    "feature_value": feature_value,
                    "shap_value": round(shap_value, 4),
                    "impact": "increases_risk" if shap_value > 0 else "decreases_risk"
                })
            
            return IAExplanation(
                top_features=top_features,
                explanation_method="SHAP TreeExplainer",
                base_value=float(self.explainer.expected_value)
            )
        
        except Exception as e:
            logger.error(f"Failed to generate explanations: {e}")
            return None
    
    async def _save_prediction(
        self,
        case_id: uuid.UUID,
        probability: float,
        risk_class: str,
        model_version: str,
        db: AsyncSession,
        features: dict | None = None,
        explanations=None,
    ) -> None:
        """
        Persist prediction to database.

        Args:
            case_id:       Case identifier
            probability:   Predicted probability
            risk_class:    Classified risk level
            model_version: Model version used
            db:            Database session
            features:      Input feature snapshot for drift monitoring (C.6.2)
        """
        snapshot = dict(features) if features else {}
        if explanations is not None:
            snapshot["_explanations"] = explanations.model_dump()

        prediction = IAPrediction(
            case_id=case_id,
            ia_score=round(probability * 100, 2),
            ia_probability_default=round(probability, 4),
            ia_risk_class=risk_class,
            model_version=model_version,
            input_features=snapshot,
        )

        db.add(prediction)
        await db.commit()

        logger.info(f"Prediction saved to database for case {case_id}")
