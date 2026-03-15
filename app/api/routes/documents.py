"""
app/api/routes/documents.py — Document management
Sprint 2B: GAP-06 — Upload, listing and status management of evidence.
"""

import logging
from typing import Optional, List

from app.core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.document_service import (
    save_document,
    get_documents_for_case,
    verify_document_integrity,
    mark_document_status,
    DOC_TYPE_LABELS,
    RELIABILITY_LABELS,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cases",
    tags=["Documents"],
)


# ─────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────

class DocumentStatusUpdate(BaseModel):
    status: str     # PRESENT | MISSING | INCOMPLETE | REJECTED


class DocumentOut(BaseModel):
    id: str
    doc_type: str
    doc_type_label: Optional[str] = None
    fiscal_year: Optional[int] = None
    filename: Optional[str] = None
    file_size_kb: Optional[float] = None
    mime_type: Optional[str] = None
    file_hash: Optional[str] = None
    status: str
    reliability_level: Optional[str] = None
    reliability_label: Optional[str] = None
    red_flags: Optional[list] = None
    auditor_name: Optional[str] = None
    notes: Optional[str] = None
    uploaded_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.post("/{case_id}/documents")
async def api_upload_document(
    case_id:           str,
    file:              UploadFile = File(..., description="File to upload"),
    doc_type:          str        = Form(..., description="Document type (e.g., FINANCIAL_STATEMENTS)"),
    description:       Optional[str]  = Form(default=None),
    fiscal_year:       Optional[int]  = Form(default=None),
    reliability_level: str            = Form(default="MEDIUM"),
    auditor_name:      Optional[str]  = Form(default=None),
    notes:             Optional[str]  = Form(default=None),
    db:                AsyncSession   = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """
    Upload a proof document and associate it with a file.

    - Calculates the SHA-256 hash of the upload (cryptographic traceability)
    - Write the file to `uploads/{case_id}/`
    - Creates a `DocumentEvidence` record in base
    - Emits a DOCUMENT_ADDED event in the audit trail

    **doc_type** accepts: FINANCIAL_STATEMENTS | AUDITOR_OPINION | APPENDICES |
    CA_DECLARATION | BANK_REFERENCES | OTHER
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File is empty.")

    mime_type = file.content_type or "application/octet-stream"

    doc_id = await save_document(
        case_id=case_id,
        file_bytes=file_bytes,
        filename=file.filename or "unnamed",
        doc_type=doc_type,
        db=db,
        fiscal_year=fiscal_year,
        reliability_level=reliability_level,
        auditor_name=auditor_name,
        notes=notes,
        mime_type=mime_type,
        user_id=current_user.get("sub", "SYSTEM"), # <-- FIX P1-AUDIT-03
    )

    logger.info(f"Document {doc_id} uploaded for case {case_id} ({doc_type})")
    return {
        "document_id": doc_id,
        "case_id":     case_id,
        "filename":    file.filename,
        "doc_type":    doc_type,
        "doc_type_label": DOC_TYPE_LABELS.get(doc_type, doc_type),
        "status":      "PRESENT",
    }


@router.get("/{case_id}/documents", response_model=List[DocumentOut])
async def api_list_documents(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Lists all documents associated with a folder."""
    docs = await get_documents_for_case(case_id=case_id, db=db)
    return docs


@router.get("/{case_id}/documents/{doc_id}/integrity")
async def api_verify_integrity(
    case_id: str,
    doc_id:  str,
    db:      AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """
    Verifies the cryptographic integrity of a document by recalculating its SHA-256 hash
    and comparing it to the fingerprint stored during the initial deposit.
    """
    return await verify_document_integrity(doc_id=doc_id, db=db)


@router.patch("/documents/{doc_id}/status")
async def api_update_document_status(
    doc_id: str,
    body:   DocumentStatusUpdate,
    db:     AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """
    Updates the status of a document.

    **status** accepts: PRESENT | MISSING | INCOMPLETE | REJECTED
    """
    await mark_document_status(
        doc_id=doc_id, 
        status=body.status, 
        db=db,
        user_id=current_user.get("sub", "SYSTEM"), # <-- FIX P1-AUDIT-04
    )
    return {"status": "ok", "doc_id": doc_id, "new_status": body.status}
