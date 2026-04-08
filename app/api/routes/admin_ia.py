"""
Admin IA routes — drift monitoring and model management.

Routes (prefix /admin/ia):
    GET  /drift-report     → generate and return Evidently drift report
"""

import logging
from typing import Annotated

import sentry_sdk
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.core.security import get_current_user
from app.db.models import User
from app.engines.ia.drift_report import generate_drift_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/ia", tags=["Admin — IA"])


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that restricts access to admin users only."""
    if not getattr(current_user, "is_admin", False):
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    return current_user


@router.get(
    "/drift-report",
    summary="Generate IA feature drift report (admin only)",
    description=(
        "Runs an Evidently DataDriftPreset report comparing a reference window "
        "to the most recent production predictions. See RETRAINING_RULES.md for "
        "threshold definitions and escalation procedure. "
        "Triggered manually or by a weekly cron — no embedded scheduler."
    ),
)
async def get_drift_report(
    reference_period_days: Annotated[int, Query(ge=7, le=180, description="Reference window in days")] = 30,
    current_period_days: Annotated[int, Query(ge=1, le=30, description="Current production window in days")] = 7,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> dict:
    """
    Generate IA feature drift report.

    Returns drift_detected, drifted_features, drift_score, and per-feature details.
    Emits Sentry warning/error events if thresholds defined in RETRAINING_RULES.md are exceeded.
    """
    report = await generate_drift_report(
        db=db,
        reference_period_days=reference_period_days,
        current_period_days=current_period_days,
    )

    # ── Sentry alerts per RETRAINING_RULES.md thresholds ─────────────────────
    drift_score = report.get("drift_score", 0.0)
    drifted_features = report.get("drifted_features", [])

    CRITICAL_FEATURES = {"debt_to_equity", "net_margin", "current_ratio", "operating_cash_flow", "z_score_altman"}
    critical_drifted = [f for f in drifted_features if f in CRITICAL_FEATURES]

    if drift_score > 0.30:
        logger.error(f"IA drift CRITICAL — score {drift_score}, features: {drifted_features}")
        sentry_sdk.capture_message(
            f"[FinaCES IA] Drift CRITICAL — score={drift_score:.4f} — {drifted_features}",
            level="error",
            extras={"report": report},
        )
    elif drift_score > 0.15 and len(critical_drifted) >= 2:
        logger.warning(f"IA drift WARNING — score {drift_score}, critical features: {critical_drifted}")
        sentry_sdk.capture_message(
            f"[FinaCES IA] Drift WARNING — score={drift_score:.4f} — critical={critical_drifted}",
            level="warning",
            extras={"report": report},
        )

    return report
