import pytest
from httpx import AsyncClient
import uuid

# Magic bytes
PDF_MAGIC = b"%PDF-1.4\n"
ZIP_MAGIC = b"PK\x03\x04"
INVALID_MAGIC = b"NOTAMAGICSIGNATURE"

pytestmark = pytest.mark.asyncio

import pytest_asyncio

@pytest_asyncio.fixture
async def mock_case_id(db_session, sample_case_data):
    from app.db.models import EvaluationCase
    import uuid
    case_data = {**sample_case_data, "id": uuid.uuid4()}
    case_model = EvaluationCase(**case_data)
    db_session.add(case_model)
    await db_session.commit()
    return str(case_model.id)

async def test_upload_valid_document(authenticated_client: AsyncClient, mock_case_id: str):
    # Case 1: Valid document
    file_content = PDF_MAGIC + b"fake pdf content"
    files = {"file": ("test.pdf", file_content, "application/pdf")}
    data = {
        "doc_type": "FINANCIAL_STATEMENTS",
        "fiscal_year": 2023,
        "auditor_name": "Test Auditor"
    }

    response = await authenticated_client.post(
        f"/api/v1/cases/{mock_case_id}/documents",
        data=data,
        files=files
    )
    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "test.pdf"

async def test_upload_invalid_doc_type(authenticated_client: AsyncClient, mock_case_id: str):
    # Case 2: Invalid doc_type
    file_content = PDF_MAGIC + b"fake pdf content"
    files = {"file": ("test.pdf", file_content, "application/pdf")}
    data = {
        "doc_type": "INVALID_TYPE",
        "fiscal_year": 2023,
        "auditor_name": "Test Auditor"
    }

    response = await authenticated_client.post(
        f"/api/v1/cases/{mock_case_id}/documents",
        data=data,
        files=files
    )
    assert response.status_code == 422

async def test_upload_invalid_extension(authenticated_client: AsyncClient, mock_case_id: str):
    # Case 3: Invalid extension
    file_content = b"random content"
    files = {"file": ("test.exe", file_content, "application/octet-stream")}
    data = {
        "doc_type": "FINANCIAL_STATEMENTS",
        "fiscal_year": 2023,
        "auditor_name": "Test Auditor"
    }

    response = await authenticated_client.post(
        f"/api/v1/cases/{mock_case_id}/documents",
        data=data,
        files=files
    )
    assert response.status_code == 415
    assert "not allowed" in response.json()["detail"]

async def test_upload_file_too_large(authenticated_client: AsyncClient, mock_case_id: str):
    # Case 4: File too large
    # 20MB limit. Let's send 21MB. But to avoid memory issues in tests, 
    # we can mock the size or read, but for simplicity we can just send it.
    # Actually, generating 21MB in memory is fine for a single test.
    file_content = b"x" * (21 * 1024 * 1024)
    files = {"file": ("large_file.csv", file_content, "text/csv")}
    data = {
        "doc_type": "FINANCIAL_STATEMENTS",
        "fiscal_year": 2023,
        "auditor_name": "Test Auditor"
    }

    response = await authenticated_client.post(
        f"/api/v1/cases/{mock_case_id}/documents",
        data=data,
        files=files
    )
    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"]

async def test_upload_magic_bytes_mismatch(authenticated_client: AsyncClient, mock_case_id: str):
    # Case 5: Magic bytes mismatch
    file_content = INVALID_MAGIC + b"fake pdf content"
    files = {"file": ("test.pdf", file_content, "application/pdf")}
    data = {
        "doc_type": "FINANCIAL_STATEMENTS",
        "fiscal_year": 2023,
        "auditor_name": "Test Auditor"
    }

    response = await authenticated_client.post(
        f"/api/v1/cases/{mock_case_id}/documents",
        data=data,
        files=files
    )
    assert response.status_code == 415
    assert "Unsupported file content" in response.json()["detail"]

async def test_upload_empty_file(authenticated_client: AsyncClient, mock_case_id: str):
    # Case 6: Empty file
    files = {"file": ("test.pdf", b"", "application/pdf")}
    data = {
        "doc_type": "FINANCIAL_STATEMENTS",
        "fiscal_year": 2023,
        "auditor_name": "Test Auditor"
    }

    response = await authenticated_client.post(
        f"/api/v1/cases/{mock_case_id}/documents",
        data=data,
        files=files
    )
    assert response.status_code == 400

async def test_upload_unauthorized(client: AsyncClient, mock_case_id: str):
    # Case 7: Unauthorized (no jwt override)
    _XSRF_TEST_TOKEN = "test-xsrf-token-finaces-12345"
    client.cookies.set("XSRF-TOKEN", _XSRF_TEST_TOKEN)
    client.headers.update({"X-XSRF-TOKEN": _XSRF_TEST_TOKEN})

    file_content = PDF_MAGIC + b"fake pdf content"
    files = {"file": ("test.pdf", file_content, "application/pdf")}
    data = {
        "doc_type": "FINANCIAL_STATEMENTS",
        "fiscal_year": 2023,
        "auditor_name": "Test Auditor"
    }

    response = await client.post(
        f"/api/v1/cases/{mock_case_id}/documents",
        data=data,
        files=files
    )
    # The application returns 401 for missing JWT
    assert response.status_code == 401

async def test_upload_missing_xsrf(client: AsyncClient, mock_case_id: str, test_user):
    # Case 8: Missing XSRF.
    # We use `client` (which does not inject XSRF tokens), but we manually override `get_current_user`
    from app.main import app
    from app.core.security import get_current_user
    
    async def override_get_current_user():
        return test_user
        
    app.dependency_overrides[get_current_user] = override_get_current_user
    
    file_content = PDF_MAGIC + b"fake pdf content"
    files = {"file": ("test.pdf", file_content, "application/pdf")}
    data = {
        "doc_type": "FINANCIAL_STATEMENTS",
        "fiscal_year": 2023,
        "auditor_name": "Test Auditor"
    }

    # Notice: we don't send the X-XSRF-TOKEN header or XSRF-TOKEN cookie!
    response = await client.post(
        f"/api/v1/cases/{mock_case_id}/documents",
        data=data,
        files=files
    )
    
    # Clean up override
    app.dependency_overrides.clear()
    
    # Must be blocked by XSRFMiddleware BEFORE even reaching route validators
    assert response.status_code == 403
    assert "XSRF" in response.json()["detail"]
