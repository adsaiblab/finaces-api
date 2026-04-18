"""
tests/test_workflow_guards.py
Tests unitaires pour les guards de workflow FinaCES (Gate Guard).
Focus: 403 Forbidden si le Gate n'est pas validé.
Utilise authenticated_client pour contourner XSRF.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import status

from app.main import app
from app.db.database import get_db

# Case ID constant pour les tests
CASE_ID = uuid.uuid4()

@pytest.fixture
def mock_db():
    return AsyncMock()

class MockGateResult:
    def __init__(self, is_passed: bool):
        self.is_passed = is_passed

@pytest.mark.asyncio
async def test_financials_no_gate_403(authenticated_client, mock_db):
    """POST /financials sans GateResult -> 403"""
    # Mock DB : pas de gate result (select avec is_passed=True ne renvoie rien)
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = await authenticated_client.post(f"/api/v1/cases/{CASE_ID}/financials", json={
        "fiscal_year": 2023,
        "currency_original": "USD",
        "exchange_rate_to_usd": 1.0,
        "referentiel": "IFRS",
        "balance_sheet_assets": {"liquid_assets": 100},
        "balance_sheet_liabilities": {"long_term_debt": 50},
        "income_statement": {"revenue": 200},
        "cash_flow": {"operating_cash_flow": 30}
    })
    
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Gate validation required" in response.json()["detail"]
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_financials_gate_failed_403(authenticated_client, mock_db):
    """POST /financials avec Gate is_passed=False -> 403"""
    # Mock DB : pas de gate result car assert_gate_passed cherche is_passed=True
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = await authenticated_client.post(f"/api/v1/cases/{CASE_ID}/financials", json={
        "fiscal_year": 2023,
        "currency_original": "USD",
        "exchange_rate_to_usd": 1.0,
        "referentiel": "IFRS",
        "balance_sheet_assets": {"liquid_assets": 100},
        "balance_sheet_liabilities": {"long_term_debt": 50},
        "income_statement": {"revenue": 200},
        "cash_flow": {"operating_cash_flow": 30}
    })
    
    assert response.status_code == status.HTTP_403_FORBIDDEN
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_financials_gate_passed_success(authenticated_client, mock_db):
    """POST /financials avec Gate is_passed=True -> Success"""
    # Mock DB : gate result existe et is_passed=True
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: MockGateResult(is_passed=True))
    
    # On mock aussi l'upsert pour éviter de toucher à la vraie DB
    with patch("app.services.financial_service.upsert_financial_statement", return_value=(uuid.uuid4(), "FINANCIAL_CREATED")):
        with patch("app.services.audit_service.log_event", return_value=None):
            app.dependency_overrides[get_db] = lambda: mock_db
            
            response = await authenticated_client.post(f"/api/v1/cases/{CASE_ID}/financials", json={
                "fiscal_year": 2023,
                "currency_original": "USD",
                "exchange_rate_to_usd": 1.0,
                "referentiel": "IFRS",
                "balance_sheet_assets": {"liquid_assets": 100},
                "balance_sheet_liabilities": {"long_term_debt": 50},
                "income_statement": {"revenue": 200},
                "cash_flow": {"operating_cash_flow": 30}
            })
            
            assert response.status_code == 200
    app.dependency_overrides.clear()

# ── Normalization tests ─────────────────────────────────────

@pytest.mark.asyncio
async def test_normalize_no_gate_403(authenticated_client, mock_db):
    """POST /normalize sans GateResult -> 403"""
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    app.dependency_overrides[get_db] = lambda: mock_db
    response = await authenticated_client.post(f"/api/v1/cases/{CASE_ID}/normalize")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_normalize_gate_failed_403(authenticated_client, mock_db):
    """POST /normalize avec Gate is_passed=False -> 403"""
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    app.dependency_overrides[get_db] = lambda: mock_db
    response = await authenticated_client.post(f"/api/v1/cases/{CASE_ID}/normalize")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_normalize_gate_passed_success(authenticated_client, mock_db):
    """POST /normalize avec Gate is_passed=True -> Success"""
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: MockGateResult(is_passed=True))
    with patch("app.api.routes.normalization.process_normalization", return_value=[]):
        app.dependency_overrides[get_db] = lambda: mock_db
        response = await authenticated_client.post(f"/api/v1/cases/{CASE_ID}/normalize")
        assert response.status_code == 200
    app.dependency_overrides.clear()

# ── Ratios tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_ratios_no_gate_403(authenticated_client, mock_db):
    """POST /ratios/compute sans GateResult -> 403"""
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    app.dependency_overrides[get_db] = lambda: mock_db
    response = await authenticated_client.post(f"/api/v1/cases/{CASE_ID}/ratios/compute")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_ratios_gate_failed_403(authenticated_client, mock_db):
    """POST /ratios/compute avec Gate is_passed=False -> 403"""
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    app.dependency_overrides[get_db] = lambda: mock_db
    response = await authenticated_client.post(f"/api/v1/cases/{CASE_ID}/ratios/compute")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_ratios_gate_passed_success(authenticated_client, mock_db):
    """POST /ratios/compute avec Gate is_passed=True -> Success"""
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: MockGateResult(is_passed=True))
    with patch("app.api.routes.ratios.assert_case_status", return_value=None):
        with patch("app.api.routes.ratios.process_ratios", return_value=[]):
            app.dependency_overrides[get_db] = lambda: mock_db
            response = await authenticated_client.post(f"/api/v1/cases/{CASE_ID}/ratios/compute")
            assert response.status_code == 200
    app.dependency_overrides.clear()
