"""
app/services/dashboard_service.py
"""

from typing import Dict, Any, List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.db.models import EvaluationCase, Scorecard, AuditLog

async def get_dashboard_statistics(db: AsyncSession) -> Dict[str, Any]:
    """Extract all statistics for the dashboard."""
    total_cases = 0
    # 1. All cases
    result_cases = await db.execute(select(func.count(EvaluationCase.id)))
    cases = cases_result.scalars().all()
    total = len(cases)

    by_status: dict = {}
    for c in cases:
        key = c.status.value if hasattr(c.status, "value") else str(c.status)
        by_status[key] = by_status.get(key, 0) + 1

    # 2. Risk distribution — most recent scorecard by file
    scorecards_result = await db.execute(select(Scorecard))
    scorecards = scorecards_result.scalars().all()

    risk_counts = {"LOW": 0, "MODERATE": 0, "HIGH": 0, "CRITICAL": 0}
    seen_cases: set = set()
    for sc in sorted(scorecards, key=lambda s: s.computed_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        rc = sc.risk_class.value if hasattr(sc.risk_class, "value") else str(sc.risk_class)
        # Handle older french states if any mapped backwards
        if rc == "MODERE": rc = "MODERATE"
        if rc == "ELEVE": rc = "HIGH"
        if rc == "CRITIQUE": rc = "CRITICAL"
        
        if sc.case_id not in seen_cases and rc in risk_counts:
            risk_counts[rc] += 1
            seen_cases.add(sc.case_id)

    # 3. Recent activity
    events_result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(15)
    )
    recent_events = events_result.scalars().all()
    events = [
        {
            "id":          str(e.id),
            "event_type":  e.event_type,
            "case_id":     str(e.case_id) if e.case_id else None,
            "description": e.description,
            "created_at":  e.created_at,
        }
        for e in recent_events
    ]

    # 4. Recent files (last 5) with risk class
    recent_cases_result = await db.execute(
        select(EvaluationCase)
        .order_by(EvaluationCase.created_at.desc())
        .limit(5)
    )
    recent_cases_orm = recent_cases_result.scalars().all()
    recent_cases_list = []

    for c in recent_cases_orm:
        sc_result = await db.execute(
            select(Scorecard)
            .where(Scorecard.case_id == c.id)
            .order_by(desc(Scorecard.computed_at))
            .limit(1)
        )
        case_sc = sc_result.scalars().first()
        risk_class = None
        if case_sc:
            rc = case_sc.risk_class.value if hasattr(case_sc.risk_class, "value") else str(case_sc.risk_class)
            if rc == "MODERE": rc = "MODERATE"
            if rc == "ELEVE": rc = "HIGH"
            if rc == "CRITIQUE": rc = "CRITICAL"
            risk_class = rc

        recent_cases_list.append({
            "id":               str(c.id),
            "market_reference": c.market_reference,
            "status":           c.status.value if hasattr(c.status, "value") else str(c.status),
            "risk_class":       risk_class,
            "created_at":       c.created_at,
        })

    return {
        "total_cases":        total,
        "by_status":          by_status,
        "risk_distribution":  risk_counts,
        "recent_events":      events,
        "recent_cases":       recent_cases_list,
    }
