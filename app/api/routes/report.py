"""
app/api/routes/report.py — MCC-grade rating (report)
FinaCES V1.2 — Async Migration Sprint 2B
"""

import traceback
import logging
from app.core.security import get_current_user, RequireRole
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi_limiter.depends import RateLimiter

from app.core.exceptions import FinaCESBaseException
from app.db.database import get_db
from app.services.report_service import (
    build_full_report,
    get_report,
    update_report_section,
    finalize_report,
)
from app.services.policy_service import get_active_policy
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Report"])


class ReportSectionUpdate(BaseModel):
    section_key: str
    content:     str


@router.post("/cases/{case_id}/report/build", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def api_build_report(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """
    Generates the full MCC-grade score (14 sections).

    The await cascade in build_full_report is:
      1. _get_case_data           → EvaluationCase + Bidder
      2. FinancialStatementNormalized SELECT
      3. RatioSet SELECT (multi-year)
      4. Scorecard SELECT (most recent)
      5. GateResult SELECT (most recent)
      6. InterpretationResult SELECT (best-effort)
      7. _get_latest_capacity → ContractCapacityAssessment
      8. _build_section_XX()      → pure sync (no await, no DB)
      9. _save_report()           → MCCGradeReport INSERT
     10. log_event()              → AuditLog REPORT_GENERATED
    """
    try:
        policy = await get_active_policy(db=db)
        result = await build_full_report(case_id=case_id, policy=policy, db=db)
        
        # <-- FIX P1-AUDIT-05
        await log_event(
            db=db,
            event_type="REPORT_GENERATED",
            entity_type="MCCGradeReport",
            entity_id=str(result.get("id")) if isinstance(result, dict) else None,
            case_id=str(case_id),
            description="Full MCC-grade report generated.",
            user_id=current_user.get("sub", "SYSTEM")
        )
        
        return result
    except HTTPException:
        raise
    except FinaCESBaseException:
        raise
    except ValueError as val_err:
        logger.warning(f"Validation error: {str(val_err)}")
        raise HTTPException(status_code=422, detail="Payload structure validation failed.")
    except Exception as exc:
        logger.error(f"Error building report for case {case_id}: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/cases/{case_id}/report")
async def api_get_report(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Returns the most recent MCC-grade report."""
    result = await get_report(case_id=case_id, db=db)
    if not result:
        raise HTTPException(status_code=404, detail="No report generated")
    return result


@router.put("/cases/{case_id}/report/{report_id}/section")
async def api_update_report_section(
    case_id:   str,
    report_id: str,
    body:      ReportSectionUpdate,
    db:        AsyncSession = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Updates a section of the report (post-generation corrections)."""
    try:
        await update_report_section(
            report_id=report_id,
            section_key=body.section_key,
            content=body.content,
            db=db,
        )
        await log_event(
            db=db,
            event_type="REPORT_SECTION_UPDATED",
            entity_type="MCCGradeReport",
            entity_id=report_id,
            case_id=case_id,
            description=f"Section {body.section_key} updated",
            new_value={"section_key": body.section_key, "length": len(body.content)},
            user_id=current_user.get("sub", "SYSTEM"), # <-- FIX P1-AUDIT-06
        )
        return {"status": "ok"}
    except HTTPException:
        raise
    except FinaCESBaseException:
        raise
    except ValueError as val_err:
        logger.warning(f"Validation error: {str(val_err)}")
        raise HTTPException(status_code=422, detail="Payload structure validation failed.")
    except Exception as exc:
        logger.error(f"Error updating report section: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/cases/{case_id}/report/{report_id}/finalize")
async def finalize_mcc_report(
    case_id:      str,
    report_id:    str,
    db:           AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)):
    """Marks the report as FINAL (Restricted access)."""
    try:
        report = await finalize_report(report_id=report_id, db=db)
        if report: # finalize_report now returns the report object if successful
            await log_event(
                db=db,
                event_type="REPORT_FINALIZED",
                entity_type="MCCGradeReport",
                entity_id=str(report.id),
                case_id=str(report.case_id),
                description="MCC-grade score finalized",
                user_id=current_user.get("sub", "SYSTEM"),
            )
            return {"status": "FINALIZED"}

        raise HTTPException(status_code=400, detail="Finalization failed")
    except HTTPException:
        raise
    except FinaCESBaseException:
        raise
    except Exception as exc:
        logger.error(f"Error finalizing report: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")
