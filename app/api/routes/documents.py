"""
app/api/routes/documents.py — Document management
Sprint 2B: GAP-06 — Upload, listing and status management of evidence.
8.4: Input validation — MIME, size cap, extension whitelist, doc_type guard.
"""

import logging
from typing import Optional, List

from app.core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi_limiter.depends import RateLimiter
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
from app.schemas.enums import DocType

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cases",
    tags=["Documents"],
)

# ── Upload constraints ────────────────────────────────────────────────────────
# Max file size: 20 MB — covers the largest realistic financial PDF/Excel.
# Anything above is almost certainly an abuse vector.
_MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB

# Accepted extensions — financial evidence documents only.
# No executables, scripts, or archive formats.
_ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".docx", ".doc", ".csv", ".png", ".jpg", ".jpeg"}

# Magic bytes → accepted MIME types.
# We verify the actual file content, NOT the client-supplied Content-Type header.
# A client can send Content-Type: application/pdf with a .exe inside — magic bytes catch this.
_MAGIC_SIGNATURES: dict[bytes, str] = {
    b"%PDF":                          "application/pdf",
    b"PK\x03\x04":                    "application/zip",   # .xlsx / .docx (ZIP-based)
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": "application/msoffice",  # .xls / .doc (OLE2)
    b"\xff\xd8\xff":                  "image/jpeg",
    b"\x89PNG\r\n\x1a\n":             "image/png",
}

# Valid DocType string values — derived from enum to stay DRY.
_VALID_DOC_TYPES = {e.value for e in DocType}


def _check_magic_bytes(file_bytes: bytes, filename: str) -> None:
    """
    Verifies that the file content matches a known safe magic signature.
    CSV and plain-text files have no magic bytes — they pass by extension only.
    Raises HTTP 415 if the content looks like a forbidden file type.
    """
    # CSV / plain text: no magic bytes — extension whitelist is the guard.
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == ".csv":
        return

    for magic, _ in _MAGIC_SIGNATURES.items():
        if file_bytes[:len(magic)] == magic:
            return  # Known safe signature found

    raise HTTPException(
        status_code=415,
        detail=(
            f"Unsupported file content for '{filename}'. "
            "Accepted formats: PDF, Excel (.xlsx/.xls), Word (.docx/.doc), CSV, JPEG, PNG."
        ),
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

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.post(
    "/{case_id}/documents",
    dependencies=[
        # Upload triggers SHA-256 hashing + disk write + DB insert.
        # 10 uploads/60s covers bulk evidence ingestion without enabling abuse.
        # NOTE: RateLimiter keys on client IP — ensure X-Forwarded-For is
        # trusted behind reverse proxy (Phase 3 infra config).
        Depends(RateLimiter(times=10, seconds=60)),
    ],
)
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
    current_user:      dict           = Depends(get_current_user),
):
    """
    Upload a proof document and associate it with a case.

    Validations applied (8.4):
      1. doc_type must be a valid DocType enum value
      2. File extension must be in the whitelist (.pdf, .xlsx, .xls, .docx, .doc, .csv, .png, .jpg, .jpeg)
      3. File size must not exceed 20 MB
      4. File magic bytes must match a known safe signature (content ≠ declared extension trap)

    - Calculates the SHA-256 hash of the upload (cryptographic traceability)
    - Writes the file to `uploads/{case_id}/`
    - Creates a `DocumentEvidence` record in DB
    - Emits a DOCUMENT_ADDED event in the audit trail

    **doc_type** accepts: FINANCIAL_STATEMENTS | AUDITOR_OPINION | ANNEXES |
    CA_DECLARATION | BANK_REFERENCES | OTHER
    """
    # ── Guard 1: doc_type enum validation ────────────────────────────────────
    if doc_type not in _VALID_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid doc_type '{doc_type}'. "
                f"Accepted values: {sorted(_VALID_DOC_TYPES)}"
            ),
        )

    # ── Guard 2: extension whitelist ─────────────────────────────────────────
    original_filename = file.filename or "unnamed"
    ext = ("." + original_filename.rsplit(".", 1)[-1].lower()) if "." in original_filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"File extension '{ext}' is not allowed. "
                f"Accepted extensions: {sorted(_ALLOWED_EXTENSIONS)}"
            ),
        )

    # ── Guard 3: size cap (read once, reuse bytes) ────────────────────────────
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File is empty.")
    if len(file_bytes) > _MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File size {round(len(file_bytes) / 1024 / 1024, 1)} MB "
                f"exceeds the 20 MB limit."
            ),
        )

    # ── Guard 4: magic bytes verification ────────────────────────────────────
    _check_magic_bytes(file_bytes, original_filename)

    mime_type = file.content_type or "application/octet-stream"

    doc_id = await save_document(
        case_id=case_id,
        file_bytes=file_bytes,
        filename=original_filename,
        doc_type=doc_type,
        db=db,
        fiscal_year=fiscal_year,
        reliability_level=reliability_level,
        auditor_name=auditor_name,
        notes=notes,
        mime_type=mime_type,
        user_id=current_user.get("sub", "SYSTEM"),  # <-- FIX P1-AUDIT-03
    )

    logger.info(f"Document {doc_id} uploaded for case {case_id} ({doc_type})")
    return {
        "document_id": doc_id,
        "case_id":     case_id,
        "filename":    original_filename,
        "doc_type":    doc_type.value if hasattr(doc_type, 'value') else doc_type,
        "doc_type_label": DOC_TYPE_LABELS.get(doc_type.value if hasattr(doc_type, 'value') else doc_type, "N/A"),
        "status":      "PRESENT",
    }


@router.get("/{case_id}/documents", response_model=List[DocumentOut])
async def api_list_documents(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lists all documents associated with a case."""
    docs = await get_documents_for_case(case_id=case_id, db=db)
    return docs


@router.get("/{case_id}/documents/{doc_id}/integrity")
async def api_verify_integrity(
    case_id: str,
    doc_id:  str,
    db:      AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    current_user: dict = Depends(get_current_user),
):
    """
    Updates the status of a document.

    **status** accepts: PRESENT | MISSING | INCOMPLETE | REJECTED
    """
    await mark_document_status(
        doc_id=doc_id,
        status=body.status,
        db=db,
        user_id=current_user.get("sub", "SYSTEM"),  # <-- FIX P1-AUDIT-04
    )
    return {"status": "ok", "doc_id": doc_id, "new_status": body.status}