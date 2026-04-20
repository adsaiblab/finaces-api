"""
Feature Engineering Module for AI Scoring System

This module implements the complete feature extraction pipeline as specified in Bloc 1.
It computes 40+ financial features from normalized accounting data, organized into
5 MCC pillars: Liquidity, Solvency, Profitability, Contractual Capacity, and Quality.

All features are computed from the normalized JSON structure (balance_sheet, income_statement, cash_flow)
and include proper handling of missing values, outliers, and edge cases.

Stack: SQLAlchemy 2.0 Async, Pydantic V2, FastAPI, PostgreSQL
Language: 100% English (code, comments, docstrings, exceptions)
"""

from typing import Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import (
    EvaluationCase,
    FinancialStatementNormalized,
    FinancialStatementRaw,
    RatioSet,
    Scorecard
)
from app.exceptions.finaces_exceptions import (
    MissingFinancialDataError,
    InsufficientFiscalYearsError
)

logger = logging.getLogger(__name__)


class FeatureEngineeringEngine:
    """
    Feature engineering engine for AI scoring module.
    
    Computes 40+ financial features from normalized accounting data,
    handling missing values, outliers, and edge cases according to
    MCC standards and Bloc 1 specifications.
    """
    
    # Feature caps for outlier handling (winsorization)
    CAPS = {
        "current_ratio": 10.0,
        "quick_ratio": 10.0,
        "debt_to_equity": 20.0,
        "roe": 2.0,  # 200% max
        "roa": 1.0,  # 100% max
        "contract_to_revenue": 5.0  # 500% max
    }
    
    # Minimum required years for trend calculation
    MIN_YEARS_FOR_TREND = 2
    
    def __init__(self):
        """Initialize the feature engineering engine."""
        self.computed_features: Dict[str, Any] = {}
        self.missing_flags: Dict[str, bool] = {}
        self.capped_flags: Dict[str, bool] = {}
    
    async def compute_all_features(
        self,
        case_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Compute all features for a given case.
        
        Args:
            case_id: Unique identifier of the evaluation case
            db: Async database session
            
        Returns:
            Dictionary containing all computed features, flags, and metadata
            
        Raises:
            MissingFinancialDataError: If required financial data is missing
            InsufficientFiscalYearsError: If less than 2 years of data available
        """
        logger.info(f"Starting feature engineering for case {case_id}")
        
        # Reset internal state
        self.computed_features = {}
        self.missing_flags = {}
        self.capped_flags = {}
        
        # Load case with related data
        case = await self._load_case_with_relations(case_id, db)
        
        if not case:
            raise MissingFinancialDataError(
                f"Case {case_id} not found in database"
            )
        
        # Load normalized financial statements (multi-year)
        normalized_statements = await self._load_normalized_statements(case_id, db)
        
        if len(normalized_statements) < 2:
            raise InsufficientFiscalYearsError(
                f"At least 2 fiscal years required for AI features. Found: {len(normalized_statements)}"
            )
        
        # Load ratio sets (pre-computed by ratio_engine)
        ratio_sets = await self._load_ratio_sets(case_id, db)
        
        # Load scorecard (if exists)
        scorecard = await self._load_scorecard(case_id, db)
        
        # Extract most recent normalized statement
        latest_statement = self._get_latest_statement(normalized_statements)
        
        # Verify critical fields are present
        balance_sheet = latest_statement.get("balance_sheet", {})
        income_statement = latest_statement.get("income_statement", {})
        
        total_assets = self._safe_get_nested(balance_sheet, ["TOTAL_ASSETS", "total"])
        equity_total = self._safe_get_nested(balance_sheet, ["EQUITY", "total"])
        revenue = self._safe_get_nested(income_statement, ["OPERATING_REVENUE"])
        
        if total_assets is None or equity_total is None or revenue is None:
            raise MissingFinancialDataError(
                f"Missing critical financial data for case {case_id}: "
                f"assets={total_assets is not None}, equity={equity_total is not None}, "
                f"revenue={revenue is not None}"
            )
        
        # Compute features by family
        self._compute_identification_features(case, latest_statement)
        self._compute_liquidity_features(latest_statement, ratio_sets)
        self._compute_solvency_features(latest_statement, ratio_sets)
        self._compute_profitability_features(latest_statement, ratio_sets, normalized_statements)
        self._compute_contractual_capacity_features(case, latest_statement, scorecard)
        self._compute_quality_features(case, normalized_statements)
        self._compute_trend_features(normalized_statements, ratio_sets)
        
        # Assemble final feature set
        features = {
            "case_id": str(case_id),
            "computed_at": datetime.utcnow().isoformat(),
            "features": self.computed_features,
            "missing_flags": self.missing_flags,
            "capped_flags": self.capped_flags,
            "metadata": {
                "case_id": str(case_id),
                "computed_at": datetime.utcnow().isoformat(),
                "num_fiscal_years": len(normalized_statements),
                "latest_fiscal_year": latest_statement.get("fiscal_year"),
                "fiscal_years_used": [s.get("fiscal_year") for s in normalized_statements if s.get("fiscal_year")],
                "feature_count": len(self.computed_features)
            }
        }
        
        logger.info(
            f"Feature engineering completed for case {case_id}. "
            f"Computed {len(self.computed_features)} features."
        )
        
        return features
    
    # ========================================================================
    # DATA LOADING METHODS
    # ========================================================================
    
    async def _load_case_with_relations(
        self,
        case_id: str,
        db: AsyncSession
    ) -> Optional[EvaluationCase]:
        """Load case with all required relationships."""
        stmt = (
            select(EvaluationCase)
            .where(EvaluationCase.id == case_id)
            .options(
                selectinload(EvaluationCase.bidder)
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def _load_normalized_statements(
        self,
        case_id: str,
        db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """Load normalized financial statements for all available years."""
        stmt = (
            select(FinancialStatementNormalized)
            .join(
                FinancialStatementRaw,
                FinancialStatementNormalized.raw_statement_id == FinancialStatementRaw.id
            )
            .where(FinancialStatementRaw.case_id == case_id)
            .order_by(FinancialStatementNormalized.fiscal_year.desc())
        )
        result = await db.execute(stmt)
        statements = result.scalars().all()
        
        # Convert flat ORM columns to nested dict format for feature computation
        return [
            {
                "fiscal_year": s.fiscal_year,
                "balance_sheet": {
                    "TOTAL_ASSETS": {"total": float(s.total_assets) if s.total_assets else None},
                    "CURRENT_ASSETS": {
                        "total": float(s.current_assets) if s.current_assets else None,
                        "CASH_EQUIVALENTS": float(s.liquid_assets) if s.liquid_assets else None,
                        "INVENTORY_WIP": float(s.inventory) if s.inventory else None,
                        "TRADE_RECEIVABLES": float(s.accounts_receivable) if s.accounts_receivable else None,
                        "OTHER": float(s.other_current_assets) if s.other_current_assets else None,
                    },
                    "NON_CURRENT_ASSETS": {
                        "total": float(s.non_current_assets) if s.non_current_assets else None,
                        "TANGIBLE": float(s.tangible_assets) if s.tangible_assets else None,
                        "INTANGIBLE": float(s.intangible_assets) if s.intangible_assets else None,
                        "FINANCIAL": float(s.financial_assets) if s.financial_assets else None,
                    },
                    "TOTAL_LIABILITIES_EQUITY": {"total": float(s.total_liabilities_and_equity) if s.total_liabilities_and_equity else None},
                    "EQUITY": {
                        "total": float(s.equity) if s.equity else None,
                        "SHARE_CAPITAL": float(s.share_capital) if s.share_capital else None,
                        "RESERVES": float(s.reserves) if s.reserves else None,
                        "RETAINED_EARNINGS": float(s.retained_earnings_prior) if s.retained_earnings_prior else None,
                    },
                    "NON_CURRENT_LIABILITIES": {
                        "total": float(s.non_current_liabilities) if s.non_current_liabilities else None,
                        "LONG_TERM_DEBT": float(s.long_term_debt) if s.long_term_debt else None,
                    },
                    "CURRENT_LIABILITIES": {
                        "total": float(s.current_liabilities) if s.current_liabilities else None,
                        "SHORT_TERM_DEBT": float(s.short_term_debt) if s.short_term_debt else None,
                        "TRADE_PAYABLES": float(s.accounts_payable) if s.accounts_payable else None,
                        "TAX_SOCIAL": float(s.tax_and_social_liabilities) if s.tax_and_social_liabilities else None,
                    },
                },
                "income_statement": {
                    "OPERATING_REVENUE": float(s.revenue) if s.revenue else None,
                    "REVENUE": float(s.revenue) if s.revenue else None,
                    "COGS": float(s.cost_of_goods_sold) if s.cost_of_goods_sold else None,
                    "EXTERNAL_EXPENSES": float(s.external_expenses) if s.external_expenses else None,
                    "PERSONNEL_EXPENSES": float(s.personnel_expenses) if s.personnel_expenses else None,
                    "DEPRECIATION": float(s.depreciation_and_amortization) if s.depreciation_and_amortization else None,
                    "OPERATING_INCOME": float(s.operating_income) if s.operating_income else None,
                    "FINANCIAL_EXPENSES": float(s.financial_expenses) if s.financial_expenses else None,
                    "NET_INCOME": float(s.net_income) if s.net_income else None,
                    "EBITDA": float(s.ebitda) if s.ebitda else None,
                    "INCOME_BEFORE_TAX": float(s.income_before_tax) if s.income_before_tax else None,
                },
                "cash_flow": {
                    "OPERATING": float(s.operating_cash_flow) if s.operating_cash_flow else None,
                    "INVESTING": float(s.investing_cash_flow) if s.investing_cash_flow else None,
                    "FINANCING": float(s.financing_cash_flow) if s.financing_cash_flow else None,
                    "CHANGE_IN_CASH": float(s.change_in_cash) if s.change_in_cash else None,
                },
                "operational": {
                    "HEADCOUNT": s.headcount,
                    "CAPEX": float(s.capex) if s.capex else None,
                },
            }
            for s in statements
        ]
    
    async def _load_ratio_sets(
        self,
        case_id: str,
        db: AsyncSession
    ) -> List[RatioSet]:
        """Load pre-computed ratio sets."""
        stmt = (
            select(RatioSet)
            .where(RatioSet.case_id == case_id)
            .order_by(RatioSet.fiscal_year.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().all()
    
    async def _load_scorecard(
        self,
        case_id: str,
        db: AsyncSession
    ) -> Optional[Scorecard]:
        """Load the most recent scorecard if exists."""
        stmt = (
            select(Scorecard)
            .where(Scorecard.case_id == case_id)
            .order_by(Scorecard.computed_at.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().first()
    
    def _get_latest_statement(
        self,
        statements: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Get the most recent fiscal year statement."""
        return statements[0] if statements else {}
    
    # ========================================================================
    # FEATURE COMPUTATION - IDENTIFICATION & CONTEXT
    # ========================================================================
    
    def _compute_identification_features(
        self,
        case: EvaluationCase,
        statement: Dict[str, Any]
    ) -> None:
        """
        Compute identification and context features.
        
        Features:
        - entity_id
        - case_id
        - fiscal_year
        - sector
        - country
        - size_class
        """
        self.computed_features["entity_id"] = str(case.bidder.id) if case.bidder else None
        self.computed_features["case_id"] = str(case.id)
        self.computed_features["fiscal_year"] = statement.get("fiscal_year")
        self.computed_features["sector"] = case.bidder.sector if case.bidder else None
        self.computed_features["country"] = case.bidder.country if case.bidder else "MA"
        
        # Size classification based on total assets or revenue
        balance_sheet = statement.get("balance_sheet", {})
        total_assets = self._safe_get_nested(balance_sheet, ["TOTAL_ASSETS", "total"])
        
        if total_assets:
            if total_assets < 10_000_000:
                size_class = "MICRO"
            elif total_assets < 50_000_000:
                size_class = "SME"
            else:
                size_class = "LARGE"
        else:
            size_class = "UNKNOWN"
            self.missing_flags["total_assets"] = True
        
        self.computed_features["size_class"] = size_class
    
    # ========================================================================
    # FEATURE COMPUTATION - LIQUIDITY (Pillar 1)
    # ========================================================================
    
    def _compute_liquidity_features(
        self,
        statement: Dict[str, Any],
        ratio_sets: List[RatioSet]
    ) -> None:
        """
        Compute liquidity features (MCC Pillar 1).
        
        Features:
        - current_ratio
        - quick_ratio
        - cash_ratio
        - days_receivables
        - liquidity_stress (flag)
        """
        balance_sheet = statement.get("balance_sheet", {})
        income_statement = statement.get("income_statement", {})
        
        # Extract source variables
        current_assets = self._safe_get_nested(balance_sheet, ["CURRENT_ASSETS", "total"])
        current_liabilities = self._safe_get_nested(balance_sheet, ["CURRENT_LIABILITIES", "total"])
        cash_equivalents = self._safe_get_nested(balance_sheet, ["CURRENT_ASSETS", "CASH_EQUIVALENTS"])
        inventory_wip = self._safe_get_nested(balance_sheet, ["CURRENT_ASSETS", "INVENTORY_WIP"])
        trade_receivables = self._safe_get_nested(balance_sheet, ["CURRENT_ASSETS", "TRADE_RECEIVABLES"])
        operating_revenue = self._safe_get_nested(income_statement, ["OPERATING_REVENUE"])
        
        # Current Ratio
        current_ratio = self._safe_divide(current_assets, current_liabilities)
        self.computed_features["current_ratio"] = self._cap_value(
            current_ratio, "current_ratio"
        )
        
        # Quick Ratio
        if current_assets is not None and inventory_wip is not None and current_liabilities is not None:
            quick_assets = current_assets - inventory_wip
            quick_ratio = self._safe_divide(quick_assets, current_liabilities)
            self.computed_features["quick_ratio"] = self._cap_value(
                quick_ratio, "quick_ratio"
            )
        else:
            quick_ratio = None
            self.computed_features["quick_ratio"] = None
            self.missing_flags["quick_ratio"] = True
        
        # Cash Ratio
        cash_ratio = self._safe_divide(cash_equivalents, current_liabilities)
        self.computed_features["cash_ratio"] = cash_ratio
        
        # Days Receivables
        if trade_receivables is not None and operating_revenue is not None and operating_revenue > 0:
            days_receivables = (trade_receivables / operating_revenue) * 365
            self.computed_features["days_receivables"] = round(days_receivables, 1)
        else:
            self.computed_features["days_receivables"] = None
            self.missing_flags["days_receivables"] = True
        
        # Liquidity Stress Flag
        liquidity_stress = (
            current_ratio is not None and current_ratio < 1.0
        ) or (
            quick_ratio is not None and quick_ratio < 0.8
        )
        self.computed_features["liquidity_stress"] = liquidity_stress
        
        # Working Capital
        if current_assets is not None and current_liabilities is not None:
            self.computed_features["working_capital"] = current_assets - current_liabilities
        else:
            self.computed_features["working_capital"] = None
            self.missing_flags["working_capital"] = True
    
    # ========================================================================
    # FEATURE COMPUTATION - SOLVENCY (Pillar 2)
    # ========================================================================
    
    def _compute_solvency_features(
        self,
        statement: Dict[str, Any],
        ratio_sets: List[RatioSet]
    ) -> None:
        """
        Compute solvency features (MCC Pillar 2).
        
        Features:
        - debt_to_equity
        - equity_ratio
        - long_term_debt_ratio
        - negative_equity (flag)
        - total_debt_amount
        """
        balance_sheet = statement.get("balance_sheet", {})
        
        # Extract source variables
        equity_total = self._safe_get_nested(balance_sheet, ["EQUITY", "total"])
        total_assets = self._safe_get_nested(balance_sheet, ["TOTAL_ASSETS", "total"])
        long_term_debt = self._safe_get_nested(balance_sheet, ["NON_CURRENT_LIABILITIES", "LONG_TERM_DEBT"])
        short_term_debt = self._safe_get_nested(balance_sheet, ["CURRENT_LIABILITIES", "SHORT_TERM_DEBT"])
        
        # Total Debt
        total_debt = self._safe_add(long_term_debt, short_term_debt)
        self.computed_features["total_debt_amount"] = total_debt
        self.computed_features["long_term_debt"] = long_term_debt
        self.computed_features["short_term_debt"] = short_term_debt
        
        # Debt to Equity
        debt_to_equity = self._safe_divide(total_debt, equity_total)
        self.computed_features["debt_to_equity"] = self._cap_value(
            debt_to_equity, "debt_to_equity"
        )
        
        # Equity Ratio
        equity_ratio = self._safe_divide(equity_total, total_assets)
        self.computed_features["equity_ratio"] = equity_ratio
        
        # Long-Term Debt Ratio
        long_term_debt_ratio = self._safe_divide(long_term_debt, total_assets)
        self.computed_features["long_term_debt_ratio"] = long_term_debt_ratio
        
        # Financial Autonomy
        financial_autonomy = self._safe_divide(equity_total, total_assets)
        self.computed_features["financial_autonomy"] = self._cap_value(
            financial_autonomy, "financial_autonomy"
        )
        
        # Gearing
        gearing = self._safe_divide(total_debt, equity_total)
        self.computed_features["gearing"] = self._cap_value(
            gearing, "gearing"
        )
        
        # Negative Equity Flag
        negative_equity = equity_total is not None and equity_total < 0
        self.computed_features["negative_equity_flag"] = int(negative_equity) if negative_equity else 0
    
    # ========================================================================
    # FEATURE COMPUTATION - PROFITABILITY (Pillar 3)
    # ========================================================================
    
    def _compute_profitability_features(
        self,
        statement: Dict[str, Any],
        ratio_sets: List[RatioSet],
        all_statements: List[Dict[str, Any]]
    ) -> None:
        """
        Compute profitability features (MCC Pillar 3).
        
        Features:
        - net_margin
        - operating_margin
        - roa (Return on Assets)
        - roe (Return on Equity)
        - consecutive_profitable_years
        - volatile_profits (flag)
        """
        balance_sheet = statement.get("balance_sheet", {})
        income_statement = statement.get("income_statement", {})
        
        # Extract source variables
        operating_revenue = self._safe_get_nested(income_statement, ["OPERATING_REVENUE"])
        operating_income = self._safe_get_nested(income_statement, ["OPERATING_INCOME"])
        net_income = self._safe_get_nested(income_statement, ["NET_INCOME"])
        total_assets = self._safe_get_nested(balance_sheet, ["TOTAL_ASSETS", "total"])
        equity_total = self._safe_get_nested(balance_sheet, ["EQUITY", "total"])
        
        # Net Margin
        net_margin = self._safe_divide(net_income, operating_revenue)
        self.computed_features["net_margin"] = net_margin
        
        # Operating Margin
        operating_margin = self._safe_divide(operating_income, operating_revenue)
        self.computed_features["operating_margin"] = operating_margin
        
        # ROA (Return on Assets)
        roa = self._safe_divide(net_income, total_assets)
        self.computed_features["roa"] = self._cap_value(roa, "roa")
        
        # ROE (Return on Equity)
        if equity_total is not None and equity_total > 0:
            roe = self._safe_divide(net_income, equity_total)
            self.computed_features["roe"] = self._cap_value(roe, "roe")
        else:
            self.computed_features["roe"] = None
            self.missing_flags["roe"] = True
            
        # EBITDA Margin
        ebitda = self._safe_get_nested(income_statement, ["EBITDA"])
        ebitda_margin = self._safe_divide(ebitda, operating_revenue)
        self.computed_features["ebitda_margin"] = ebitda_margin
        
        # Profitability Stability Features
        net_incomes = []
        for stmt in all_statements[:3]:  # Last 3 years
            ni = self._safe_get_nested(stmt.get("income_statement", {}), ["NET_INCOME"])
            if ni is not None:
                net_incomes.append(ni)
        
        if len(net_incomes) >= 2:
            # Count consecutive profitable years
            consecutive_profitable = sum(1 for ni in net_incomes if ni > 0)
            self.computed_features["consecutive_profitable_years"] = consecutive_profitable
            
            # Detect volatile profits (alternating positive/negative)
            signs = [1 if ni > 0 else -1 for ni in net_incomes]
            volatile_profits = len(set(signs)) > 1 and len(signs) >= 3
            self.computed_features["volatile_profits"] = volatile_profits
        else:
            self.computed_features["consecutive_profitable_years"] = None
            self.computed_features["volatile_profits"] = None
            self.missing_flags["profitability_trend"] = True
    
    # ========================================================================
    # FEATURE COMPUTATION - CONTRACTUAL CAPACITY (Pillar 4)
    # ========================================================================
    
    def _compute_contractual_capacity_features(
        self,
        case: EvaluationCase,
        statement: Dict[str, Any],
        scorecard: Optional[Scorecard]
    ) -> None:
        """
        Compute contractual capacity features (MCC Pillar 4).
        
        Features:
        - contract_value
        - contract_to_revenue
        - total_exposure (contract + backlog)
        - exposure_level (LOW/MODERATE/HIGH/CRITICAL)
        - backlog_ratio
        """
        income_statement = statement.get("income_statement", {})
        operating_revenue = self._safe_get_nested(income_statement, ["OPERATING_REVENUE"])
        
        # Contract value directly from case
        contract_value = float(case.contract_value) if case.contract_value is not None else None
        
        self.computed_features["contract_value"] = contract_value
        
        # Contract to Revenue Ratio
        contract_to_revenue = self._safe_divide(contract_value, operating_revenue)
        self.computed_features["contract_to_revenue"] = self._cap_value(
            contract_to_revenue, "contract_to_revenue"
        )
        
        # Backlog (if available from scorecard or case metadata)
        # Note: This would need to be added to the data model if not present
        backlog_existing_contracts = 0.0  # Placeholder
        
        # Total Exposure
        if contract_value is not None:
            total_exposure_amount = contract_value + backlog_existing_contracts
            total_exposure = self._safe_divide(total_exposure_amount, operating_revenue)
            self.computed_features["total_exposure"] = total_exposure
            
            # Exposure Level Classification
            if total_exposure is not None:
                if total_exposure < 0.3:
                    exposure_level = "LOW"
                elif total_exposure < 0.5:
                    exposure_level = "MODERATE"
                elif total_exposure < 0.7:
                    exposure_level = "HIGH"
                else:
                    exposure_level = "CRITICAL"
                
                self.computed_features["exposure_level"] = exposure_level
            else:
                self.computed_features["exposure_level"] = None
        else:
            self.computed_features["total_exposure"] = None
            self.computed_features["exposure_level"] = None
            self.missing_flags["contract_value"] = True
        
        # Backlog Ratio
        backlog_ratio = self._safe_divide(backlog_existing_contracts, operating_revenue)
        self.computed_features["backlog_ratio"] = backlog_ratio
    
    # ========================================================================
    # FEATURE COMPUTATION - QUALITY & RELIABILITY (Pillar 5)
    # ========================================================================
    
    def _compute_quality_features(
        self,
        case: EvaluationCase,
        all_statements: List[Dict[str, Any]]
    ) -> None:
        """
        Compute quality and reliability features (MCC Pillar 5).
        
        Features:
        - audit_quality_score (0-5 scale)
        - years_with_audited_fs
        - no_audit (flag)
        - late_filing (flag)
        - documentation_completeness
        """
        # Remove audit_type logic as it does not exist on Bidder model. 
        # Defaulting to 0 for now until data model evolves.
        audit_quality_score = 0
        self.computed_features["audit_quality_score"] = audit_quality_score
        self.computed_features["no_audit"] = True
        
        # Years with audited financial statements
        years_with_audited_fs = len(all_statements)
        self.computed_features["years_with_audited_fs"] = years_with_audited_fs
        
        # Late filing flag (would need metadata)
        # Placeholder
        self.computed_features["late_filing"] = False
        
        # Documentation completeness (based on available statements)
        documentation_completeness = min(years_with_audited_fs / 3.0, 1.0)
        self.computed_features["documentation_completeness"] = round(documentation_completeness, 2)
        self.computed_features["data_completeness_score"] = round(documentation_completeness, 2)
    
    # ========================================================================
    # FEATURE COMPUTATION - TRENDS & DYNAMICS
    # ========================================================================
    
    def _compute_trend_features(
        self,
        all_statements: List[Dict[str, Any]],
        ratio_sets: List[RatioSet]
    ) -> None:
        """
        Compute trend and dynamic features (multi-year analysis).
        
        Features:
        - revenue_cagr_3y (Compound Annual Growth Rate)
        - revenue_volatility
        - liquidity_trend (improving/stable/declining)
        - debt_trend
        - margin_trend
        """
        if len(all_statements) < self.MIN_YEARS_FOR_TREND:
            logger.warning(
                f"Insufficient data for trend calculation. "
                f"Need {self.MIN_YEARS_FOR_TREND}, got {len(all_statements)}"
            )
            self.missing_flags["trend_features"] = True
            return
        
        # Extract revenue for last 3 years
        revenues = []
        for stmt in all_statements[:3]:
            rev = self._safe_get_nested(stmt.get("income_statement", {}), ["OPERATING_REVENUE"])
            if rev is not None:
                revenues.append(float(rev))
        
        if len(revenues) >= 2:
            # Revenue CAGR (3 years)
            if len(revenues) == 3 and revenues[-1] > 0:
                cagr = ((revenues[0] / revenues[-1]) ** (1/2)) - 1
                self.computed_features["revenue_cagr_3y"] = round(cagr, 4)
            else:
                self.computed_features["revenue_cagr_3y"] = None
                
            # Revenue Growth Rate (1 year)
            if revenues[1] > 0:
                self.computed_features["revenue_growth_rate"] = (revenues[0] - revenues[1]) / revenues[1]
            else:
                self.computed_features["revenue_growth_rate"] = None
            
            # Equity Growth Rate (1 year)
            eq_current = self._safe_get_nested(all_statements[0].get("balance_sheet", {}), ["EQUITY", "total"])
            eq_previous = self._safe_get_nested(all_statements[1].get("balance_sheet", {}), ["EQUITY", "total"])
            if eq_current is not None and eq_previous is not None and eq_previous > 0:
                self.computed_features["equity_growth_rate"] = (eq_current - eq_previous) / eq_previous
            else:
                self.computed_features["equity_growth_rate"] = None
            
            # Revenue Volatility (coefficient of variation)
            import statistics
            if len(revenues) >= 2:
                mean_rev = statistics.mean(revenues)
                std_rev = statistics.stdev(revenues)
                cv = std_rev / mean_rev if mean_rev > 0 else None
                self.computed_features["revenue_volatility"] = round(cv, 4) if cv else None
        
        # Liquidity Trend (based on current_ratio evolution)
        if len(ratio_sets) >= 2:
            current_ratios = [
                rs.current_ratio for rs in ratio_sets[:3]
                if rs.current_ratio is not None
            ]
            
            if len(current_ratios) >= 2:
                if current_ratios[0] > current_ratios[-1] * Decimal("1.1"):
                    liquidity_trend = "IMPROVING"
                elif current_ratios[0] < current_ratios[-1] * Decimal("0.9"):
                    liquidity_trend = "DECLINING"
                else:
                    liquidity_trend = "STABLE"
                
                self.computed_features["liquidity_trend"] = liquidity_trend
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def _safe_get_nested(
        self,
        data: Dict[str, Any],
        keys: List[str]
    ) -> Optional[float]:
        """
        Safely navigate nested dictionary structure.
        
        Args:
            data: Source dictionary (normalized JSON)
            keys: List of keys to traverse
            
        Returns:
            Value if found, None otherwise
        """
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
                if current is None:
                    return None
            else:
                return None
        
        # Convert to float if numeric
        if isinstance(current, (int, float, Decimal)):
            return float(current)
        
        return None
    
    def _safe_divide(
        self,
        numerator: Optional[float],
        denominator: Optional[float]
    ) -> Optional[float]:
        """
        Safe division with None handling.
        
        Returns None if either operand is None or denominator is zero.
        """
        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator
    
    def _safe_add(
        self,
        a: Optional[float],
        b: Optional[float]
    ) -> Optional[float]:
        """Safe addition with None handling."""
        if a is None and b is None:
            return None
        if a is None:
            return b
        if b is None:
            return a
        return a + b
    
    def _cap_value(
        self,
        value: Optional[float],
        feature_name: str
    ) -> Optional[float]:
        """
        Cap outlier values (winsorization).
        
        Args:
            value: Raw computed value
            feature_name: Name of the feature (to look up cap threshold)
            
        Returns:
            Capped value if above threshold, original value otherwise
        """
        if value is None:
            return None
        
        cap = self.CAPS.get(feature_name)
        if cap is not None and value > cap:
            self.capped_flags[feature_name] = True
            logger.debug(f"Capped {feature_name}: {value} -> {cap}")
            return cap
        
        return value
