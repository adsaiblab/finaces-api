"""
app/services/audit_service.py
FinaCES V1.2 — Audit Trail Service (Async Migration Sprint 2B)

Single interface: log_event() called by all services.
Records each application action immutably in the audit_logs table.
"""

import json
import uuid
import traceback
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import AuditLog

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# TYPES OF PERMITTED EVENTS (Source of Truth)
# ════════════════════════════════════════════════════════════════

VALID_EVENT_TYPES = {
    # Dossier
    "CASE_CREATED",
    "CASE_UPDATED",
    "CASE_STATUS_CHANGED",
    "CASE_DELETED",
    "RECOMMENDATION_UPDATED",
    "CONCLUSION_UPDATED",
    # Gate
    "GATE_COMPUTED",
    "DD_CHECK_SAVED",
    "DOCUMENT_ADDED",
    "DOCUMENT_UPDATED",
    # Financiers
    "FINANCIAL_CREATED",
    "FINANCIAL_UPDATED",
    "FINANCIAL_STATEMENT_SAVED",
    "FINANCIAL_STATEMENT_UPDATED",
    "NORMALIZATION_SAVED",
    "ADJUSTMENT_ADDED",
    # Analyse
    "RATIO_COMPUTED",
    "INTERPRETATION_SAVED",
    "STRESS_TEST_COMPUTED",
    # Scoring
    "SCORECARD_COMPUTED",
    "OVERRIDE_ADDED",
    "OVERRIDE_CANCELLED",
    "EXPERT_REVIEW_SUBMITTED",
    # Rapport
    "REPORT_GENERATED",
    "REPORT_SECTION_UPDATED",
    "REPORT_FINALIZED",
    "REPORT_EXPORTED",
    # System
    "POLICY_LOADED",
    "POLICY_CREATED",
    "DATA_IMPORT",
    "DATA_EXPORT",
    "SYSTEM_ERROR",
    "SESSION_START",
    # Invalidation Pipeline IRB
    "PIPELINE_INVALIDATED",
}


# ════════════════════════════════════════════════════════════════
# MAIN FUNCTION
# ════════════════════════════════════════════════════════════════

async def log_event(
    db:           AsyncSession,
    event_type:   str,
    description:  str            = "",
    case_id:      Optional[str]  = None,
    entity_type:  Optional[str]  = None,
    entity_id:    Optional[str]  = None,
    old_value:    Optional[dict] = None,
    new_value:    Optional[dict] = None,
    user_id:      Optional[str]  = None,
    session_id:   Optional[str]  = None,
    duration_ms:  Optional[int]  = None,
    ip_address:   Optional[str]  = None,
    raise_on_error: bool         = False,
) -> Optional[str]:
    """
    Records an event to the audit trail asynchronously.

    Args:
        db: AsyncSession SQLAlchemy (injected by the calling service)
        event_type: Event type (see VALID_EVENT_TYPES)
        description: Text description of the action
        case_id: ID of the folder concerned (optional)
        entity_type: Entity type (ex: "Scorecard", "FinancialStatementRaw")
        entity_id: ID of the entity concerned
        old_value: State before modification (serializable dict)
        new_value: State after modification (serializable dict)
        user_id       : User ID
        session_id    : Session ID
        duration_ms: Duration of the operation in milliseconds
        ip_address    : IP address of the request
        # user_agent    : Browser or API client
        raise_on_error: Raise an exception if saving fails

    Returns: ID of the log created (str UUID), or None if silent failure.
    """
    log_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Normalization and validation of event type
    event_type_clean = event_type.upper().strip()
    if event_type_clean not in VALID_EVENT_TYPES:
        logger.warning(f"Unknown audit event type '{event_type}' — logging as SYSTEM_ERROR.")
        description = f"[EVENT_TYPE_UNKNOWN: {event_type}] {description}"
        event_type_clean = "SYSTEM_ERROR"

    try:
        audit_log = AuditLog(
            id=uuid.UUID(log_id),
            case_id=uuid.UUID(case_id) if case_id else None,
            event_type=event_type_clean,
            entity_type=entity_type,
            entity_id=entity_id,
            description=(description or "")[:2000],
            old_value_json=_safe_json(old_value),
            new_value_json=_safe_json(new_value),
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            duration_ms=duration_ms,
            created_at=now,
        )
        db.add(audit_log)
        await db.commit()
        logger.debug(f"[AUDIT] {event_type_clean} | {log_id} | case={case_id}")
        return log_id

    except Exception as exc:
        await db.rollback()
        _print_fallback_log(log_id, event_type_clean, case_id, description, now, exc)
        if raise_on_error:
            raise
        return None


# ════════════════════════════════════════════════════════════════
# PROFESSIONAL HELPERS
# ════════════════════════════════════════════════════════════════

async def log_error(
    db:        AsyncSession,
    error:     Exception,
    context:   str = "",
    case_id:   Optional[str] = None,
    entity_id: Optional[str] = None,
) -> Optional[str]:
    """
    Records a system error in the audit trail.
    Automatically captures the complete traceback.
    """
    tb = traceback.format_exc()
    return await log_event(
        db=db,
        event_type="SYSTEM_ERROR",
        description=f"{context} | {type(error).__name__}: {str(error)}"[:2000],
        case_id=case_id,
        entity_type="SystemError",
        entity_id=entity_id,
        new_value={
            "error_type": type(error).__name__,
            "error_msg":  str(error)[:500],
            "context":    context,
            "traceback":  tb[-1000:],
        },
    )


# ════════════════════════════════════════════════════════════════
# AUDIT TRAIL QUERIES (Async)
# ════════════════════════════════════════════════════════════════

async def get_audit_trail(
    db:          AsyncSession,
    case_id:     Optional[str] = None,
    event_type:  Optional[str] = None,
    entity_type: Optional[str] = None,
    limit:       int           = 200,
    offset:      int           = 0,
) -> list:
    """Returns the filtered audit trail."""
    stmt = select(AuditLog)
    if case_id:
        stmt = stmt.where(AuditLog.case_id == uuid.UUID(case_id))
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type.upper())
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [_log_to_dict(log) for log in result.scalars().all()]


async def get_case_timeline(db: AsyncSession, case_id: str) -> list:
    """
    Returns the complete timeline of a folder (chronological order).
    Enriched format with icon, color and section for UI display.
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.case_id == uuid.UUID(case_id))
        .order_by(AuditLog.created_at.asc())
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()
    timeline = []
    for log in logs:
        entry = _log_to_dict(log)
        entry["icon"]    = EVENT_ICONS.get(log.event_type, "📌")
        entry["color"]   = EVENT_COLORS.get(log.event_type, "#95A5A6")
        entry["event_type"] = log.event_type
        entry["section"] = EVENT_SECTIONS.get(log.event_type, "System")
        # UI translations mapped dynamically on the backend (helps frontend format cleanly)
        timeline.append(entry)
    return timeline


async def get_audit_stats(db: AsyncSession, case_id: Optional[str] = None) -> dict:
    """
    Returns aggregated statistics on the audit trail.
    If case_id provided: stats for this folder only.
    """
    stmt = select(AuditLog)
    if case_id:
        stmt = stmt.where(AuditLog.case_id == uuid.UUID(case_id))
    result = await db.execute(stmt)
    logs = result.scalars().all()

    counts_by_type: dict = {}
    for log in logs:
        counts_by_type[log.event_type] = counts_by_type.get(log.event_type, 0) + 1

    errors = [l for l in logs if l.event_type == "SYSTEM_ERROR"]
    last_event = max(logs, key=lambda l: l.created_at) if logs else None

    return {
        "total_events":       len(logs),
        "counts_by_type":     counts_by_type,
        "error_count":        len(errors),
        "last_event_at":      last_event.created_at if last_event else None,
        "last_event_type":    last_event.event_type if last_event else None,
        "unique_event_types": len(counts_by_type),
    }


async def get_recent_events(db: AsyncSession, limit: int = 50) -> list:
    """Returns the last N events for all sessions combined."""
    result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    return [_log_to_dict(log) for log in result.scalars().all()]


# ════════════════════════════════════════════════════════════════
# DISPLAY METADATA (retained in full)
# ════════════════════════════════════════════════════════════════

EVENT_ICONS = {
    "CASE_CREATED":                "📂",
    "CASE_UPDATED":                "✏️",
    "CASE_STATUS_CHANGED":         "🔄",
    "RECOMMENDATION_UPDATED":      "⚖️",
    "CONCLUSION_UPDATED":          "📝",
    "GATE_COMPUTED":               "🛡️",
    "DOCUMENT_ADDED":              "📄",
    "DOCUMENT_UPDATED":            "📝",
    "DD_CHECK_SAVED":              "✅",
    "FINANCIAL_STATEMENT_SAVED":   "💰",
    "FINANCIAL_STATEMENT_UPDATED": "💱",
    "FINANCIAL_CREATED":           "💰",
    "FINANCIAL_UPDATED":           "💱",
    "NORMALIZATION_SAVED":         "🔀",
    "ADJUSTMENT_ADDED":            "⚙️",
    "RATIO_COMPUTED":              "📊",
    "INTERPRETATION_SAVED":        "🖊️",
    "STRESS_TEST_COMPUTED":        "📉",
    "SCORECARD_COMPUTED":          "🏆",
    "OVERRIDE_ADDED":              "⚠️",
    "OVERRIDE_CANCELLED":          "↩️",
    "EXPERT_REVIEW_SUBMITTED":     "🔬",
    "REPORT_GENERATED":            "📋",
    "REPORT_SECTION_UPDATED":      "✏️",
    "REPORT_FINALIZED":            "✅",
    "REPORT_EXPORTED":             "⬇️",
    "POLICY_LOADED":               "📜",
    "POLICY_CREATED":              "🆕",
    "DATA_IMPORT":                 "📥",
    "DATA_EXPORT":                 "📤",
    "SYSTEM_ERROR":                "🔴",
    "SESSION_START":               "🔑",
    "PIPELINE_INVALIDATED":        "🗑️",
}

EVENT_COLORS = {
    "CASE_CREATED":                "#3498DB",
    "CASE_UPDATED":                "#3498DB",
    "CASE_STATUS_CHANGED":         "#F39C12",
    "RECOMMENDATION_UPDATED":      "#2980B9",
    "CONCLUSION_UPDATED":          "#2C3E50",
    "GATE_COMPUTED":               "#8E44AD",
    "DOCUMENT_ADDED":              "#2ECC71",
    "FINANCIAL_STATEMENT_SAVED":   "#27AE60",
    "FINANCIAL_CREATED":           "#27AE60",
    "FINANCIAL_UPDATED":           "#27AE60",
    "NORMALIZATION_SAVED":         "#16A085",
    "RATIO_COMPUTED":              "#1A527A",
    "INTERPRETATION_SAVED":        "#2C3E50",
    "STRESS_TEST_COMPUTED":        "#D35400",
    "SCORECARD_COMPUTED":          "#E74C3C",
    "OVERRIDE_ADDED":              "#E67E22",
    "EXPERT_REVIEW_SUBMITTED":     "#9B59B6",
    "REPORT_GENERATED":            "#27AE60",
    "REPORT_FINALIZED":            "#27AE60",
    "REPORT_EXPORTED":             "#27AE60",
    "SYSTEM_ERROR":                "#E74C3C",
    "POLICY_LOADED":               "#95A5A6",
    "PIPELINE_INVALIDATED":        "#7F8C8D",
}

EVENT_SECTIONS = {
    "CASE_CREATED":                "Dossier",
    "CASE_UPDATED":                "Dossier",
    "CASE_STATUS_CHANGED":         "Dossier",
    "GATE_COMPUTED":               "Gate",
    "DOCUMENT_ADDED":              "Gate",
    "DD_CHECK_SAVED":              "Gate",
    "FINANCIAL_STATEMENT_SAVED":   "Financiers",
    "FINANCIAL_CREATED":           "Financiers",
    "FINANCIAL_UPDATED":           "Financiers",
    "NORMALIZATION_SAVED":         "Normalization",
    "ADJUSTMENT_ADDED":            "Normalization",
    "RATIO_COMPUTED":              "Analysis",
    "INTERPRETATION_SAVED":        "Analysis",
    "STRESS_TEST_COMPUTED":        "Capacity",
    "SCORECARD_COMPUTED":          "Scoring",
    "OVERRIDE_ADDED":              "Scoring",
    "EXPERT_REVIEW_SUBMITTED":     "Scoring",
    "REPORT_GENERATED":            "Rapport",
    "REPORT_EXPORTED":             "Export",
    # SYSTEM
    "EXPERTISE_REQUESTED":         "Expertise",
    "EXPERTISE_SUBMITTED":         "Expertise",
    "EXPERTISE_REJECTED":          "Expertise",
    "SYSTEM_ERROR":                "System",
    "SESSION_START":               "System",
    "PIPELINE_INVALIDATED":        "System",
}


# ════════════════════════════════════════════════════════════════
# PRIVATE HELPERS
# ════════════════════════════════════════════════════════════════

def _safe_json(value) -> Optional[str]:
    """Securely serializes a dict to JSON (datetime/Decimal/UUID handles)."""
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({"raw": str(value)})


def _safe_parse_json(value: Optional[str]) -> Optional[dict]:
    """Parses a JSON string securely."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(value)}


def _log_to_dict(log: AuditLog) -> dict:
    """Converts an ORM AuditLog to a JSON serializable dict."""
    return {
        "id":          str(log.id),
        "case_id":     str(log.case_id) if log.case_id else None,
        "event_type":  log.event_type,
        "entity_type": log.entity_type,
        "entity_id":   log.entity_id,
        "description": log.description,
        "old_value":   _safe_parse_json(log.old_value_json),
        "new_value":   _safe_parse_json(log.new_value_json),
        "user_id":     log.user_id,
        "session_id":  log.session_id,
        "duration_ms": log.duration_ms,
        "created_at":  log.created_at,
    }


def _print_fallback_log(
    log_id:      str,
    event_type:  str,
    case_id:     Optional[str],
    description: str,
    now:         datetime,
    exc:         Exception,
) -> None:
    """
    Fallback console if writing to DB fails.
    Avoids the silent loss of a critical event.
    """
    logger.error(
        f"[AUDIT FALLBACK] {now.isoformat()} | {event_type} | "
        f"case={case_id} | {description} | DB_ERROR: {exc}"
    )
