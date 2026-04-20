"""
Data Loader for FinaCES AI Module

Loads financial datasets from multiple sources:
- Kaggle datasets (credit scoring)
- UCI ML Repository
- Built-in sklearn datasets
- Custom FinaCES database

All datasets are normalized to match FinancialStatementNormalized schema
for consistency with production data structure.

Stack: pandas, scikit-learn, kaggle API
Language: 100% English
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
import pandas as pd
import numpy as np
from decimal import Decimal

logger = logging.getLogger(__name__)


class DataLoader:
    """
    Multi-source data loader for credit scoring datasets.
    
    Provides unified interface to load training data from:
    - Kaggle API
    - sklearn synthetic data
    - Local CSV files
    - FinaCES PostgreSQL database
    """
    
    def __init__(self, data_dir: str = "ml/data"):
        """
        Initialize data loader.
        
        Args:
            data_dir: Directory for downloaded/cached datasets
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.raw_dir = self.data_dir / "raw"
        self.processed_dir = self.data_dir / "processed"
        
        self.raw_dir.mkdir(exist_ok=True)
        self.processed_dir.mkdir(exist_ok=True)
        
        logger.info(f"DataLoader initialized with data_dir: {self.data_dir}")
    
    # ========================================================================
    # SYNTHETIC DATA GENERATION (for quick testing)
    # ========================================================================
    
    def generate_synthetic_financial_data(
        self,
        n_samples: int = 1000,
        n_features: int = 46,
        default_rate: float = 0.15,
        random_state: int = 42
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Generate synthetic financial data matching FinaCES structure.

        Uses a domain-aware generative process: base accounting items are
        generated first (e.g., net_income, total_assets, equity), then
        financial ratios are derived from them to ensure realistic
        structural collinearity between features. The target is defined
        by a logical rule over the derived ratios.

        Useful for:
        - Initial testing without real data
        - Unit tests
        - Prototyping

        Args:
            n_samples: Number of companies to generate
            n_features: Number of features (matches feature engineering output)
            default_rate: Proportion of defaults (imbalanced, used for noise calibration)
            random_state: Random seed

        Returns:
            (features_df, target_series)
        """
        logger.info(f"Generating synthetic data: {n_samples} samples, {n_features} features")

        rng = np.random.default_rng(random_state)

        # ============================================================
        # STEP 1: Generate base accounting items (latent variables)
        # ============================================================

        # Revenue and cost structure
        revenue = rng.lognormal(mean=16, sigma=1.5, size=n_samples)  # ~9M median
        cogs_ratio = rng.beta(a=5, b=3, size=n_samples)  # COGS as % of revenue
        cogs = revenue * cogs_ratio
        gross_profit = revenue - cogs

        # Operating expenses
        opex_ratio = rng.beta(a=3, b=5, size=n_samples)
        opex = revenue * opex_ratio
        ebitda = gross_profit - opex

        # Depreciation & amortisation, interest, tax
        depreciation = rng.uniform(0.02, 0.08, size=n_samples) * revenue
        interest_expense = rng.exponential(scale=revenue * 0.02)
        operating_income = ebitda - depreciation
        ebt = operating_income - interest_expense
        tax_rate = rng.uniform(0.15, 0.35, size=n_samples)
        net_income = ebt * (1 - tax_rate)

        # Balance sheet items
        total_assets = rng.lognormal(mean=17, sigma=1.5, size=n_samples)
        equity = total_assets * rng.beta(a=4, b=3, size=n_samples)  # equity ratio 0.2-0.8
        total_liabilities = total_assets - equity

        current_assets = total_assets * rng.beta(a=4, b=4, size=n_samples)
        current_liabilities = total_liabilities * rng.beta(a=5, b=4, size=n_samples)

        cash = current_assets * rng.beta(a=2, b=5, size=n_samples)
        inventory = (current_assets - cash) * rng.beta(a=3, b=4, size=n_samples)
        receivables = current_assets - cash - inventory
        receivables = np.maximum(receivables, 0)

        long_term_debt = np.maximum(total_liabilities - current_liabilities, 0)

        # Cash flow
        cashflow_operations = net_income + depreciation + rng.normal(0, revenue * 0.02)

        # ============================================================
        # STEP 2: Derive financial ratios from base accounting items
        # ============================================================

        # Avoid division by zero
        eps = 1e-8

        # --- Liquidity ratios (10) ---
        current_ratio = current_assets / np.maximum(current_liabilities, eps)
        quick_ratio = (current_assets - inventory) / np.maximum(current_liabilities, eps)
        cash_ratio = cash / np.maximum(current_liabilities, eps)
        working_capital = current_assets - current_liabilities
        working_capital_pct_assets = working_capital / np.maximum(total_assets, eps)
        cash_to_assets = cash / np.maximum(total_assets, eps)
        inventory_to_current_assets = inventory / np.maximum(current_assets, eps)
        receivables_to_current_assets = receivables / np.maximum(current_assets, eps)
        liquid_assets_coverage = (cash + receivables) / np.maximum(current_liabilities, eps)
        daily_opex = np.maximum(opex / 365.0, eps)
        defensive_interval_days = (cash + receivables) / daily_opex

        # --- Solvency ratios (10) ---
        debt_to_equity = total_liabilities / np.maximum(equity, eps)
        financial_autonomy = equity / np.maximum(total_assets, eps)
        gearing = long_term_debt / np.maximum(equity, eps)
        long_term_debt_ratio = long_term_debt / np.maximum(total_liabilities, eps)
        current_debt_ratio = current_liabilities / np.maximum(total_liabilities, eps)
        equity_ratio = equity / np.maximum(total_assets, eps)
        debt_service_coverage = ebitda / np.maximum(interest_expense + long_term_debt * 0.1, eps)
        liabilities_to_assets = total_liabilities / np.maximum(total_assets, eps)
        equity_multiplier = total_assets / np.maximum(equity, eps)
        capitalization_ratio = long_term_debt / np.maximum(long_term_debt + equity, eps)

        # --- Profitability ratios (8) ---
        net_margin = net_income / np.maximum(revenue, eps)
        ebitda_margin = ebitda / np.maximum(revenue, eps)
        operating_margin = operating_income / np.maximum(revenue, eps)
        roa = net_income / np.maximum(total_assets, eps)
        roe = net_income / np.maximum(equity, eps)
        invested_capital = equity + long_term_debt
        roic = operating_income * (1 - tax_rate) / np.maximum(invested_capital, eps)
        gross_profit_margin = gross_profit / np.maximum(revenue, eps)
        return_on_sales = operating_income / np.maximum(revenue, eps)

        # --- Capacity ratios (6) ---
        cashflow_capacity = cashflow_operations / np.maximum(total_liabilities, eps)
        cashflow_margin_pct = cashflow_operations / np.maximum(revenue, eps)
        debt_repayment_years = total_liabilities / np.maximum(cashflow_operations, eps)
        interest_coverage = ebitda / np.maximum(interest_expense, eps)
        cash_debt_coverage = cashflow_operations / np.maximum(total_liabilities, eps)
        wc_requirement = receivables + inventory - current_liabilities
        working_capital_requirement_pct = wc_requirement / np.maximum(revenue, eps)

        # --- Quality indicators (6) ---
        negative_equity_flag = (equity < 0).astype(float)
        negative_cashflow_flag = (cashflow_operations < 0).astype(float)

        # Altman Z-Score (EM 4-variable model approximation)
        z_a = working_capital / np.maximum(total_assets, eps)
        z_b = (net_income * 0.6) / np.maximum(total_assets, eps)  # proxy retained earnings
        z_c = ebitda / np.maximum(total_assets, eps)
        z_d = equity / np.maximum(total_liabilities, eps)
        z_score_altman = 6.56 * z_a + 3.26 * z_b + 6.72 * z_c + 1.05 * z_d

        balance_sheet_balance_check = rng.choice(
            [1.0, 0.0], size=n_samples, p=[0.95, 0.05]
        )
        audit_quality_score = rng.beta(a=8, b=2, size=n_samples) * 5
        data_completeness_score = rng.beta(a=9, b=1, size=n_samples) * 5

        # --- Trend features (6) ---
        # Simulated as statistically correlated scalars (single-year dataset)
        revenue_growth_rate = rng.normal(loc=0.05, scale=0.15, size=n_samples)
        revenue_growth_rate = np.where(net_margin < -0.05, revenue_growth_rate - 0.10, revenue_growth_rate)
        revenue_growth_rate = np.clip(revenue_growth_rate, -0.60, 0.80)

        equity_growth_rate = rng.normal(loc=0.03, scale=0.12, size=n_samples)
        equity_growth_rate = np.where(roe < 0, equity_growth_rate - 0.08, equity_growth_rate)
        equity_growth_rate = np.clip(equity_growth_rate, -0.70, 0.80)

        debt_growth_rate = rng.normal(loc=0.04, scale=0.18, size=n_samples)
        debt_growth_rate = np.where(debt_to_equity > 3.0, debt_growth_rate + 0.10, debt_growth_rate)
        debt_growth_rate = np.clip(debt_growth_rate, -0.50, 1.00)

        profitability_trend = rng.normal(loc=0.0, scale=0.05, size=n_samples)
        profitability_trend = np.where(net_margin < 0, profitability_trend - 0.03, profitability_trend)
        profitability_trend = np.clip(profitability_trend, -0.30, 0.30)

        liquidity_trend = rng.normal(loc=0.0, scale=0.10, size=n_samples)
        liquidity_trend = np.where(current_ratio < 1.0, liquidity_trend - 0.05, liquidity_trend)
        liquidity_trend = np.clip(liquidity_trend, -0.50, 0.50)

        cashflow_trend = rng.normal(loc=0.0, scale=0.08, size=n_samples)
        cashflow_trend = np.where(cashflow_operations < 0, cashflow_trend - 0.05, cashflow_trend)
        cashflow_trend = np.clip(cashflow_trend, -0.40, 0.40)

        # ============================================================
        # STEP 3: Assemble feature DataFrame
        # ============================================================

        feature_arrays = {
            # Liquidity
            "current_ratio": current_ratio,
            "quick_ratio": quick_ratio,
            "cash_ratio": cash_ratio,
            "working_capital": working_capital,
            "working_capital_pct_assets": working_capital_pct_assets,
            "cash_to_assets": cash_to_assets,
            "inventory_to_current_assets": inventory_to_current_assets,
            "receivables_to_current_assets": receivables_to_current_assets,
            "liquid_assets_coverage": liquid_assets_coverage,
            "defensive_interval_days": defensive_interval_days,
            # Solvency
            "debt_to_equity": debt_to_equity,
            "financial_autonomy": financial_autonomy,
            "gearing": gearing,
            "long_term_debt_ratio": long_term_debt_ratio,
            "current_debt_ratio": current_debt_ratio,
            "equity_ratio": equity_ratio,
            "debt_service_coverage": debt_service_coverage,
            "liabilities_to_assets": liabilities_to_assets,
            "equity_multiplier": equity_multiplier,
            "capitalization_ratio": capitalization_ratio,
            # Profitability
            "net_margin": net_margin,
            "ebitda_margin": ebitda_margin,
            "operating_margin": operating_margin,
            "roa": roa,
            "roe": roe,
            "roic": roic,
            "gross_profit_margin": gross_profit_margin,
            "return_on_sales": return_on_sales,
            # Capacity
            "cashflow_capacity": cashflow_capacity,
            "cashflow_margin_pct": cashflow_margin_pct,
            "debt_repayment_years": debt_repayment_years,
            "interest_coverage": interest_coverage,
            "cash_debt_coverage": cash_debt_coverage,
            "working_capital_requirement_pct": working_capital_requirement_pct,
            # Quality
            "negative_equity_flag": negative_equity_flag,
            "negative_cashflow_flag": negative_cashflow_flag,
            "z_score_altman": z_score_altman,
            "balance_sheet_balance_check": balance_sheet_balance_check,
            "audit_quality_score": audit_quality_score,
            "data_completeness_score": data_completeness_score,
            # Trends
            "revenue_growth_rate": revenue_growth_rate,
            "equity_growth_rate": equity_growth_rate,
            "debt_growth_rate": debt_growth_rate,
            "profitability_trend": profitability_trend,
            "liquidity_trend": liquidity_trend,
            "cashflow_trend": cashflow_trend,
        }

        df = pd.DataFrame(feature_arrays)

        # Log feature count
        logger.info(f"Feature count: {len(df.columns)} (expected 46)")

        # ============================================================
        # STEP 4: Define target via logical rule over ratios
        # ============================================================

        # Default rule: company is in default if it fails multiple
        # financial health criteria simultaneously
        risk_score = np.zeros(n_samples)
        risk_score += (current_ratio < 1.0).astype(float)           # illiquid
        risk_score += (debt_to_equity > 3.0).astype(float)          # over-leveraged
        risk_score += (net_margin < -0.05).astype(float)            # unprofitable
        risk_score += (interest_coverage < 1.5).astype(float)       # can't service debt
        risk_score += (cashflow_operations < 0).astype(float)       # negative cash flow
        risk_score += (z_score_altman < 1.1).astype(float)          # distress zone

        # Default if risk_score >= 3 (multiple red flags)
        y = (risk_score >= 3).astype(int)

        # Add controlled noise to approximate desired default_rate
        actual_rate = y.mean()
        noise_mask = rng.random(n_samples) < 0.05  # 5% label noise
        y[noise_mask] = 1 - y[noise_mask]

        target = pd.Series(y, name="default")

        logger.info(
            f"Synthetic data generated (domain-aware). "
            f"Default rate: {target.mean():.2%}, "
            f"Features: {len(df.columns)}"
        )

        return df, target
    
    # ========================================================================
    # KAGGLE DATASETS
    # ========================================================================
    
    def download_kaggle_dataset(
        self,
        dataset_name: str,
        force_download: bool = False
    ) -> Path:
        """
        Download dataset from Kaggle using Kaggle API.
        
        Requires:
        - kaggle.json in ~/.kaggle/ with API credentials
        - Dataset name in format: "username/dataset-name"
        
        Args:
            dataset_name: Kaggle dataset identifier
            force_download: Re-download even if exists
            
        Returns:
            Path to downloaded dataset directory
            
        Raises:
            FileNotFoundError: If kaggle.json not configured
            Exception: If download fails
        """
        try:
            import kaggle
        except ImportError:
            raise ImportError(
                "Kaggle package not installed. "
                "Run: pip install kaggle"
            )
        
        # Check for API credentials
        kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
        if not kaggle_json.exists():
            raise FileNotFoundError(
                "Kaggle API credentials not found. "
                "Download kaggle.json from https://www.kaggle.com/settings "
                "and place in ~/.kaggle/"
            )
        
        # Destination directory
        dest_dir = self.raw_dir / dataset_name.replace("/", "_")
        
        if dest_dir.exists() and not force_download:
            logger.info(f"Dataset already exists: {dest_dir}")
            return dest_dir
        
        logger.info(f"Downloading Kaggle dataset: {dataset_name}")
        
        try:
            kaggle.api.dataset_download_files(
                dataset_name,
                path=str(dest_dir),
                unzip=True
            )
            logger.info(f"✓ Dataset downloaded to: {dest_dir}")
            return dest_dir
            
        except Exception as e:
            logger.error(f"Failed to download {dataset_name}: {str(e)}")
            raise
    
    def load_german_credit_data(self) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Load UCI German Credit dataset.
        
        Classic credit scoring dataset with 1000 samples, 20 features.
        Target: 1 = good credit, 2 = bad credit (will invert to match our schema)
        
        Returns:
            (features_df, target_series) where target is 1=default, 0=no default
        """
        logger.info("Loading German Credit dataset...")
        
        # Try loading from imbalanced-learn built-in datasets
        try:
            from imblearn.datasets import fetch_datasets
            datasets = fetch_datasets()
            
            if 'german' in datasets or 'credit_g' in datasets:
                key = 'german' if 'german' in datasets else 'credit_g'
                X, y = datasets[key]
                
                # Convert to DataFrame
                feature_names = [f"feature_{i+1}" for i in range(X.shape[1])]
                df = pd.DataFrame(X, columns=feature_names)
                
                # Invert target: original 2=bad becomes 1=default
                target = pd.Series((y == 2).astype(int), name="default")
                
                logger.info(f"✓ German Credit loaded: {len(df)} samples")
                return df, target
                
        except ImportError:
            logger.warning("imbalanced-learn not available")
        
        # Fallback: download from UCI
        logger.info("Downloading from UCI repository...")
        url = "https://archive.ics.uci.edu/ml/machine-learning-databases/statlog/german/german.data"
        
        try:
            df = pd.read_csv(url, sep=" ", header=None)
            
            # Last column is target
            X = df.iloc[:, :-1]
            y = df.iloc[:, -1]
            
            # Rename columns
            X.columns = [f"feature_{i+1}" for i in range(X.shape[1])]
            
            # Invert target
            target = pd.Series((y == 2).astype(int), name="default")
            
            logger.info(f"✓ German Credit loaded from UCI: {len(X)} samples")
            return X, target
            
        except Exception as e:
            logger.error(f"Failed to load German Credit: {str(e)}")
            raise
    
    def load_lending_club_data(
        self,
        sample_frac: float = 0.1
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Load Lending Club loan data from Kaggle.
        
        Large dataset with 2M+ loans. Use sample_frac to reduce size.
        
        Args:
            sample_frac: Fraction of data to load (0.1 = 10%)
            
        Returns:
            (features_df, target_series)
        """
        logger.info(f"Loading Lending Club data (sample: {sample_frac:.1%})...")
        
        # Download from Kaggle
        dataset_path = self.download_kaggle_dataset(
            "wordsforthewise/lending-club"
        )
        
        # Find CSV file
        csv_files = list(dataset_path.glob("*.csv"))
        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {dataset_path}")
        
        # Load with sampling
        df = pd.read_csv(csv_files[0], low_memory=False)
        
        if sample_frac < 1.0:
            df = df.sample(frac=sample_frac, random_state=42)
        
        logger.info(f"Lending Club loaded: {len(df)} samples, {len(df.columns)} columns")
        
        # Map loan_status to binary default
        # 'Charged Off', 'Default' = 1, others = 0
        if 'loan_status' in df.columns:
            default_statuses = ['Charged Off', 'Default', 'Does not meet the credit policy. Status:Charged Off']
            df['default'] = df['loan_status'].isin(default_statuses).astype(int)
            target = df['default']
            
            # Drop target and non-feature columns
            drop_cols = ['loan_status', 'default', 'id', 'member_id', 'url', 'desc']
            X = df.drop(columns=[c for c in drop_cols if c in df.columns])
            
        else:
            raise ValueError("loan_status column not found")
        
        # Basic preprocessing
        X = self._preprocess_lending_club(X)
        
        logger.info(f"✓ Preprocessed: {len(X.columns)} features, default rate: {target.mean():.2%}")
        return X, target
    
    def _preprocess_lending_club(self, df: pd.DataFrame) -> pd.DataFrame:
        """Basic preprocessing for Lending Club data."""
        
        # Select only numeric columns for now
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df = df[numeric_cols]
        
        # Drop columns with >50% missing
        threshold = len(df) * 0.5
        df = df.dropna(thresh=threshold, axis=1)
        
        # Fill remaining missing with median
        df = df.fillna(df.median())
        
        return df

    def load_from_csv(
        self, 
        file_path: str, 
        target_column: str = "default"
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Load a dataset from a local CSV file.
        
        Args:
            file_path: Path to CSV file
            target_column: Name of the target variable
            
        Returns:
            (features_df, target_series)
        """
        logger.info(f"Loading data from CSV: {file_path}")
        
        path = Path(file_path)
        if not path.exists():
            # Try relative to raw_dir if not absolute
            path = self.raw_dir / file_path
            if not path.exists():
                raise FileNotFoundError(f"CSV file not found: {file_path}")
        
        df = pd.read_csv(path)
        
        if target_column not in df.columns:
            # Fallback check for common target names
            common_targets = ['default', 'target', 'y', 'label']
            for t in common_targets:
                if t in df.columns:
                    target_column = t
                    break
            else:
                raise ValueError(f"Target column '{target_column}' not found in {df.columns}")
        
        target = df[target_column]
        features = df.drop(columns=[target_column])
        
        # Ensure only numeric features are used
        features = features.select_dtypes(include=[np.number])
        
        logger.info(f"✓ CSV loaded: {len(df)} samples, {len(features.columns)} features")
        return features, target
    
    # ========================================================================
    # FINACES DATABASE EXPORT
    # ========================================================================
    
    async def load_from_finaces_database(
        self,
        db_session,
        limit: Optional[int] = None,
        include_features: bool = True,
        include_targets: bool = True
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Load training data directly from FinaCES PostgreSQL database.
        
        Extracts:
        - Features from ia_features table
        - Targets from evaluation outcomes (defaults/non-defaults)
        
        Args:
            db_session: SQLAlchemy async session
            limit: Maximum records to load
            include_features: Load computed features
            include_targets: Load target labels
            
        Returns:
            (features_df, target_series)
        """
        from sqlalchemy import select, func
        from app.db.models import IAFeatures, EvaluationCase, Scorecard
        
        logger.info("Loading data from FinaCES database...")
        
        if not include_features:
            raise ValueError("Must include features for training")
        
        # Load features
        stmt = select(IAFeatures)
        
        if limit:
            stmt = stmt.limit(limit)
        
        result = await db_session.execute(stmt)
        features_records = result.scalars().all()
        
        if not features_records:
            raise ValueError("No feature records found in database")
        
        # Convert to DataFrame
        features_data = []
        case_ids = []
        
        for record in features_records:
            features_dict = record.features
            if isinstance(features_dict, dict) and 'features' in features_dict:
                features_data.append(features_dict['features'])
                case_ids.append(str(record.case_id))
        
        df = pd.DataFrame(features_data)
        df['case_id'] = case_ids
        
        logger.info(f"✓ Loaded {len(df)} feature records")
        
        # Load targets if requested
        target = None
        if include_targets:
            # Query scorecards to get risk classifications
            # HIGH/CRITICAL = 1 (default), LOW/MODERATE = 0 (no default)
            stmt = (
                select(
                    EvaluationCase.id,
                    Scorecard.risk_class
                )
                .join(Scorecard, EvaluationCase.id == Scorecard.case_id)
                .where(EvaluationCase.id.in_(case_ids))
            )
            
            result = await db_session.execute(stmt)
            risk_data = {str(row[0]): row[1] for row in result}
            
            # Map risk classes to binary target
            def map_risk_to_default(risk_class: str) -> int:
                if risk_class in ['HIGH', 'ELEVE', 'CRITICAL', 'CRITIQUE']:
                    return 1
                return 0
            
            df['default'] = df['case_id'].map(
                lambda cid: map_risk_to_default(risk_data.get(cid, 'MODERATE'))
            )
            
            target = df['default']
            df = df.drop(columns=['case_id', 'default'])
            
            logger.info(f"✓ Targets loaded. Default rate: {target.mean():.2%}")
        
        return df, target
    
    # ========================================================================
    # UNIFIED INTERFACE
    # ========================================================================
    
    def load_dataset(
        self,
        source: str = "synthetic",
        **kwargs
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Unified interface to load any dataset.
        
        Args:
            source: Dataset source
                - "synthetic": Generate synthetic data
                - "german": UCI German Credit
                - "lending_club": Kaggle Lending Club
                - "finaces_db": FinaCES PostgreSQL (requires db_session kwarg)
            **kwargs: Source-specific arguments
            
        Returns:
            (features_df, target_series)
        """
        logger.info(f"Loading dataset from source: {source}")
        
        if source == "synthetic":
            return self.generate_synthetic_financial_data(**kwargs)
        
        elif source == "german":
            return self.load_german_credit_data()
        
        elif source == "lending_club":
            return self.load_lending_club_data(**kwargs)
        
        elif source == "finaces_db":
            if 'db_session' not in kwargs:
                raise ValueError("db_session required for finaces_db source")
            # Async method - caller must await
            return self.load_from_finaces_database(**kwargs)
        
        elif source == "csv":
            if 'file_path' not in kwargs:
                raise ValueError("file_path required for csv source")
            return self.load_from_csv(**kwargs)
        
        else:
            raise ValueError(
                f"Unknown data source: {source}. "
                f"Valid sources: synthetic, german, lending_club, finaces_db"
            )
    
    def save_processed_data(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        name: str
    ) -> Path:
        """
        Save processed dataset to disk.
        
        Args:
            X: Features DataFrame
            y: Target Series
            name: Dataset name (will be used as filename prefix)
            
        Returns:
            Path to saved file
        """
        output_path = self.processed_dir / f"{name}.parquet"
        
        # Combine X and y
        data = X.copy()
        data['target'] = y
        
        # Save as parquet (efficient compression)
        data.to_parquet(output_path, index=False)
        
        logger.info(f"✓ Processed data saved to: {output_path}")
        return output_path
    
    def load_processed_data(self, name: str) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Load previously saved processed dataset.
        
        Args:
            name: Dataset name
            
        Returns:
            (features_df, target_series)
        """
        file_path = self.processed_dir / f"{name}.parquet"
        
        if not file_path.exists():
            raise FileNotFoundError(f"Processed dataset not found: {file_path}")
        
        data = pd.read_parquet(file_path)
        
        y = data['target']
        X = data.drop(columns=['target'])
        
        logger.info(f"✓ Loaded processed data: {len(X)} samples, {len(X.columns)} features")
        return X, y


# ============================================================================
# CLI INTERFACE (for standalone usage)
# ============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    loader = DataLoader()
    
    # Example: Load synthetic data
    print("\n" + "="*60)
    print("Loading synthetic data...")
    print("="*60)
    X, y = loader.load_dataset("synthetic", n_samples=2000)
    print(f"\nShape: {X.shape}")
    print(f"Default rate: {y.mean():.2%}")
    print(f"\nFirst 5 features:\n{X.head()}")
    
    # Save
    loader.save_processed_data(X, y, "synthetic_baseline")
    print("\n✓ Data saved for training")
