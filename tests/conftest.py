"""
FinaCES API - Pytest Configuration & Shared Fixtures

Critical fixtures for async testing:
- Database session management (async)
- FastAPI test client (httpx.AsyncClient)
- Test data factories
- Mock dependencies

Stack: pytest-asyncio, httpx, factory-boy, faker
Language: 100% English
"""

import os
import sys
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Generator, Dict, Any
import logging

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker
)
from sqlalchemy.pool import NullPool
from httpx import AsyncClient, ASGITransport
from faker import Faker
from unittest.mock import AsyncMock, patch

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.main import app
from app.db.database import Base, get_db
from app.core.security import get_current_user
from app.core.config import settings

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress noisy logs during tests
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

# Set event loop scope for async tests

# asyncio_default_fixture_loop_scope=session in pytest.ini manages the rest.

# ============================================================================
# DATABASE FIXTURES (ASYNC)
# ============================================================================

@pytest.fixture(scope="session")
def test_database_url() -> str:
    """
    Test database URL.
    
    Uses environment variable or default test database.
    CRITICAL: Must be different from production database!
    """
    db_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://finaces:password@localhost:5433/finaces_test"
    )
    
    # Safety check: ensure we're not using production database
    if "finaces_test" not in db_url and "test" not in db_url:
        raise ValueError(
            "Test database URL must contain 'test' or 'finaces_test'. "
            f"Got: {db_url}"
        )
    
    logger.info(f"Using test database: {db_url}")
    return db_url


@pytest_asyncio.fixture(scope="session")
async def test_engine(test_database_url: str):
    """
    Create test database engine.
    
    Uses NullPool to prevent connection issues in tests.
    Scope: session (created once, reused for all tests)
    """
    engine = create_async_engine(
        test_database_url,
        echo=False,
        poolclass=NullPool,  # No connection pooling for tests
        future=True
    )
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("✓ Test database tables created")
    
    yield engine
    
    # Cleanup: drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()
    logger.info("✓ Test database cleaned up")


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Create async database session for each test.
    
    Scope: function (new session per test)
    Automatically rolls back transactions after each test.
    """
    # Create session factory
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session
        await session.rollback()


# ============================================================================
# FASTAPI TEST CLIENT (ASYNC)
# ============================================================================

@pytest_asyncio.fixture(autouse=True, scope="session")
async def mock_fastapi_limiter():
    """Mock FastAPILimiter.init (Redis) + désactive RateLimiter.__call__ en test."""
    from fastapi import Request, Response
    async def _mock_limiter(request: Request, response: Response):
        pass

    with patch("fastapi_limiter.FastAPILimiter.init", new_callable=AsyncMock):
        with patch("fastapi_limiter.depends.RateLimiter.__call__", _mock_limiter):
            yield


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Create async HTTP test client.
    
    Overrides database dependency to use the SAME test session so
    fixture-inserted data is visible to the ASGI handlers.
    The base_url is http://test — no XSRF cookie is set here (unauthenticated
    client for testing 403 scenarios).
    """
    
    # Override database dependency - share session for data visibility
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    
    # Clean up overrides
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_client(
    client: AsyncClient,
    test_user: Dict[str, Any]
) -> AsyncClient:
    """
    Authenticated HTTP client with test user.

    - Overrides get_current_user to return test_user (no real JWT).
    - Injects a XSRF-TOKEN cookie and the matching X-XSRF-TOKEN header
      so the XSRFMiddleware passes on all POST/PUT/PATCH/DELETE requests.
      The token value is a fixed test string — predictable is fine in tests,
      secrets.compare_digest just checks equality.
    """
    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Inject XSRF cookie + header for mutation requests
    _XSRF_TEST_TOKEN = "test-xsrf-token-finaces-12345"
    client.cookies.set("XSRF-TOKEN", _XSRF_TEST_TOKEN)
    client.headers.update({"X-XSRF-TOKEN": _XSRF_TEST_TOKEN})

    yield client

    app.dependency_overrides.clear()
    # Reset cookies and headers after test
    client.cookies.clear()
    if "X-XSRF-TOKEN" in client.headers:
        del client.headers["X-XSRF-TOKEN"]


# ============================================================================
# TEST DATA FIXTURES
# ============================================================================

@pytest.fixture
def faker_instance() -> Faker:
    """Faker instance for generating test data."""
    return Faker()


@pytest.fixture
def test_user() -> Dict[str, Any]:
    """
    Mock authenticated user.
    
    Mimics the structure returned by get_current_user dependency.
    """
    return {
        "id": "test-user-id-12345",
        "email": "test.analyst@finaces.test",
        "role": "ANALYST",
        "firstname": "Test",
        "lastname": "Analyst",
        "is_active": True
    }


@pytest.fixture
def sample_financial_data() -> Dict[str, Any]:
    """
    Sample financial statement data for testing.
    
    Mimics structure of FinancialStatementNormalized model.
    """
    return {
        "fiscal_year": 2023,
        "currency_usd": "USD",
        "exchange_rate": 1.0,
        
        # Assets
        "total_assets": 5000000.0,
        "current_assets": 2500000.0,
        "liquid_assets": 1000000.0,
        "inventory": 800000.0,
        "accounts_receivable": 700000.0,
        "noncurrent_assets": 2500000.0,
        "tangible_assets": 2000000.0,
        
        # Liabilities & Equity
        "total_liabilities_and_equity": 5000000.0,
        "equity": 2000000.0,
        "current_liabilities": 1500000.0,
        "short_term_debt": 500000.0,
        "accounts_payable": 600000.0,
        "noncurrent_liabilities": 1500000.0,
        "long_term_debt": 1200000.0,
        
        # Income Statement
        "revenue": 10000000.0,
        "operating_income": 800000.0,
        "net_income": 500000.0,
        "ebitda": 1000000.0,
        "cost_of_goods_sold": 6000000.0,
        "financial_expenses": 100000.0,
        "depreciation_and_amortization": 200000.0,
        
        # Cash Flows
        "operating_cash_flow": 700000.0,
        "investing_cash_flow": -300000.0,
        "financing_cash_flow": -200000.0,
        
        # Other
        "headcount": 50,
        "is_consolidated": 0
    }


@pytest.fixture
def sample_case_data(faker_instance: Faker) -> Dict[str, Any]:
    """Sample evaluation case data."""
    return {
        "case_type": "SINGLE",
        "market_reference": faker_instance.bothify(text="MKT-####-????"),
        "market_object": "Construction of office building",
        "contract_value": 5000000.0,
        "contract_currency": "USD",
        "contract_duration_months": 24,
        "status": "DRAFT"
    }


@pytest.fixture
def sample_ia_features() -> Dict[str, Any]:
    """
    Sample AI features for testing predictor.
    
    Contains 40+ features matching feature_engineering output.
    """
    return {
        # Liquidity
        "current_ratio": 1.67,
        "quick_ratio": 1.13,
        "cash_ratio": 0.67,
        "working_capital": 1000000.0,
        "working_capital_pct_assets": 0.20,
        "cash_to_assets": 0.20,
        "inventory_to_current_assets": 0.32,
        "receivables_to_current_assets": 0.28,
        "liquid_assets_coverage": 0.67,
        "defensive_interval_days": 60.0,
        
        # Solvency
        "debt_to_equity": 1.50,
        "financial_autonomy": 0.40,
        "gearing": 0.85,
        "long_term_debt_ratio": 0.24,
        "current_debt_ratio": 0.10,
        "equity_ratio": 0.40,
        "debt_service_coverage": 8.0,
        "liabilities_to_assets": 0.60,
        "equity_multiplier": 2.50,
        "capitalization_ratio": 0.375,
        
        # Profitability
        "net_margin": 5.0,
        "ebitda_margin": 10.0,
        "operating_margin": 8.0,
        "roa": 10.0,
        "roe": 25.0,
        "roic": 18.0,
        "gross_profit_margin": 40.0,
        "return_on_sales": 8.0,
        
        # Capacity
        "cashflow_capacity": 700000.0,
        "cashflow_margin_pct": 7.0,
        "debt_repayment_years": 2.43,
        "interest_coverage": 8.0,
        "cash_debt_coverage": 0.41,
        "working_capital_requirement_pct": 5.0,
        
        # Quality
        "negative_equity_flag": 0,
        "negative_cashflow_flag": 0,
        "z_score_altman": 3.5,
        "balance_sheet_balance_check": 0.0,
        "audit_quality_score": 0.8,
        "data_completeness_score": 0.95,
        
        # Trends (requires 2+ years, can be null for single year)
        "revenue_growth_rate": 0.10,
        "equity_growth_rate": 0.08,
        "debt_growth_rate": 0.05,
        "profitability_trend": 0.02,
        "liquidity_trend": 0.01,
        "cashflow_trend": 0.03
    }


@pytest.fixture
def sample_mcc_scorecard() -> Dict[str, Any]:
    """Sample MCC scorecard for tension detection tests."""
    return {
        "global_score": 3.5,
        "final_risk_class": "MODERATE",
        "pillar_scores": {
            "liquidity": 4.0,
            "solvency": 3.5,
            "profitability": 3.0,
            "capacity": 3.5,
            "quality": 4.0
        },
        "overrides_applied": [],
        "policy_version_id": "test-policy-v1"
    }


# ============================================================================
# AI MODULE FIXTURES
# ============================================================================

@pytest.fixture
def mock_trained_model(tmp_path: Path):
    """
    Mock trained ML model saved to temporary path.
    
    Creates a simple XGBoost model for testing without real training.
    """
    import xgboost as xgb
    from sklearn.datasets import make_classification
    
    # Create minimal training data
    X, y = make_classification(n_samples=100, n_features=46, random_state=42)
    
    # Train simple model
    model = xgb.XGBClassifier(n_estimators=10, max_depth=3, random_state=42)
    model.fit(X, y)
    
    # Create simple scaler
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    scaler = StandardScaler()
    scaler.fit(np.zeros((1, 46)))
    
    # Create artifact dict
    artifact = {
        "model": model,
        "scaler": scaler,
        "feature_names": [f"f{i}" for i in range(46)],
        "model_type": "xgboost",
        "version": "test_v1.0",
        "trained_at": "2024-03-11T12:00:00Z"
    }
    
    # Save to temp path
    model_path = tmp_path / "test_model.joblib"
    import joblib
    joblib.dump(artifact, model_path)
    
    return model_path


@pytest.fixture
def feature_engineering_config() -> Dict[str, Any]:
    """Feature engineering configuration for tests."""
    return {
        "version": "1.0.0",
        "feature_groups": {
            "liquidity": ["current_ratio", "quick_ratio", "cash_ratio"],
            "solvency": ["debt_to_equity", "financial_autonomy", "gearing"],
            "profitability": ["net_margin", "roa", "roe"],
            "capacity": ["cashflow_capacity", "debt_repayment_years"],
            "quality": ["negative_equity_flag", "z_score_altman"]
        },
        "missing_value_strategy": {
            "numeric_features": "median",
            "categorical_features": "mode"
        },
        "outlier_detection": {
            "enabled": True,
            "method": "iqr",
            "iqr_multiplier": 3.0
        }
    }


# ============================================================================
# CLEANUP UTILITIES
# ============================================================================

@pytest.fixture(autouse=True)
def cleanup_test_artifacts():
    """
    Auto-cleanup fixture that runs after each test.
    
    Removes temporary files, resets state, etc.
    """
    yield
    
    # Cleanup actions after test
    # (e.g., remove temporary files, reset global state)
    pass


# ============================================================================
# PYTEST HOOKS
# ============================================================================

def pytest_configure(config):
    """Pytest configuration hook."""
    # Create logs directory
    log_dir = Path("tests/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Pytest configuration complete")


def pytest_collection_modifyitems(config, items):
    """
    Modify test collection.
    
    Automatically adds markers based on test path.
    """
    for item in items:
        # Add markers based on path
        if "test_api" in str(item.fspath):
            item.add_marker(pytest.mark.api)
        
        if "test_engine" in str(item.fspath) or "engines" in str(item.fspath):
            item.add_marker(pytest.mark.engine)
        
        if "/ia/" in str(item.fspath):
            item.add_marker(pytest.mark.ia)
        
        # Mark tests requiring database
        if "db_session" in item.fixturenames:
            item.add_marker(pytest.mark.requires_db)
        
        # asyncio_mode=auto in pytest.ini marks async tests automatically
        # No manual pytest.mark.asyncio needed


def pytest_sessionfinish(session, exitstatus):
    """Hook called after test session finishes."""
    logger.info(f"Test session finished with status: {exitstatus}")
