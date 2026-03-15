"""
Unit Tests for Feature Engineering Engine

Tests:
- Feature computation from normalized financial statements
- Edge cases (missing data, zero values, negative values)
- Feature validation
- Multi-year trend analysis
- Error handling

Stack: pytest-asyncio, SQLAlchemy 2.0 async
Language: 100% English
"""

import pytest
import pytest_asyncio
from decimal import Decimal
from typing import Dict, Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    EvaluationCase,
    Bidder,
    FinancialStatementRaw,
    FinancialStatementNormalized
)
from app.engines.ia.feature_engineering import FeatureEngineeringEngine
from app.exceptions.finaces_exceptions import (
    InsufficientFiscalYearsError,
    MissingFinancialDataError
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest_asyncio.fixture
async def test_bidder(db_session: AsyncSession) -> Bidder:
    """Create test bidder."""
    bidder = Bidder(
        id=uuid4(),
        name="Test Construction Company",
        legal_form="SARL",
        country="Morocco",
        sector="Construction"
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
    """Create test evaluation case."""
    case = EvaluationCase(
        id=uuid4(),
        case_type="SINGLE",
        bidder_id=test_bidder.id,
        market_reference="TEST-001",
        contract_value=Decimal("5000000.00"),
        status="IN_ANALYSIS"
    )
    db_session.add(case)
    await db_session.commit()
    await db_session.refresh(case)
    return case


@pytest_asyncio.fixture
async def normalized_statements_multi_year(
    db_session: AsyncSession,
    test_case: EvaluationCase
) -> list:
    """Create normalized statements for 3 fiscal years."""
    
    statements = []
    
    for year in [2021, 2022, 2023]:
        # Create raw statement first
        raw_stmt = FinancialStatementRaw(
            id=uuid4(),
            case_id=test_case.id,
            fiscal_year=year,
            currency_original="USD",
            exchange_rate_to_usd=Decimal("1.0")
        )
        db_session.add(raw_stmt)
        await db_session.flush()
        
        # Create normalized statement
        norm_stmt = FinancialStatementNormalized(
            id=uuid4(),
            raw_statement_id=raw_stmt.id,
            fiscal_year=year,
            
            # Assets (growing 10% per year)
            total_assets=Decimal(5000000 * (1.1 ** (year - 2021))),
            current_assets=Decimal(2500000 * (1.1 ** (year - 2021))),
            liquid_assets=Decimal(1000000 * (1.1 ** (year - 2021))),
            inventory=Decimal(800000 * (1.1 ** (year - 2021))),
            accounts_receivable=Decimal(700000 * (1.1 ** (year - 2021))),
            non_current_assets=Decimal(2500000 * (1.1 ** (year - 2021))),
            
            # Liabilities & Equity
            total_liabilities_and_equity=Decimal(5000000 * (1.1 ** (year - 2021))),
            equity=Decimal(2000000 * (1.08 ** (year - 2021))),
            current_liabilities=Decimal(1500000 * (1.05 ** (year - 2021))),
            short_term_debt=Decimal(500000 * (1.05 ** (year - 2021))),
            accounts_payable=Decimal(600000 * (1.05 ** (year - 2021))),
            non_current_liabilities=Decimal(1500000 * (1.05 ** (year - 2021))),
            long_term_debt=Decimal(1200000 * (1.05 ** (year - 2021))),
            
            # Income Statement
            revenue=Decimal(10000000 * (1.1 ** (year - 2021))),
            operating_income=Decimal(800000 * (1.1 ** (year - 2021))),
            net_income=Decimal(500000 * (1.1 ** (year - 2021))),
            ebitda=Decimal(1000000 * (1.1 ** (year - 2021))),
            cost_of_goods_sold=Decimal(6000000 * (1.1 ** (year - 2021))),
            financial_expenses=Decimal(100000),
            depreciation_and_amortization=Decimal(200000),
            
            # Cash Flows
            operating_cash_flow=Decimal(700000 * (1.1 ** (year - 2021))),
            
            # Other
            headcount=50,
            is_consolidated=0
        )
        db_session.add(norm_stmt)
        statements.append(norm_stmt)
    
    await db_session.commit()
    
    for stmt in statements:
        await db_session.refresh(stmt)
    
    return statements


# ============================================================================
# TESTS - FEATURE COMPUTATION
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.ia
class TestFeatureComputation:
    """Test feature computation logic."""
    
    async def test_compute_liquidity_ratios(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        normalized_statements_multi_year: list
    ):
        """Test liquidity ratios computation."""
        
        engine = FeatureEngineeringEngine()
        features = await engine.compute_all_features(str(test_case.id), db_session)
        
        # Verify liquidity features exist
        assert "current_ratio" in features["features"]
        assert "quick_ratio" in features["features"]
        assert "cash_ratio" in features["features"]
        assert "working_capital" in features["features"]
        
        # Verify values are reasonable
        current_ratio = features["features"]["current_ratio"]
        assert 0 < current_ratio < 10, f"Current ratio out of range: {current_ratio}"
        
        quick_ratio = features["features"]["quick_ratio"]
        assert 0 < quick_ratio < current_ratio, "Quick ratio should be < current ratio"
    
    async def test_compute_solvency_ratios(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        normalized_statements_multi_year: list
    ):
        """Test solvency ratios computation."""
        
        engine = FeatureEngineeringEngine()
        features = await engine.compute_all_features(str(test_case.id), db_session)
        
        # Verify solvency features
        assert "debt_to_equity" in features["features"]
        assert "financial_autonomy" in features["features"]
        assert "gearing" in features["features"]
        
        # Financial autonomy should be between 0 and 1
        autonomy = features["features"]["financial_autonomy"]
        assert 0 <= autonomy <= 1, f"Financial autonomy out of range: {autonomy}"
    
    async def test_compute_profitability_ratios(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        normalized_statements_multi_year: list
    ):
        """Test profitability ratios computation."""
        
        engine = FeatureEngineeringEngine()
        features = await engine.compute_all_features(str(test_case.id), db_session)
        
        # Verify profitability features
        assert "net_margin" in features["features"]
        assert "ebitda_margin" in features["features"]
        assert "roa" in features["features"]
        assert "roe" in features["features"]
        
        # Margins should be percentages
        net_margin = features["features"]["net_margin"]
        assert -100 < net_margin < 100, f"Net margin out of range: {net_margin}"
    
    async def test_compute_trend_features(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        normalized_statements_multi_year: list
    ):
        """Test multi-year trend analysis."""
        
        engine = FeatureEngineeringEngine()
        features = await engine.compute_all_features(str(test_case.id), db_session)
        
        # Verify trend features exist
        assert "revenue_growth_rate" in features["features"]
        assert "equity_growth_rate" in features["features"]
        
        # Revenue growing at 10% per year
        revenue_growth = features["features"]["revenue_growth_rate"]
        assert 0.08 < revenue_growth < 0.12, f"Revenue growth unexpected: {revenue_growth}"
        
        # Equity growing at 8% per year
        equity_growth = features["features"]["equity_growth_rate"]
        assert 0.06 < equity_growth < 0.10, f"Equity growth unexpected: {equity_growth}"
    
    async def test_feature_count(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        normalized_statements_multi_year: list
    ):
        """Test that all 40+ features are computed."""
        
        engine = FeatureEngineeringEngine()
        features = await engine.compute_all_features(str(test_case.id), db_session)
        
        feature_count = features["metadata"]["feature_count"]
        assert feature_count >= 40, f"Expected 40+ features, got {feature_count}"


# ============================================================================
# TESTS - EDGE CASES
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.ia
class TestEdgeCases:
    """Test edge cases and error handling."""
    
    async def test_insufficient_fiscal_years(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase
    ):
        """Test error when less than 2 fiscal years available."""
        
        # Create only 1 year of data
        raw_stmt = FinancialStatementRaw(
            id=uuid4(),
            case_id=test_case.id,
            fiscal_year=2023,
            currency_original="USD"
        )
        db_session.add(raw_stmt)
        await db_session.flush()
        
        norm_stmt = FinancialStatementNormalized(
            id=uuid4(),
            raw_statement_id=raw_stmt.id,
            fiscal_year=2023,
            total_assets=Decimal("5000000"),
            revenue=Decimal("10000000")
        )
        db_session.add(norm_stmt)
        await db_session.commit()
        
        engine = FeatureEngineeringEngine()
        
        with pytest.raises(InsufficientFiscalYearsError) as exc_info:
            await engine.compute_all_features(str(test_case.id), db_session)
        
        assert "at least 2 fiscal years" in str(exc_info.value).lower()
    
    async def test_missing_critical_fields(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase
    ):
        """Test handling of missing critical financial fields."""
        
        # Create statements with missing critical data
        for year in [2022, 2023]:
            raw_stmt = FinancialStatementRaw(
                id=uuid4(),
                case_id=test_case.id,
                fiscal_year=year
            )
            db_session.add(raw_stmt)
            await db_session.flush()
            
            norm_stmt = FinancialStatementNormalized(
                id=uuid4(),
                raw_statement_id=raw_stmt.id,
                fiscal_year=year,
                # Missing critical fields (None)
                total_assets=None,
                revenue=None,
                equity=None
            )
            db_session.add(norm_stmt)
        
        await db_session.commit()
        
        engine = FeatureEngineeringEngine()
        
        with pytest.raises(MissingFinancialDataError) as exc_info:
            await engine.compute_all_features(str(test_case.id), db_session)
        
        assert "missing" in str(exc_info.value).lower()
    
    async def test_zero_denominators(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase
    ):
        """Test handling of zero values in denominators."""
        
        # Create statements with zero liabilities (edge case)
        for year in [2022, 2023]:
            raw_stmt = FinancialStatementRaw(
                id=uuid4(),
                case_id=test_case.id,
                fiscal_year=year
            )
            db_session.add(raw_stmt)
            await db_session.flush()
            
            norm_stmt = FinancialStatementNormalized(
                id=uuid4(),
                raw_statement_id=raw_stmt.id,
                fiscal_year=year,
                total_assets=Decimal("5000000"),
                current_assets=Decimal("2500000"),
                current_liabilities=Decimal("0"),  # Zero denominator
                equity=Decimal("5000000"),
                revenue=Decimal("10000000"),
                net_income=Decimal("500000")
            )
            db_session.add(norm_stmt)
        
        await db_session.commit()
        
        engine = FeatureEngineeringEngine()
        
        # Should not crash, should handle gracefully
        features = await engine.compute_all_features(str(test_case.id), db_session)
        
        # Current ratio should be None or infinity indicator
        current_ratio = features["features"].get("current_ratio")
        assert current_ratio is None or current_ratio > 999, "Should handle zero denominator"
    
    async def test_negative_equity(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase
    ):
        """Test handling of negative equity (insolvency indicator)."""
        
        for year in [2022, 2023]:
            raw_stmt = FinancialStatementRaw(
                id=uuid4(),
                case_id=test_case.id,
                fiscal_year=year
            )
            db_session.add(raw_stmt)
            await db_session.flush()
            
            norm_stmt = FinancialStatementNormalized(
                id=uuid4(),
                raw_statement_id=raw_stmt.id,
                fiscal_year=year,
                total_assets=Decimal("5000000"),
                equity=Decimal("-500000"),  # Negative equity
                current_liabilities=Decimal("3000000"),
                non_current_liabilities=Decimal("2500000"),
                revenue=Decimal("10000000")
            )
            db_session.add(norm_stmt)
        
        await db_session.commit()
        
        engine = FeatureEngineeringEngine()
        features = await engine.compute_all_features(str(test_case.id), db_session)
        
        # Should set negative_equity_flag
        negative_equity_flag = features["features"]["negative_equity_flag"]
        assert negative_equity_flag == 1, "Should detect negative equity"


# ============================================================================
# TESTS - FEATURE VALIDATION
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.ia
class TestFeatureValidation:
    """Test feature validation and quality checks."""
    
    async def test_feature_metadata(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        normalized_statements_multi_year: list
    ):
        """Test metadata generation."""
        
        engine = FeatureEngineeringEngine()
        features = await engine.compute_all_features(str(test_case.id), db_session)
        
        # Verify metadata structure
        assert "metadata" in features
        assert "case_id" in features["metadata"]
        assert "computed_at" in features["metadata"]
        assert "feature_count" in features["metadata"]
        assert "fiscal_years_used" in features["metadata"]
        
        # Verify fiscal years
        fiscal_years = features["metadata"]["fiscal_years_used"]
        assert len(fiscal_years) == 3
        assert 2021 in fiscal_years
        assert 2023 in fiscal_years
    
    async def test_feature_completeness_score(
        self,
        db_session: AsyncSession,
        test_case: EvaluationCase,
        normalized_statements_multi_year: list
    ):
        """Test data completeness scoring."""
        
        engine = FeatureEngineeringEngine()
        features = await engine.compute_all_features(str(test_case.id), db_session)
        
        completeness = features["features"]["data_completeness_score"]
        
        # With complete data, should be close to 1.0
        assert 0.9 <= completeness <= 1.0, f"Expected high completeness, got {completeness}"
