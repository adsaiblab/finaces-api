"""
Machine Learning Models Module for AI Scoring System

This module implements ML model management, training, and inference for credit risk scoring.
Supports XGBoost and LightGBM models with proper calibration, feature importance tracking,
and version management.

Stack: SQLAlchemy 2.0 Async, Pydantic V2, FastAPI, PostgreSQL
Language: 100% English
"""

from typing import Dict, Any, Optional, List, Tuple, Literal
from pathlib import Path
import joblib
import json
import logging
from datetime import datetime
from dataclasses import dataclass
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, precision_recall_curve, confusion_matrix
import xgboost as xgb
import lightgbm as lgb

logger = logging.getLogger(__name__)


@dataclass
class ModelMetrics:
    """Container for model performance metrics."""
    auc: float
    gini: float
    precision: float
    recall: float
    f1_score: float
    optimal_threshold: float
    confusion_matrix: List[List[int]]
    feature_importance: Dict[str, float]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "auc": round(self.auc, 4),
            "gini": round(self.gini, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "optimal_threshold": round(self.optimal_threshold, 4),
            "confusion_matrix": self.confusion_matrix,
            "feature_importance": {
                k: round(v, 4) for k, v in list(self.feature_importance.items())[:10]
            }
        }


class MLModelManager:
    """
    Machine Learning model manager for AI scoring.
    
    Handles model training, evaluation, persistence, and inference
    for both XGBoost and LightGBM models.
    """
    
    # Model types supported
    MODEL_TYPES = Literal["xgboost", "lightgbm", "logistic"]
    
    # Default hyperparameters
    DEFAULT_XGBOOST_PARAMS = {
        "max_depth": 6,
        "learning_rate": 0.1,
        "n_estimators": 100,
        "min_child_weight": 1,
        "gamma": 0,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "random_state": 42,
        "tree_method": "hist",
        "enable_categorical": False
    }
    
    DEFAULT_LIGHTGBM_PARAMS = {
        "max_depth": 6,
        "learning_rate": 0.1,
        "n_estimators": 100,
        "num_leaves": 31,
        "min_child_samples": 20,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "objective": "binary",
        "metric": "auc",
        "random_state": 42,
        "verbosity": -1
    }
    
    def __init__(
        self,
        model_dir: Path = Path("ml/models"),
        model_type: str = "xgboost"
    ):
        """
        Initialize ML model manager.
        
        Args:
            model_dir: Directory to store trained models
            model_type: Type of model (xgboost, lightgbm, logistic)
        """
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        self.model_type = model_type
        self.model: Optional[Any] = None
        self.scaler: Optional[StandardScaler] = None
        self.feature_names: Optional[List[str]] = None
        self.metrics: Optional[ModelMetrics] = None
        self.version: Optional[str] = None
        
        logger.info(f"MLModelManager initialized with type: {model_type}")
    
    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        feature_names: List[str],
        hyperparams: Optional[Dict[str, Any]] = None
    ) -> ModelMetrics:
        """
        Train a new model.
        
        Args:
            X_train: Training features
            y_train: Training labels (0/1)
            X_val: Validation features
            y_val: Validation labels
            feature_names: List of feature names
            hyperparams: Optional custom hyperparameters
            
        Returns:
            ModelMetrics object with performance metrics
        """
        logger.info(
            f"Starting training for {self.model_type} model. "
            f"Train samples: {len(X_train)}, Val samples: {len(X_val)}"
        )
        
        self.feature_names = feature_names
        
        # Scale features
        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_val_scaled = self.scaler.transform(X_val)
        
        # Get hyperparameters
        params = self._get_hyperparameters(hyperparams)
        
        # Train model based on type
        if self.model_type == "xgboost":
            self.model = self._train_xgboost(
                X_train_scaled, y_train,
                X_val_scaled, y_val,
                params
            )
        elif self.model_type == "lightgbm":
            self.model = self._train_lightgbm(
                X_train_scaled, y_train,
                X_val_scaled, y_val,
                params
            )
        else:
            raise ValueError(f"Unsupported model type: {self.model_type}")
        
        # Evaluate on validation set
        self.metrics = self._evaluate(X_val_scaled, y_val)
        
        logger.info(
            f"Training completed. AUC: {self.metrics.auc:.4f}, "
            f"Gini: {self.metrics.gini:.4f}"
        )
        
        return self.metrics
    
    def _train_xgboost(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        params: Dict[str, Any]
    ) -> xgb.XGBClassifier:
        """Train XGBoost model."""
        model = xgb.XGBClassifier(**params)
        
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False
        )
        
        return model
    
    def _train_lightgbm(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        params: Dict[str, Any]
    ) -> lgb.LGBMClassifier:
        """Train LightGBM model."""
        model = lgb.LGBMClassifier(**params)
        
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(stopping_rounds=10, verbose=False)]
        )
        
        return model
    
    def _evaluate(
        self,
        X_val: np.ndarray,
        y_val: np.ndarray
    ) -> ModelMetrics:
        """
        Evaluate model performance.
        
        Args:
            X_val: Validation features (scaled)
            y_val: Validation labels
            
        Returns:
            ModelMetrics with all performance indicators
        """
        # Predict probabilities
        y_pred_proba = self.model.predict_proba(X_val)[:, 1]
        
        # AUC and Gini
        auc = roc_auc_score(y_val, y_pred_proba)
        gini = 2 * auc - 1
        
        # Find optimal threshold (maximizes F1)
        precision, recall, thresholds = precision_recall_curve(y_val, y_pred_proba)
        f1_scores = 2 * (precision * recall) / (precision + recall + 1e-10)
        optimal_idx = np.argmax(f1_scores)
        optimal_threshold = thresholds[optimal_idx] if optimal_idx < len(thresholds) else 0.5
        
        # Predict with optimal threshold
        y_pred = (y_pred_proba >= optimal_threshold).astype(int)
        
        # Confusion matrix
        cm = confusion_matrix(y_val, y_pred).tolist()
        
        # Precision, Recall, F1 at optimal threshold
        tn, fp, fn, tp = confusion_matrix(y_val, y_pred).ravel()
        precision_opt = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall_opt = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1_opt = 2 * (precision_opt * recall_opt) / (precision_opt + recall_opt + 1e-10)
        
        # Feature importance
        feature_importance = self._get_feature_importance()
        
        return ModelMetrics(
            auc=auc,
            gini=gini,
            precision=precision_opt,
            recall=recall_opt,
            f1_score=f1_opt,
            optimal_threshold=optimal_threshold,
            confusion_matrix=cm,
            feature_importance=feature_importance
        )
    
    def _get_feature_importance(self) -> Dict[str, float]:
        """Extract feature importance from trained model."""
        if self.model is None or self.feature_names is None:
            return {}
        
        if hasattr(self.model, 'feature_importances_'):
            importances = self.model.feature_importances_
            
            # Sort by importance
            importance_dict = dict(zip(self.feature_names, importances))
            sorted_importance = dict(
                sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)
            )
            
            return sorted_importance
        
        return {}
    
    def predict_proba(
        self,
        features: Dict[str, Any]
    ) -> float:
        """
        Predict default probability for a single case.
        
        Args:
            features: Dictionary of computed features
            
        Returns:
            Probability of default (0.0 - 1.0)
        """
        if self.model is None or self.scaler is None or self.feature_names is None:
            raise ValueError("Model not trained or loaded. Call train() or load() first.")
        
        # Convert features dict to array in correct order
        actual_features = features.get("features", features) if isinstance(features, dict) else features
        X = np.array([
            actual_features.get(fname, 0.0) for fname in self.feature_names
        ]).reshape(1, -1)
        
        # Handle missing values (impute with 0)
        X = np.nan_to_num(X, nan=0.0)
        
        # Scale
        X_scaled = self.scaler.transform(X)
        
        # Predict
        proba = self.model.predict_proba(X_scaled)[0, 1]
        
        return float(proba)
    
    def save(
        self,
        version: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Path:
        """
        Save trained model to disk.
        
        Args:
            version: Version string (e.g., "v1.0", "v1.1")
            metadata: Optional metadata to save alongside model
            
        Returns:
            Path to saved model file
        """
        if self.model is None:
            raise ValueError("No model to save. Train a model first.")
        
        self.version = version
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        # Save model
        model_filename = f"{self.model_type}_{version}_{timestamp}.pkl"
        model_path = self.model_dir / model_filename
        
        model_artifact = {
            "model": self.model,
            "scaler": self.scaler,
            "feature_names": self.feature_names,
            "model_type": self.model_type,
            "version": version,
            "trained_at": timestamp
        }
        
        joblib.dump(model_artifact, model_path)
        logger.info(f"Model saved to {model_path}")
        
        # Save metadata
        metadata_dict = {
            "version": version,
            "model_type": self.model_type,
            "trained_at": timestamp,
            "feature_count": len(self.feature_names) if self.feature_names else 0,
            "metrics": self.metrics.to_dict() if self.metrics else {},
            "custom_metadata": metadata or {}
        }
        
        metadata_path = self.model_dir / f"{self.model_type}_{version}_{timestamp}_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata_dict, f, indent=2)
        
        logger.info(f"Metadata saved to {metadata_path}")
        
        return model_path
    
    def load(
        self,
        model_path: Path
    ) -> None:
        """
        Load a trained model from disk.
        
        Args:
            model_path: Path to the saved model file
        """
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")
        
        logger.info(f"Loading model from {model_path}")
        
        artifact = joblib.load(model_path)
        
        self.model = artifact["model"]
        self.scaler = artifact["scaler"]
        self.feature_names = artifact["feature_names"]
        self.model_type = artifact["model_type"]
        self.version = artifact["version"]
        
        logger.info(
            f"Model loaded successfully. Type: {self.model_type}, "
            f"Version: {self.version}, Features: {len(self.feature_names)}"
        )
    
    def load_latest(self) -> None:
        """Load the most recently saved model."""
        model_files = list(self.model_dir.glob(f"{self.model_type}_*.pkl"))
        
        if not model_files:
            raise FileNotFoundError(
                f"No saved models found for type: {self.model_type}"
            )
        
        # Sort by modification time
        latest_model = max(model_files, key=lambda p: p.stat().st_mtime)
        self.load(latest_model)
    
    def _get_hyperparameters(
        self,
        custom_params: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Get hyperparameters (default or custom)."""
        if self.model_type == "xgboost":
            params = self.DEFAULT_XGBOOST_PARAMS.copy()
        elif self.model_type == "lightgbm":
            params = self.DEFAULT_LIGHTGBM_PARAMS.copy()
        else:
            params = {}
        
        if custom_params:
            params.update(custom_params)
        
        return params
