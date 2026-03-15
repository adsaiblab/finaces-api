"""
app/api/routes/audit.py — Piste d'audit
FinaCES V1.2 — Async Migration Sprint 2B

All reading functions (get_recent_events, get_audit_stats,
get_audit_trail) prennent maintenant db: AsyncSession en premier argument.
CSV export generated in memory (no direct DB).
"""

import csv
import io
import logging
from typing import Optional

from app.core.security import get_current_user
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.audit_service import (
    get_recent_events,
    get_audit_trail,
    get_audit_stats,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Audit"])


@router.get("/audit/events")
async def api_get_audit_events(
    limit:      int            = 50,
    case_id:    Optional[str]  = None,
    event_type: Optional[str]  = None,
    db:         AsyncSession   = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Returns recent audit events (filterable by case_id and event_type)."""
    if case_id or event_type:
        # Use get_audit_trail to filter in database — more efficient than filtering in memory
        events = await get_audit_trail(
            db=db,
            case_id=case_id,
            event_type=event_type,
            limit=limit,
        )
    else:
        events = await get_recent_events(db=db, limit=limit)
    return events


@router.get("/audit/stats")
async def api_get_audit_stats(
    case_id: Optional[str] = None,
    db:      AsyncSession  = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Returns aggregated audit trail statistics."""
    return await get_audit_stats(db=db, case_id=case_id)


@router.get("/audit/trail")
async def api_get_audit_trail(
    case_id:    Optional[str] = None,
    event_type: Optional[str] = None,
    limit:      int           = 200,
    offset:     int           = 0,
    db:         AsyncSession  = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Returns the filtered audit trail with pagination."""
    return await get_audit_trail(
        db=db,
        case_id=case_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )


@router.get("/audit/export/csv")
async def api_export_audit_csv(
    case_id: Optional[str] = None,
    db:      AsyncSession  = Depends(get_db),
current_user: dict = Depends(get_current_user)):
    """Generates and returns the audit trail in CSV format (in memory)."""
    events = await get_audit_trail(
        db=db,
        case_id=case_id,
        limit=10_000,
    )

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id", "created_at", "case_id", "event_type",
            "entity_type", "entity_id", "description",
            "user_id", "duration_ms",
        ],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(events)

    filename = f"audit_trail_{case_id[:8] if case_id else 'global'}.csv"

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
