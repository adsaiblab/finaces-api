import pytest
from app.services.report_builders import _fmt_amount, _build_section_01

def test_fmt_amount():
    """Test the currency formatting utility."""
    assert _fmt_amount(1234.56) == "1,235"
    assert _fmt_amount(None) == "N/A"
    assert _fmt_amount("invalid") == "N/A"

def test_build_section_01():
    """Test the generation of the Executive Info section."""
    case_mock = {
        "bidder_name": "ACME Corp",
        "market_reference": "RFP-2026-01",
        "contract_value": 1000000,
        "contract_currency": "USD"
    }
    result = _build_section_01(case_mock)
    
    assert "ACME Corp" in result
    assert "RFP-2026-01" in result
    assert "1,000,000" in result
    assert "USD" in result
