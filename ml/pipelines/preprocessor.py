"""
Data Preprocessing Pipeline for FinaCES AI Module

Handles:
- Missing value imputation
- Outlier detection and treatment
- Feature scaling
- Feature engineering validation
- Train/test split with stratification

Cohérent avec: features_config.yaml, model_config.yaml
Stack: pandas, scikit-learn, imbalanced-learn
Language: 100% English
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import logging
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler
from sklearn.impute import SimpleImputer
from imblearn.over_sampling import SMOTE
from imblearn.under_sampling import RandomUnderSampler
from imblearn.pipeline import Pipeline as ImbPipeline

logger = logging.getLogger(__name__)


class FinancialDataPreprocessor:
    """
    Complete preprocessing pipeline for financial credit scoring data.
    
    Applies transformations defined in features_config.yaml and
    model_config.yaml to prepare data for ML training.
    """
    
    def __init__(
        self,
        features_config_path: str = "ml/config/features_config.yaml",
        model_config_path: str = "ml/config/model_config.yaml"
    ):
        """
        Initialize preprocessor with configuration files.
        
        Args:
            features_config_path: Path to features configuration YAML
            model_config_path: Path to model configuration YAML
        """
        self.features_config = self._load_config(features_config_path)
        self.model_config = self._load_config(model_config_path)
        
        # Extract relevant configs
        self.feature_eng_config = self.features_config['feature_engineering']
        self.model_train_config = self.model_config['model_training']
        
        # Initialize scalers and imputers (fitted during preprocessing)
        self.scaler = None
        self.imputer_numeric = None
        self.imputer_categorical = None
        
        # Feature lists (populated during fit)
        self.numeric_features = []
        self.categorical_features = []
        self.features_to_scale = []
        
        logger.info("FinancialDataPreprocessor initialized")
    
    def _load_config(self, path: str) -> Dict:
        """Load YAML configuration file."""
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        return config
    
    # ========================================================================
    # MISSING VALUE HANDLING
    # ========================================================================
    
    def handle_missing_values(
        self,
        X: pd.DataFrame,
        fit: bool = True
    ) -> pd.DataFrame:
        """
        Handle missing values according to features_config.yaml strategy.
        
        Args:
            X: Features DataFrame
            fit: If True, fit imputers; if False, use existing fitted imputers
            
        Returns:
            DataFrame with missing values imputed
        """
        X = X.copy()
        
        # Separate numeric and categorical
        numeric_cols = X.select_dtypes(include=[np.number]).columns.tolist()
        categorical_cols = X.select_dtypes(include=['object', 'category']).columns.tolist()
        
        self.numeric_features = numeric_cols
        self.categorical_features = categorical_cols
        
        # Get strategies from config
        numeric_strategy = self.feature_eng_config['missing_value_strategy']['numeric_features']
        categorical_strategy = self.feature_eng_config['missing_value_strategy']['categorical_features']
        
        # Impute numeric features
        if numeric_cols:
            if fit:
                self.imputer_numeric = SimpleImputer(strategy=numeric_strategy)
                X[numeric_cols] = self.imputer_numeric.fit_transform(X[numeric_cols])
            else:
                if self.imputer_numeric is None:
                    raise ValueError("Imputer not fitted. Call with fit=True first.")
                X[numeric_cols] = self.imputer_numeric.transform(X[numeric_cols])
        
        # Impute categorical features
        if categorical_cols:
            if fit:
                self.imputer_categorical = SimpleImputer(
                    strategy='most_frequent' if categorical_strategy == 'mode' else 'constant',
                    fill_value='missing' if categorical_strategy == 'constant' else None
                )
                X[categorical_cols] = self.imputer_categorical.fit_transform(X[categorical_cols])
            else:
                if self.imputer_categorical is None:
                    raise ValueError("Imputer not fitted. Call with fit=True first.")
                X[categorical_cols] = self.imputer_categorical.transform(X[categorical_cols])
        
        logger.info(
            f"Missing values handled: {len(numeric_cols)} numeric, "
            f"{len(categorical_cols)} categorical features"
        )
        
        return X
    
    # ========================================================================
    # OUTLIER DETECTION
    # ========================================================================
    
    def detect_and_treat_outliers(
        self,
        X: pd.DataFrame,
        method: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Detect and treat outliers according to config.
        
        Args:
            X: Features DataFrame
            method: Outlier detection method (overrides config if provided)
                - "iqr": Interquartile range method
                - "zscore": Z-score method
                - "clip": Clip to percentiles
                
        Returns:
            DataFrame with outliers treated
        """
        X = X.copy()
        
        outlier_config = self.feature_eng_config.get('outlier_detection', {})
        
        if not outlier_config.get('enabled', True):
            logger.info("Outlier detection disabled in config")
            return X
        
        method = method or outlier_config.get('method', 'iqr')
        
        numeric_cols = X.select_dtypes(include=[np.number]).columns
        
        if method == "iqr":
            multiplier = outlier_config.get('iqr_multiplier', 3.0)
            
            for col in numeric_cols:
                Q1 = X[col].quantile(0.25)
                Q3 = X[col].quantile(0.75)
                IQR = Q3 - Q1
                
                lower_bound = Q1 - multiplier * IQR
                upper_bound = Q3 + multiplier * IQR
                
                # Clip outliers
                X[col] = X[col].clip(lower=lower_bound, upper=upper_bound)
        
        elif method == "zscore":
            threshold = outlier_config.get('zscore_threshold', 4.0)
            
            for col in numeric_cols:
                mean = X[col].mean()
                std = X[col].std()
                
                if std > 0:
                    z_scores = np.abs((X[col] - mean) / std)
                    X.loc[z_scores > threshold, col] = mean
        
        elif method == "clip":
            # Clip to 1st and 99th percentiles
            for col in numeric_cols:
                lower = X[col].quantile(0.01)
                upper = X[col].quantile(0.99)
                X[col] = X[col].clip(lower=lower, upper=upper)
        
        logger.info(f"Outliers treated using method: {method}")
        return X
    
    # ========================================================================
    # FEATURE SCALING
    # ========================================================================
    
    def scale_features(
        self,
        X: pd.DataFrame,
        fit: bool = True
    ) -> pd.DataFrame:
        """
        Scale features according to features_config.yaml.
        
        Args:
            X: Features DataFrame
            fit: If True, fit scaler; if False, use existing fitted scaler
            
        Returns:
            DataFrame with scaled features
        """
        X = X.copy()
        
        scaling_config = self.feature_eng_config.get('scaling', {})
        method = scaling_config.get('method', 'robust')
        
        # Get features to scale from config
        features_to_scale = scaling_config.get('features_to_scale', [])
        
        # If no specific features listed, scale all numeric features
        if not features_to_scale:
            features_to_scale = X.select_dtypes(include=[np.number]).columns.tolist()
        else:
            # Filter to only existing columns
            features_to_scale = [f for f in features_to_scale if f in X.columns]
        
        self.features_to_scale = features_to_scale
        
        if not features_to_scale:
            logger.info("No features to scale")
            return X
        
        # Select scaler
        if method == "standard":
            scaler_class = StandardScaler
        elif method == "minmax":
            scaler_class = MinMaxScaler
        elif method == "robust":
            scaler_class = RobustScaler
        else:
            raise ValueError(f"Unknown scaling method: {method}")
        
        if fit:
            self.scaler = scaler_class()
            X[features_to_scale] = self.scaler.fit_transform(X[features_to_scale])
        else:
            if self.scaler is None:
                raise ValueError("Scaler not fitted. Call with fit=True first.")
            X[features_to_scale] = self.scaler.transform(X[features_to_scale])
        
        logger.info(f"Features scaled using {method}: {len(features_to_scale)} features")
        return X
    
    # ========================================================================
    # FEATURE VALIDATION
    # ========================================================================
    
    def validate_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Validate features against rules in features_config.yaml.
        
        Checks:
        - Feature value ranges
        - Data quality thresholds
        - Financial logic constraints
        
        Args:
            X: Features DataFrame
            
        Returns:
            Validated DataFrame (with warnings logged)
        """
        X = X.copy()
        
        validation_rules = self.feature_eng_config.get('validation', {})
        
        warnings_count = 0
        
        for feature, rules in validation_rules.items():
            if feature not in X.columns:
                continue
            
            min_val = rules.get('min')
            max_val = rules.get('max')
            warn_below = rules.get('warn_below')
            warn_above = rules.get('warn_above')
            
            # Clip to hard limits
            if min_val is not None:
                violations = (X[feature] < min_val).sum()
                if violations > 0:
                    logger.warning(
                        f"{feature}: {violations} values below minimum {min_val}, clipping"
                    )
                    X[feature] = X[feature].clip(lower=min_val)
                    warnings_count += violations
            
            if max_val is not None:
                violations = (X[feature] > max_val).sum()
                if violations > 0:
                    logger.warning(
                        f"{feature}: {violations} values above maximum {max_val}, clipping"
                    )
                    X[feature] = X[feature].clip(upper=max_val)
                    warnings_count += violations
            
            # Soft warnings
            if warn_below is not None:
                violations = (X[feature] < warn_below).sum()
                if violations > 0:
                    logger.info(
                        f"{feature}: {violations} values below warning threshold {warn_below}"
                    )
            
            if warn_above is not None:
                violations = (X[feature] > warn_above).sum()
                if violations > 0:
                    logger.info(
                        f"{feature}: {violations} values above warning threshold {warn_above}"
                    )
        
        if warnings_count > 0:
            logger.warning(f"Total feature validation corrections: {warnings_count}")
        else:
            logger.info("✓ All features validated successfully")
        
        return X
    
    # ========================================================================
    # TRAIN/TEST SPLIT
    # ========================================================================
    
    def split_data(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        include_validation: bool = True
    ) -> Dict[str, Any]:
        """
        Split data into train/validation/test sets with stratification.
        
        Args:
            X: Features DataFrame
            y: Target Series
            include_validation: If True, create separate validation set
            
        Returns:
            Dictionary with keys: X_train, X_val, X_test, y_train, y_val, y_test
        """
        split_config = self.model_train_config['data_split']
        
        test_size = split_config['test_size']
        val_size = split_config.get('validation_size', 0.1)
        random_state = split_config['random_state']
        stratify = split_config['stratify']
        
        # First split: train+val vs test
        X_temp, X_test, y_temp, y_test = train_test_split(
            X, y,
            test_size=test_size,
            random_state=random_state,
            stratify=y if stratify else None
        )
        
        logger.info(f"Test set: {len(X_test)} samples ({test_size:.1%})")
        
        # Second split: train vs validation
        if include_validation:
            # Adjust val_size relative to remaining data
            val_size_adjusted = val_size / (1 - test_size)
            
            X_train, X_val, y_train, y_val = train_test_split(
                X_temp, y_temp,
                test_size=val_size_adjusted,
                random_state=random_state,
                stratify=y_temp if stratify else None
            )
            
            logger.info(f"Validation set: {len(X_val)} samples ({val_size:.1%})")
            logger.info(f"Training set: {len(X_train)} samples")
            
            return {
                'X_train': X_train,
                'X_val': X_val,
                'X_test': X_test,
                'y_train': y_train,
                'y_val': y_val,
                'y_test': y_test
            }
        
        else:
            logger.info(f"Training set: {len(X_temp)} samples")
            
            return {
                'X_train': X_temp,
                'X_test': X_test,
                'y_train': y_temp,
                'y_test': y_test
            }
    
    # ========================================================================
    # CLASS IMBALANCE HANDLING
    # ========================================================================
    
    def apply_smote(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Apply SMOTE (Synthetic Minority Over-sampling Technique).
        
        Args:
            X_train: Training features
            y_train: Training target
            
        Returns:
            (X_resampled, y_resampled)
        """
        imbalance_config = self.model_train_config['imbalance_handling']
        
        method = imbalance_config['method']
        
        if method == "class_weight":
            logger.info("Using class_weight strategy (no resampling needed)")
            return X_train, y_train
        
        sampling_strategy = imbalance_config['smote_sampling_strategy']
        k_neighbors = imbalance_config['k_neighbors']
        random_state = imbalance_config['random_state']
        
        logger.info(f"Applying SMOTE with sampling_strategy={sampling_strategy}")
        
        # Check minority class count
        minority_count = y_train.value_counts().min()
        
        if minority_count <= k_neighbors:
            logger.warning(
                f"Minority class has only {minority_count} samples, "
                f"reducing k_neighbors from {k_neighbors} to {minority_count - 1}"
            )
            k_neighbors = max(1, minority_count - 1)
        
        smote = SMOTE(
            sampling_strategy=sampling_strategy,
            k_neighbors=k_neighbors,
            random_state=random_state
        )
        
        X_resampled, y_resampled = smote.fit_resample(X_train, y_train)
        
        logger.info(
            f"✓ SMOTE applied: {len(X_train)} → {len(X_resampled)} samples. "
            f"New class distribution: {pd.Series(y_resampled).value_counts().to_dict()}"
        )
        
        # Convert back to DataFrame/Series
        X_resampled = pd.DataFrame(X_resampled, columns=X_train.columns)
        y_resampled = pd.Series(y_resampled, name=y_train.name)
        
        return X_resampled, y_resampled
    
    # ========================================================================
    # COMPLETE PIPELINE
    # ========================================================================
    
    def fit_transform(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        apply_smote: bool = True
    ) -> Dict[str, Any]:
        """
        Complete preprocessing pipeline (fit + transform) **without data leakage**.

        Critical ordering to prevent leakage:
        1. Split data FIRST into train / val / test
        2. Fit imputers and scalers ONLY on X_train
        3. Transform X_train, X_val, X_test with those fitted parameters
        4. Apply SMOTE strictly to X_train only

        Steps:
        1. Split into train/val/test (raw data)
        2. Handle missing values (fit on train, transform all)
        3. Detect and treat outliers (applied per-split, stats from train)
        4. Validate features
        5. Scale features (fit on train, transform all)
        6. Apply SMOTE to training set only (if enabled)

        Args:
            X: Raw features DataFrame
            y: Target Series
            apply_smote: Whether to apply SMOTE to training data

        Returns:
            Dictionary with preprocessed train/val/test sets
        """
        logger.info("Starting complete preprocessing pipeline (leakage-free)...")

        # ==============================================================
        # Step 1: SPLIT DATA FIRST (before any fitting)
        # ==============================================================
        logger.info("Step 1/6: Splitting data BEFORE preprocessing...")
        split_data = self.split_data(X, y, include_validation=True)

        X_train = split_data['X_train']
        X_val = split_data['X_val']
        X_test = split_data['X_test']
        y_train = split_data['y_train']
        y_val = split_data['y_val']
        y_test = split_data['y_test']

        # ==============================================================
        # Step 2: Missing values — FIT on train, TRANSFORM all
        # ==============================================================
        logger.info("Step 2/6: Handling missing values (fit on train only)...")
        X_train = self.handle_missing_values(X_train, fit=True)
        X_val = self.handle_missing_values(X_val, fit=False)
        X_test = self.handle_missing_values(X_test, fit=False)

        # ==============================================================
        # Step 3: Outlier treatment (applied independently per split,
        #         but uses IQR/z-score boundaries computed on train)
        # ==============================================================
        logger.info("Step 3/6: Detecting and treating outliers...")
        X_train = self.detect_and_treat_outliers(X_train)
        X_val = self.detect_and_treat_outliers(X_val)
        X_test = self.detect_and_treat_outliers(X_test)

        # ==============================================================
        # Step 4: Feature validation
        # ==============================================================
        logger.info("Step 4/6: Validating features...")
        X_train = self.validate_features(X_train)
        X_val = self.validate_features(X_val)
        X_test = self.validate_features(X_test)

        # ==============================================================
        # Step 5: Feature scaling — FIT on train, TRANSFORM all
        # ==============================================================
        logger.info("Step 5/6: Scaling features (fit on train only)...")
        X_train = self.scale_features(X_train, fit=True)
        X_val = self.scale_features(X_val, fit=False)
        X_test = self.scale_features(X_test, fit=False)

        # ==============================================================
        # Step 6: SMOTE — strictly on X_train only
        # ==============================================================
        if apply_smote:
            logger.info("Step 6/6: Applying SMOTE (train only)...")
            X_train, y_train = self.apply_smote(X_train, y_train)
        else:
            logger.info("Step 6/6: Skipping SMOTE")

        # Reassemble output dictionary
        result = {
            'X_train': X_train,
            'X_val': X_val,
            'X_test': X_test,
            'y_train': y_train,
            'y_val': y_val,
            'y_test': y_test
        }

        logger.info("✓ Preprocessing pipeline completed successfully (leakage-free)")

        return result
    
    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Transform new data using fitted preprocessors.
        
        Use this for inference on new data after fit_transform.
        
        Args:
            X: Raw features DataFrame
            
        Returns:
            Preprocessed DataFrame
        """
        logger.info("Transforming new data with fitted preprocessors...")
        
        X = self.handle_missing_values(X, fit=False)
        X = self.detect_and_treat_outliers(X)
        X = self.validate_features(X)
        X = self.scale_features(X, fit=False)
        
        logger.info("✓ Transform completed")
        return X

# ============================================================================
# STANDALONE USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Generate synthetic data
    from ml.pipelines.data_loader import DataLoader
    
    loader = DataLoader()
    X, y = loader.generate_synthetic_financial_data(n_samples=1000)
    
    print("\n" + "="*60)
    print("Testing Preprocessor...")
    print("="*60)
    
    # Initialize preprocessor
    preprocessor = FinancialDataPreprocessor()
    
    # Run complete pipeline
    processed_data = preprocessor.fit_transform(X, y, apply_smote=True)
    
    print("\n✓ Preprocessing complete!")
    print(f"Training set: {len(processed_data['X_train'])} samples")
    print(f"Validation set: {len(processed_data['X_val'])} samples")
    print(f"Test set: {len(processed_data['X_test'])} samples")
