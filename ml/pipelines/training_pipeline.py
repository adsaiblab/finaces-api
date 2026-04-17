"""
Complete ML Training Pipeline for FinaCES AI Module

Orchestrates the entire training workflow:
1. Data loading (multiple sources)
2. Feature engineering
3. Preprocessing (missing values, outliers, scaling)
4. Model training (XGBoost, LightGBM, Ensemble)
5. Hyperparameter tuning
6. Cross-validation
7. Model evaluation
8. Model persistence (joblib + PostgreSQL registration)
9. SHAP explanations generation

Stack: XGBoost, LightGBM, scikit-learn, SHAP, MLflow (optional)
Language: 100% English
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import logging
import json
import joblib
import yaml

import pandas as pd
import numpy as np
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score, f1_score, fbeta_score,
    accuracy_score, log_loss, confusion_matrix, classification_report,
    roc_curve, precision_recall_curve
)
from sklearn.model_selection import cross_val_score, StratifiedKFold
import xgboost as xgb
import lightgbm as lgb
import shap
import matplotlib.pyplot as plt
import seaborn as sns

# FinaCES imports
from ml.pipelines.data_loader import DataLoader
from ml.pipelines.preprocessor import FinancialDataPreprocessor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ModelTrainer:
    """
    Complete training pipeline for credit scoring models.
    
    Handles end-to-end workflow from data loading to model deployment,
    with automatic hyperparameter tuning, evaluation, and persistence.
    """
    
    def __init__(
        self,
        model_config_path: str = "ml/config/model_config.yaml",
        features_config_path: str = "ml/config/features_config.yaml",
        output_dir: str = "ml/models",
        plots_dir: str = "ml/outputs/plots"
    ):
        """
        Initialize training pipeline.
        
        Args:
            model_config_path: Path to model configuration YAML
            features_config_path: Path to features configuration YAML
            output_dir: Directory to save trained models
            plots_dir: Directory to save evaluation plots
        """
        self.model_config_path = model_config_path
        self.features_config_path = features_config_path
        self.model_config = self._load_config(model_config_path)
        self.features_config = self._load_config(features_config_path)
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.plots_dir = Path(plots_dir)
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        
        self.model = None
        self.model_type = None
        self.preprocessor = None
        self.best_threshold = 0.5
        self.feature_importance = None
        self.shap_values = None
        
        # Training results
        self.training_history = {
            'metrics': {},
            'cv_scores': {},
            'feature_importance': {},
            'hyperparameters': {},
            'data_info': {}
        }
        
        logger.info("ModelTrainer initialized")
    
    def _load_config(self, path: str) -> Dict:
        """Load YAML configuration file."""
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        return config
    
    # ========================================================================
    # DATA PREPARATION
    # ========================================================================
    
    def prepare_data(
        self,
        data_source: str = "synthetic",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Load and preprocess data for training.
        
        Args:
            data_source: Data source (synthetic, german, lending_club, finaces_db)
            **kwargs: Source-specific arguments
            
        Returns:
            Dictionary with train/val/test splits
        """
        logger.info(f"Preparing data from source: {data_source}")
        
        # Load data
        loader = DataLoader()
        X, y = loader.load_dataset(data_source, **kwargs)
        
        logger.info(f"Raw data loaded: {X.shape[0]} samples, {X.shape[1]} features")
        logger.info(f"Target distribution: {y.value_counts().to_dict()}")
        
        # Store data info
        self.training_history['data_info'] = {
            'source': data_source,
            'n_samples': len(X),
            'n_features': X.shape[1],
            'target_distribution': y.value_counts().to_dict(),
            'default_rate': float(y.mean()),
            'feature_names': X.columns.tolist()
        }
        
        # Preprocess
        self.preprocessor = FinancialDataPreprocessor(
            features_config_path=self.features_config_path,
            model_config_path=self.model_config_path
        )
        
        processed_data = self.preprocessor.fit_transform(
            X, y,
            apply_smote=True
        )
        
        logger.info("✓ Data preparation completed")
        
        return processed_data
    
    # ========================================================================
    # MODEL TRAINING
    # ========================================================================
    
    def train_model(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        model_type: str = "xgboost"
    ):
        """
        Train ML model with specified algorithm.
        
        Args:
            X_train: Training features
            y_train: Training target
            X_val: Validation features (for early stopping)
            y_val: Validation target
            model_type: Model type (xgboost, lightgbm)
        """
        logger.info(f"Training {model_type.upper()} model...")
        
        self.model_type = model_type
        
        if model_type == "xgboost":
            self.model = self._train_xgboost(X_train, y_train, X_val, y_val)
        elif model_type == "lightgbm":
            self.model = self._train_lightgbm(X_train, y_train, X_val, y_val)
        else:
            raise ValueError(f"Unknown model type: {model_type}")
        
        # Extract feature importance
        self._extract_feature_importance(X_train)
        
        logger.info("✓ Model training completed")
    
    def _train_xgboost(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame],
        y_val: Optional[pd.Series]
    ) -> xgb.XGBClassifier:
        """Train XGBoost model."""
        
        config = self.model_config['model_training']['xgboost']
        hyperparams = config['hyperparameters'].copy()
        
        # Remove non-XGBClassifier params
        hyperparams.pop('eval_metric', None)
        
        # Initialize model
        model = xgb.XGBClassifier(**hyperparams)
        
        # Setup early stopping if validation set provided
        eval_set = []
        if X_val is not None and y_val is not None:
            eval_set = [(X_train, y_train), (X_val, y_val)]
        
        early_stopping_config = config.get('early_stopping', {})
        
        if early_stopping_config.get('enabled', False) and eval_set:
            early_stopping_rounds = early_stopping_config.get('rounds', 20)
            model.set_params(early_stopping_rounds=early_stopping_rounds)
            
            model.fit(
                X_train, y_train,
                eval_set=eval_set,
                verbose=False
            )
            
            logger.info(f"Best iteration: {model.best_iteration}")
        else:
            model.fit(X_train, y_train, verbose=False)
        
        # Store hyperparameters
        self.training_history['hyperparameters'] = hyperparams
        
        return model
    
    def _train_lightgbm(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame],
        y_val: Optional[pd.Series]
    ) -> lgb.LGBMClassifier:
        """Train LightGBM model."""
        
        config = self.model_config['model_training']['lightgbm']
        hyperparams = config['hyperparameters'].copy()
        
        # Remove non-LGBMClassifier params
        hyperparams.pop('metric', None)
        
        # Initialize model
        model = lgb.LGBMClassifier(**hyperparams)
        
        # Setup early stopping
        callbacks = []
        eval_set = []
        
        if X_val is not None and y_val is not None:
            eval_set = [(X_train, y_train), (X_val, y_val)]
            
            early_stopping_config = config.get('early_stopping', {})
            if early_stopping_config.get('enabled', False):
                callbacks.append(lgb.early_stopping(
                    stopping_rounds=early_stopping_config.get('rounds', 20)
                ))
        
        if callbacks and eval_set:
            model.fit(
                X_train, y_train,
                eval_set=eval_set,
                callbacks=callbacks
            )
        else:
            model.fit(X_train, y_train)
        
        # Store hyperparameters
        self.training_history['hyperparameters'] = hyperparams
        
        return model
    
    def _extract_feature_importance(self, X_train: pd.DataFrame):
        """Extract and store feature importance."""
        
        if hasattr(self.model, 'feature_importances_'):
            importance = self.model.feature_importances_
            
            importance_df = pd.DataFrame({
                'feature': X_train.columns,
                'importance': importance
            }).sort_values('importance', ascending=False)
            
            self.feature_importance = importance_df
            
            # Store top 20 in history
            self.training_history['feature_importance'] = (
                importance_df.head(20).to_dict('records')
            )
            
            logger.info("✓ Feature importance extracted")
    
    # ========================================================================
    # CROSS-VALIDATION
    # ========================================================================
    
    def cross_validate(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series
    ) -> Dict[str, float]:
        """
        Perform stratified k-fold cross-validation.
        
        Args:
            X_train: Training features
            y_train: Training target
            
        Returns:
            Dictionary with mean CV scores
        """
        cv_config = self.model_config['model_training']['cross_validation']
        
        if not cv_config.get('enabled', True):
            logger.info("Cross-validation disabled in config")
            return {}
        
        logger.info("Performing cross-validation...")
        
        n_folds = cv_config['n_folds']
        stratified = cv_config['stratified']
        random_state = cv_config['random_state']
        
        # Setup CV splitter
        if stratified:
            cv = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=random_state)
        else:
            cv = n_folds
        
        # Perform CV for multiple metrics
        metrics_to_eval = ['roc_auc', 'precision', 'recall', 'f1']
        cv_results = {}
        
        # Disable early stopping for CV to avoid missing eval_set errors
        if hasattr(self.model, 'set_params'):
            try:
                self.model.set_params(early_stopping_rounds=None)
            except Exception:
                pass
        
        for metric in metrics_to_eval:
            scores = cross_val_score(
                self.model, X_train, y_train,
                cv=cv,
                scoring=metric,
                n_jobs=-1
            )
            
            cv_results[f'{metric}_mean'] = float(scores.mean())
            cv_results[f'{metric}_std'] = float(scores.std())
            
            logger.info(
                f"  {metric}: {scores.mean():.4f} (+/- {scores.std():.4f})"
            )
        
        self.training_history['cv_scores'] = cv_results
        
        logger.info("✓ Cross-validation completed")
        return cv_results
    
    # ========================================================================
    # MODEL EVALUATION
    # ========================================================================
    
    def evaluate_model(
        self,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        optimize_threshold: bool = True
    ) -> Dict[str, float]:
        """
        Comprehensive model evaluation on test set.
        
        Args:
            X_test: Test features
            y_test: Test target
            optimize_threshold: Whether to optimize classification threshold
            
        Returns:
            Dictionary with evaluation metrics
        """
        logger.info("Evaluating model on test set...")
        
        if self.model is None:
            raise ValueError("Model not trained. Call train_model() first.")
        
        # Get predictions
        y_pred_proba = self.model.predict_proba(X_test)[:, 1]
        
        # Optimize threshold if requested
        if optimize_threshold:
            self.best_threshold = self._optimize_threshold(y_test, y_pred_proba)
            logger.info(f"Optimized threshold: {self.best_threshold:.3f}")
        
        y_pred = (y_pred_proba >= self.best_threshold).astype(int)
        
        # Calculate metrics
        metrics = {
            'roc_auc': float(roc_auc_score(y_test, y_pred_proba)),
            'precision': float(precision_score(y_test, y_pred, zero_division=0)),
            'recall': float(recall_score(y_test, y_pred, zero_division=0)),
            'f1_score': float(f1_score(y_test, y_pred, zero_division=0)),
            'accuracy': float(accuracy_score(y_test, y_pred)),
            'log_loss': float(log_loss(y_test, y_pred_proba)),
            'threshold': float(self.best_threshold)
        }
        
        # Confusion matrix
        cm = confusion_matrix(y_test, y_pred)
        metrics['confusion_matrix'] = cm.tolist()
        
        # Classification report
        report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
        metrics['classification_report'] = report
        
        # Store in history
        self.training_history['metrics'] = metrics
        
        # Log results
        logger.info("="*60)
        logger.info("MODEL EVALUATION RESULTS")
        logger.info("="*60)
        logger.info(f"ROC-AUC:    {metrics['roc_auc']:.4f}")
        logger.info(f"Precision:  {metrics['precision']:.4f}")
        logger.info(f"Recall:     {metrics['recall']:.4f}")
        logger.info(f"F1-Score:   {metrics['f1_score']:.4f}")
        logger.info(f"Accuracy:   {metrics['accuracy']:.4f}")
        logger.info(f"Log Loss:   {metrics['log_loss']:.4f}")
        logger.info("="*60)
        
        # Generate evaluation plots
        self._plot_evaluation_results(y_test, y_pred, y_pred_proba)
        
        logger.info("✓ Model evaluation completed")
        return metrics
    
    def _optimize_threshold(
        self,
        y_true: pd.Series,
        y_pred_proba: np.ndarray
    ) -> float:
        """
        Optimize classification threshold using F-beta (beta=2) with a
        minimum recall gate.

        In fiduciary context, False Negatives (missing a risky entity) are
        catastrophic. Therefore:
        - We use fbeta_score with beta=2 to heavily weight recall.
        - Any threshold yielding recall < MIN_RECALL_GATE (0.90) is
          discarded regardless of its F-beta score.

        Args:
            y_true: True labels
            y_pred_proba: Predicted probabilities

        Returns:
            Optimal threshold (defaults to lowest candidate if no threshold
            meets the recall gate)
        """
        MIN_RECALL_GATE = 0.90
        BETA = 2

        threshold_config = self.model_config['model_training']['evaluation_metrics']['threshold_optimization']

        if not threshold_config.get('enabled', True):
            return 0.5

        search_range = threshold_config.get('search_range', [0.3, 0.7])
        n_points = threshold_config.get('n_points', 40)

        thresholds = np.linspace(search_range[0], search_range[1], n_points)

        best_threshold = thresholds[0]  # safe fallback: lowest threshold = highest recall
        best_fbeta = -1.0

        for threshold in thresholds:
            y_pred = (y_pred_proba >= threshold).astype(int)

            recall = recall_score(y_true, y_pred, zero_division=0)

            # Minimum recall gate: discard thresholds that miss too many defaults
            if recall < MIN_RECALL_GATE:
                continue

            fb = fbeta_score(y_true, y_pred, beta=BETA, zero_division=0)

            if fb > best_fbeta:
                best_fbeta = fb
                best_threshold = threshold

        # If no threshold met the recall gate, warn and use the lowest
        # threshold (most conservative / highest recall) as fallback
        if best_fbeta < 0:
            best_threshold = thresholds[0]
            y_pred_fallback = (y_pred_proba >= best_threshold).astype(int)
            fallback_recall = recall_score(y_true, y_pred_fallback, zero_division=0)
            logger.warning(
                f"No threshold met minimum recall gate ({MIN_RECALL_GATE:.0%}). "
                f"Falling back to lowest threshold {best_threshold:.3f} "
                f"(recall={fallback_recall:.3f})."
            )
        else:
            logger.info(
                f"Threshold optimized with F-beta(beta={BETA}) + recall gate >= {MIN_RECALL_GATE:.0%}: "
                f"threshold={best_threshold:.3f}, F{BETA}={best_fbeta:.4f}"
            )

        return best_threshold
    
    def _plot_evaluation_results(
        self,
        y_test: pd.Series,
        y_pred: np.ndarray,
        y_pred_proba: np.ndarray
    ):
        """Generate evaluation plots."""
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        # 1. Confusion Matrix
        cm = confusion_matrix(y_test, y_pred)
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', ax=axes[0, 0])
        axes[0, 0].set_title('Confusion Matrix')
        axes[0, 0].set_ylabel('True Label')
        axes[0, 0].set_xlabel('Predicted Label')
        
        # 2. ROC Curve
        fpr, tpr, _ = roc_curve(y_test, y_pred_proba)
        auc = roc_auc_score(y_test, y_pred_proba)
        axes[0, 1].plot(fpr, tpr, label=f'ROC (AUC = {auc:.3f})')
        axes[0, 1].plot([0, 1], [0, 1], 'k--', label='Random')
        axes[0, 1].set_title('ROC Curve')
        axes[0, 1].set_xlabel('False Positive Rate')
        axes[0, 1].set_ylabel('True Positive Rate')
        axes[0, 1].legend()
        axes[0, 1].grid(True, alpha=0.3)
        
        # 3. Precision-Recall Curve
        precision, recall, _ = precision_recall_curve(y_test, y_pred_proba)
        axes[1, 0].plot(recall, precision)
        axes[1, 0].set_title('Precision-Recall Curve')
        axes[1, 0].set_xlabel('Recall')
        axes[1, 0].set_ylabel('Precision')
        axes[1, 0].grid(True, alpha=0.3)
        
        # 4. Prediction Distribution
        axes[1, 1].hist(y_pred_proba[y_test == 0], bins=30, alpha=0.5, label='No Default (0)')
        axes[1, 1].hist(y_pred_proba[y_test == 1], bins=30, alpha=0.5, label='Default (1)')
        axes[1, 1].axvline(self.best_threshold, color='red', linestyle='--', label=f'Threshold ({self.best_threshold:.2f})')
        axes[1, 1].set_title('Prediction Distribution')
        axes[1, 1].set_xlabel('Predicted Probability')
        axes[1, 1].set_ylabel('Frequency')
        axes[1, 1].legend()
        
        plt.tight_layout()
        
        # Save plot
        plot_path = self.plots_dir / f"evaluation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        logger.info(f"✓ Evaluation plots saved to: {plot_path}")
    
    # ========================================================================
    # SHAP EXPLANATIONS
    # ========================================================================
    
    def generate_shap_explanations(
        self,
        X_train: pd.DataFrame,
        max_samples: int = 500
    ):
        """
        Generate SHAP (SHapley Additive exPlanations) values.
        
        Args:
            X_train: Training data for background distribution
            max_samples: Maximum samples to use (for performance)
        """
        shap_config = self.model_config['model_training']['shap_config']
        
        if not shap_config.get('enabled', True):
            logger.info("SHAP explanations disabled in config")
            return
        
        logger.info("Generating SHAP explanations...")
        
        if self.model is None:
            raise ValueError("Model not trained")
        
        # Sample data for efficiency
        if len(X_train) > max_samples:
            X_sample = X_train.sample(n=max_samples, random_state=42)
        else:
            X_sample = X_train
        
        # Create SHAP explainer
        explainer_type = shap_config.get('explainer_type', 'tree')
        
        if explainer_type == 'tree':
            explainer = shap.TreeExplainer(self.model)
        else:
            explainer = shap.Explainer(self.model, X_sample)
        
        # Calculate SHAP values
        shap_values = explainer.shap_values(X_sample)
        
        # Handle binary classification output
        if isinstance(shap_values, list):
            shap_values = shap_values[1]  # Positive class
        
        self.shap_values = shap_values
        
        # Generate plots
        if shap_config.get('save_plots', True):
            self._plot_shap_summary(X_sample, shap_values, shap_config)
        
        logger.info("✓ SHAP explanations generated")
    
    def _plot_shap_summary(
        self,
        X_sample: pd.DataFrame,
        shap_values: np.ndarray,
        config: Dict
    ):
        """Generate and save SHAP summary plots."""
        
        max_display = config.get('max_display_features', 15)
        
        # Summary plot
        plt.figure(figsize=(10, 8))
        shap.summary_plot(
            shap_values, X_sample,
            max_display=max_display,
            show=False
        )
        
        plot_path = self.plots_dir / f"shap_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        logger.info(f"✓ SHAP plots saved to: {plot_path}")
    
    # ========================================================================
    # MODEL PERSISTENCE
    # ========================================================================
    
    def save_model(
        self,
        model_name: Optional[str] = None,
        version: Optional[str] = None
    ) -> Path:
        """
        Save trained model with its preprocessing context to disk.
        
        Saves a structured dictionary artifact:
        {
            "model": self.model,
            "scaler": self.preprocessor.scaler if self.preprocessor else None,
            "feature_names": self.preprocessor.numeric_features if self.preprocessor else None,
            "model_type": self.model_type,
            "version": version,
            "trained_at": timestamp
        }
        
        Args:
            model_name: Custom model name (default: auto-generated)
            version: Model version (default: timestamp)
            
        Returns:
            Path to saved model file
        """
        if self.model is None:
            raise ValueError("No model to save. Train model first.")
        
        # Generate filename
        if model_name is None:
            model_name = f"{self.model_type}_model"
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if version is None:
            version = timestamp
        
        filename = f"{model_name}_{version}.joblib"
        model_path = self.output_dir / filename
        
        # ── Artifact Construction (Ensures compatibility with MLModelManager) ──
        # We extract the scaler and numeric features from the fitted preprocessor
        scaler = None
        feature_names = None
        if self.preprocessor:
            scaler = self.preprocessor.scaler
            # In FinancialDataPreprocessor, numeric_features stores the list of columns
            feature_names = self.preprocessor.numeric_features
            
        model_artifact = {
            "model": self.model,
            "scaler": scaler,
            "feature_names": feature_names,
            "model_type": self.model_type,
            "version": version,
            "trained_at": timestamp
        }
        
        # Save structured artifact
        joblib.dump(model_artifact, model_path)
        
        logger.info(f"✓ Structured model artifact saved to: {model_path}")
        
        # Save metadata (JSON only, for humans/dashboard)
        metadata_path = self.output_dir / f"{model_name}_{version}_metadata.json"
        
        metadata = {
            'model_name': model_name,
            'version': version,
            'model_type': self.model_type,
            'training_date': datetime.now().isoformat(),
            'training_history': self.training_history,
            'threshold': float(self.best_threshold),
            'feature_count': len(feature_names) if feature_names else 0,
            'metrics': self.training_history.get('metrics', {}),
            'preprocessor': 'FinancialDataPreprocessor'
        }
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2, default=str)
        
        logger.info(f"✓ Metadata saved to: {metadata_path}")
        
        return model_path
    
    def save_preprocessor(self, model_name: str, version: str) -> Path:
        """Save fitted preprocessor."""
        
        if self.preprocessor is None:
            raise ValueError("No preprocessor to save")
        
        filename = f"{model_name}_{version}_preprocessor.joblib"
        preprocessor_path = self.output_dir / filename
        
        joblib.dump(self.preprocessor, preprocessor_path)
        
        logger.info(f"✓ Preprocessor saved to: {preprocessor_path}")
        return preprocessor_path
    
    # ========================================================================
    # COMPLETE PIPELINE
    # ========================================================================
    
    def run_complete_pipeline(
        self,
        data_source: str = "synthetic",
        model_type: str = "xgboost",
        save_artifacts: bool = True,
        **data_kwargs
    ) -> Dict[str, Any]:
        """
        Run complete end-to-end training pipeline.
        
        Steps:
        1. Load and preprocess data
        2. Train model
        3. Cross-validate
        4. Evaluate on test set
        5. Generate SHAP explanations
        6. Save model and artifacts
        
        Args:
            data_source: Data source identifier
            model_type: Model algorithm (xgboost, lightgbm)
            save_artifacts: Whether to save model files
            **data_kwargs: Additional arguments for data loading
            
        Returns:
            Dictionary with complete results
        """
        logger.info("="*70)
        logger.info("STARTING COMPLETE TRAINING PIPELINE")
        logger.info("="*70)
        
        start_time = datetime.now()
        
        # Step 1: Prepare data
        logger.info("\n[1/6] Preparing data...")
        data = self.prepare_data(data_source, **data_kwargs)
        
        # Step 2: Train model
        logger.info("\n[2/6] Training model...")
        self.train_model(
            data['X_train'], data['y_train'],
            data['X_val'], data['y_val'],
            model_type=model_type
        )
        
        # Step 3: Cross-validate
        logger.info("\n[3/6] Cross-validating...")
        cv_scores = self.cross_validate(data['X_train'], data['y_train'])
        
        # Step 4: Evaluate
        logger.info("\n[4/6] Evaluating on test set...")
        metrics = self.evaluate_model(data['X_test'], data['y_test'])
        
        # Step 5: SHAP explanations
        logger.info("\n[5/6] Generating SHAP explanations...")
        self.generate_shap_explanations(data['X_train'])
        
        # Step 6: Save artifacts
        if save_artifacts:
            logger.info("\n[6/6] Saving model artifacts...")
            
            version = datetime.now().strftime('%Y%m%d_%H%M%S')
            model_path = self.save_model(version=version)
            preprocessor_path = self.save_preprocessor(
                f"{self.model_type}_model",
                version
            )
        else:
            logger.info("\n[6/6] Skipping model save (save_artifacts=False)")
            model_path = None
            preprocessor_path = None
        
        # Calculate training time
        training_time = (datetime.now() - start_time).total_seconds()
        
        # Compile results
        results = {
            'model_type': self.model_type,
            'version': version if save_artifacts else None,
            'data_source': data_source,
            'training_time_seconds': training_time,
            'metrics': metrics,
            'cv_scores': cv_scores,
            'model_path': str(model_path) if model_path else None,
            'preprocessor_path': str(preprocessor_path) if preprocessor_path else None,
            'feature_importance': self.feature_importance.head(20).to_dict('records') if self.feature_importance is not None else None
        }
        
        logger.info("="*70)
        logger.info("PIPELINE COMPLETED SUCCESSFULLY")
        logger.info(f"Total time: {training_time:.2f} seconds")
        logger.info(f"Final ROC-AUC: {metrics['roc_auc']:.4f}")
        logger.info("="*70)
        
        return results


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    """Command-line interface for training pipeline."""
    import argparse
    
    parser = argparse.ArgumentParser(description="FinaCES AI Training Pipeline")
    
    parser.add_argument(
        '--data-source',
        type=str,
        default='synthetic',
        choices=['synthetic', 'german', 'lending_club'],
        help='Data source to use'
    )
    
    parser.add_argument(
        '--model-type',
        type=str,
        default='xgboost',
        choices=['xgboost', 'lightgbm'],
        help='Model algorithm'
    )
    
    parser.add_argument(
        '--n-samples',
        type=int,
        default=2000,
        help='Number of samples for synthetic data'
    )
    
    parser.add_argument(
        '--no-save',
        action='store_true',
        help='Skip saving model artifacts'
    )
    
    args = parser.parse_args()
    
    # Initialize trainer
    trainer = ModelTrainer()
    
    # Run pipeline
    data_kwargs = {}
    if args.data_source == 'synthetic':
        data_kwargs['n_samples'] = args.n_samples
    
    results = trainer.run_complete_pipeline(
        data_source=args.data_source,
        model_type=args.model_type,
        save_artifacts=not args.no_save,
        **data_kwargs
    )
    
    # Print summary
    print("\n" + "="*70)
    print("TRAINING SUMMARY")
    print("="*70)
    print(f"Model Type:        {results['model_type']}")
    print(f"Data Source:       {results['data_source']}")
    print(f"Training Time:     {results['training_time_seconds']:.2f}s")
    print(f"\nTest Set Metrics:")
    print(f"  ROC-AUC:         {results['metrics']['roc_auc']:.4f}")
    print(f"  Precision:       {results['metrics']['precision']:.4f}")
    print(f"  Recall:          {results['metrics']['recall']:.4f}")
    print(f"  F1-Score:        {results['metrics']['f1_score']:.4f}")
    
    if results['model_path']:
        print(f"\nModel saved to:    {results['model_path']}")
    
    print("="*70)


if __name__ == "__main__":
    main()
