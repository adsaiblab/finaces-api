"""
app/services/document_service.py
FinaCES V1.2 — Document management (Async Migration Sprint 2B, GAP-06)

Fournit :
  - save_document(): Upload + SHA-256 hash + ORM persistence
  - get_documents_for_case(): List of documents in a folder
  - verify_document_integrity(): Hash integrity check
  - mark_document_status(): Status update + audit
"""

import hashlib
import uuid
import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiofiles

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import DocumentEvidence
from app.schemas.enums import DocType, DocStatus, ReliabilityLevel
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

# ── Storage directory ─────────────────────────────────────
UPLOAD_DIR = Path(os.getenv("FINACES_UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── Display dictionaries (kept from legacy) ────────────
DOC_TYPE_LABELS: dict[str, str] = {
    "FINANCIAL_STATEMENTS": "Financial Statements",
    "AUDITOR_OPINION":      "Auditor Opinion",
    "ANNEXES":              "Accounting Annexes",
    "CA_DECLARATION":       "Revenue Declaration",
    "BANK_REFERENCES":      "Bank References",
    "OTHER":                "Other Document",
}

RELIABILITY_LABELS: dict[str, str] = {
    "HIGH":      "High (Big4 / recognized firm)",
    "MEDIUM":    "Medium (credible local firm)",
    "LOW":       "Low (limited audit)",
    "UNAUDITED": "Unaudited",
}

VALID_DOC_STATUSES = ["PRESENT", "MISSING", "INCOMPLETE", "REJECTED"]


# ════════════════════════════════════════════════════════════════
# MAIN SERVICE FUNCTIONS
# ════════════════════════════════════════════════════════════════

async def save_document(
    case_id:           str,
    file_bytes:        bytes,
    filename:          str,
    doc_type:          str,
    db:                AsyncSession,
    fiscal_year:       Optional[int]  = None,
    reliability_level: str            = "MEDIUM",
    red_flags:         Optional[list] = None,
    auditor_name:      Optional[str]  = None,
    notes:             Optional[str]  = None,
    mime_type:         Optional[str]  = None,
    user_id:           str            = "SYSTEM",
) -> str:
    """
    Save a file uploaded asynchronously:
      1. Sanitizes filename (path traversal prevention)
      2. Calculates SHA-256 hash (immutable cryptographic fingerprint)
      3. Writes the file to disk via aiofiles (non-blocking)
      4. Creates the DocumentEvidence ORM and persists it
      5. Emits a DOCUMENT_ADDED event in the audit trail

    Returns the document_id (str UUID).
    """
    doc_id = str(uuid.uuid4())

    # 1. Filename sanitization — strip path components and dangerous characters.
    #    Keeps only alphanumerics, dots, dashes, underscores.
    #    e.g. "../../etc/passwd" → "etc_passwd", "report 2024.pdf" → "report_2024.pdf"
    safe_filename = _sanitize_filename(filename)

    sha256 = _compute_hash(file_bytes)
    file_size_kb = round(len(file_bytes) / 1024, 2)

    # 2. Directory by case
    case_dir = UPLOAD_DIR / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    file_path = case_dir / f"{doc_id}_{safe_filename}"

    # 3. Asynchronous writing
    try:
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_bytes)
        logger.info(f"File written: {file_path} ({file_size_kb} KB)")
    except Exception as exc:
        logger.error(f"File write failed for doc {doc_id}: {exc}")
        raise

    # 4. ORM Persistence
    doc = DocumentEvidence(
        id=uuid.UUID(doc_id),
        case_id=uuid.UUID(case_id),
        doc_type=DocType(doc_type),
        fiscal_year=fiscal_year,
        filename=safe_filename,
        file_path=str(file_path),
        file_size_kb=file_size_kb,
        mime_type=mime_type,
        status=DocStatus.PRESENT,
        reliability_level=ReliabilityLevel(reliability_level) if reliability_level else ReliabilityLevel.MEDIUM,
        red_flags_json=red_flags or [],
        file_hash=sha256,
        auditor_name=auditor_name,
        notes=notes,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # 5. Audit
    await log_event(
        db=db,
        event_type="DOCUMENT_UPLOADED",
        entity_type="CaseDocument",
        entity_id=doc_id,
        case_id=case_id,
        description=f"Document uploaded: {safe_filename} ({doc_type})",
        new_value={
            "doc_type":          doc_type,
            "fiscal_year":       fiscal_year,
            "sha256":            sha256,
            "file_size_kb":      file_size_kb,
            "reliability_level": reliability_level,
        },
        user_id=user_id,
    )

    return doc_id


async def get_documents_for_case(case_id: str, db: AsyncSession) -> list:
    """Returns all documents in a folder, enriched with display labels."""
    result = await db.execute(
        select(DocumentEvidence)
        .where(DocumentEvidence.case_id == uuid.UUID(case_id))
        .order_by(DocumentEvidence.uploaded_at.desc())
    )
    docs = result.scalars().all()
    return [
        {
            "id":                str(doc.id),
            "doc_type":          doc.doc_type.value if hasattr(doc.doc_type, "value") else doc.doc_type,
            "doc_type_label":    DOC_TYPE_LABELS.get(str(doc.doc_type), str(doc.doc_type)),
            "fiscal_year":       doc.fiscal_year,
            "filename":          doc.filename,
            "file_size_kb":      float(doc.file_size_kb) if doc.file_size_kb else None,
            "mime_type":         doc.mime_type,
            "file_hash":         doc.file_hash,
            "status":            doc.status.value if hasattr(doc.status, "value") else doc.status,
            "reliability_level": doc.reliability_level.value if hasattr(doc.reliability_level, "value") else doc.reliability_level,
            "reliability_label": RELIABILITY_LABELS.get(str(doc.reliability_level), str(doc.reliability_level)),
            "red_flags":         doc.red_flags_json or [],
            "auditor_name":      doc.auditor_name,
            "notes":             doc.notes,
            "uploaded_at":       doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        }
        for doc in docs
    ]


async def verify_document_integrity(doc_id: str, db: AsyncSession) -> dict:
    """
    Reads the file from disk and recalculates its SHA-256 hash.
    Returns {is_intact, stored_hash, computed_hash}.
    """
    result = await db.execute(
        select(DocumentEvidence).where(DocumentEvidence.id == uuid.UUID(doc_id))
    )
    doc = result.scalars().first()
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    async with aiofiles.open(doc.file_path, mode="rb") as f:
        file_bytes = await f.read()
    computed = _compute_hash(file_bytes)
    return {
        "is_intact":     computed == doc.file_hash,
        "stored_hash":   doc.file_hash,
        "computed_hash": computed,
    }


async def mark_document_status(
    doc_id:  str,
    status:  str,
    db:      AsyncSession,
    user_id: str = "SYSTEM",
) -> None:
    """
    Updates the status of a document.
    Authorized statuses: PRESENT | MISSING | INCOMPLETE | REJECTED
    Emits a DOCUMENT_UPDATED event in the audit trail.
    """
    if status not in VALID_DOC_STATUSES:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: '{status}'. Allowed values: {VALID_DOC_STATUSES}"
        )

    result = await db.execute(
        select(DocumentEvidence).where(DocumentEvidence.id == uuid.UUID(doc_id))
    )
    doc = result.scalars().first()
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    old_status = doc.status.value if hasattr(doc.status, "value") else str(doc.status)
    doc.status = DocStatus(status)
    await db.commit()

    await log_event(
        db=db,
        event_type="DOCUMENT_UPDATED",
        entity_type="DocumentEvidence",
        entity_id=doc_id,
        case_id=str(doc.case_id),
        description=f"Document status: {old_status} → {status}",
        old_value={"status": old_status},
        new_value={"status": status},
        user_id=user_id,
    )
    logger.info(f"Document {doc_id} status updated: {old_status} → {status}")


# ════════════════════════════════════════════════════════════════
# PRIVATE HELPERS
# ════════════════════════════════════════════════════════════════

def _compute_hash(file_bytes: bytes) -> str:
    """Calculates the SHA-256 hash of a file."""
    return hashlib.sha256(file_bytes).hexdigest()


def _sanitize_filename(filename: str) -> str:
    """
    Strips path traversal sequences and dangerous characters from a filename.
    Keeps only the base name (no directory components), then replaces
    anything outside [a-zA-Z0-9._-] with an underscore.

    Examples:
      '../../etc/passwd'      → 'etc_passwd'
      'report 2024 (v2).pdf'  → 'report_2024__v2_.pdf'
      '../secret.xlsx'        → 'secret.xlsx'
    """
    # Extract base name only — kills all path traversal
    base = Path(filename).name
    # Replace any character that is not alphanumeric, dot, dash, or underscore
    safe = re.sub(r"[^\w.\-]", "_", base)
    # Collapse multiple consecutive underscores for readability
    safe = re.sub(r"_+", "_", safe)
    return safe or "unnamed"