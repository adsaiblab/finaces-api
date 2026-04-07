"""
app/api/routes/export.py — Word / PDF Export
Sprint 2B: GAP-08 — MCC-grade report generation and download.
"""

import logging
import uuid
from typing import Optional

from app.core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi_limiter.depends import RateLimiter
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.db.models import MCCGradeReport
from app.services.export_service import export_to_word, export_to_pdf

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cases",
    tags=["Export"],
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _report_to_dict(report: MCCGradeReport) -> dict:
    """Converts a MCCGradeReport ORM object to a dict compatible with export_service."""
    return {
        "report_id":                str(report.id),
        "case_id":                  str(report.case_id),
        "recommendation":           report.recommendation.value if report.recommendation and hasattr(report.recommendation, "value") else report.recommendation,
        "section_01_info":          report.section_01_info,
        "section_02_objective":      report.section_02_objective,
        "section_03_scope":          report.section_03_scope,
        "section_04_executive_summary": report.section_04_executive_summary,
        "section_05_profile":       report.section_05_profile,
        "section_06_analysis":      report.section_06_analysis,
        "section_07_capacity":      report.section_07_capacity,
        "section_08_red_flags":     report.section_08_red_flags,
        "section_09_mitigants":    report.section_09_mitigants,
        "section_10_scoring":       report.section_10_scoring,
        "section_11_assessment":  report.section_11_assessment,
        "section_12_recommendation":report.section_12_recommendation,
        "section_13_limitations":       report.section_13_limitations,
        "section_14_conclusion":    report.section_14_conclusion,
    }


async def _get_report_or_404(case_id: str, db: AsyncSession) -> MCCGradeReport:
    """Retrieves the most recent MCCGradeReport for a case or raises 404."""
    result = await db.execute(
        select(MCCGradeReport)
        .where(MCCGradeReport.case_id == uuid.UUID(case_id))
        .order_by(MCCGradeReport.created_at.desc())
        .limit(1)
    )
    report = result.scalars().first()
    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"No MCCGradeReport found for case {case_id}. "
                   "Finalize the report before starting export."
        )
    return report


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.post("/{case_id}/export/word", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def api_export_word(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """
    Generates the MCC-grade report in Word (.docx) format.

    - Retrieves the final report for the case
    - Delegates generation to `export_service.export_to_word`
    - Updates `MCCGradeReport.export_word_path`
    - Emits REPORT_EXPORTED in the audit trail
    """
    report = await _get_report_or_404(case_id=case_id, db=db)
    report_dict = _report_to_dict(report)

    file_path = await export_to_word(
        report=report_dict,
        case_id=case_id,
        db=db,
    )

    logger.info(f"Word export requested for case {case_id}: {file_path}")
    return {
        "status":      "ok",
        "format":      "docx",
        "case_id":     case_id,
        "report_id":   str(report.id),
        "file_path":   file_path,
        "download_url": f"/api/v1/cases/{case_id}/export/word/download",
    }


@router.post("/{case_id}/export/pdf", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def api_export_pdf(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)):
    """
    Generates the MCC-grade report in PDF format via WeasyPrint.

    - Retrieves the final report for the case
    - Delegates generation to `export_service.export_to_pdf`
    - Updates `MCCGradeReport.export_pdf_path`
    - Emits REPORT_EXPORTED in the audit trail
    """
    report = await _get_report_or_404(case_id=case_id, db=db)
    report_dict = _report_to_dict(report)

    file_path = await export_to_pdf(
        report=report_dict,
        case_id=case_id,
        db=db,
    )

    logger.info(f"PDF export requested for case {case_id}: {file_path}")
    return {
        "status":      "ok",
        "format":      "pdf",
        "case_id":     case_id,
        "report_id":   str(report.id),
        "file_path":   file_path,
        "download_url": f"/api/v1/cases/{case_id}/export/pdf/download",
    }


@router.get("/{case_id}/export/word/download")
async def api_download_word(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Downloads the previously generated Word file."""
    report = await _get_report_or_404(case_id=case_id, db=db)
    if not report.export_word_path:
        raise HTTPException(
            status_code=404,
            detail="No Word export available. Call POST /export/word first."
        )
    return FileResponse(
        path=report.export_word_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"Note_MCC_{case_id[:8]}.docx",
    )


@router.get("/{case_id}/export/pdf/download")
async def api_download_pdf(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Downloads the previously generated PDF file."""
    report = await _get_report_or_404(case_id=case_id, db=db)
    if not report.export_pdf_path:
        raise HTTPException(
            status_code=404,
            detail="No PDF export available. Call POST /export/pdf first."
        )
    return FileResponse(
        path=report.export_pdf_path,
        media_type="application/pdf",
        filename=f"Note_MCC_{case_id[:8]}.pdf",
    )
