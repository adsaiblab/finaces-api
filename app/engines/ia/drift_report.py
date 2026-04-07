"""
Drift Report — Evidently-based feature drift detection for the IA scoring model.

Usage:
    from app.engines.ia.drift_report import generate_drift_report
    report = await generate_drift_report(db, reference_period_days=30, current_period_days=7)

Returns:
    {
        "drift_detected": bool,
        "drifted_features": list[str],
        "drift_score": float,           # mean drift score across all features
        "n_reference": int,             # number of predictions in reference period
        "n_current": int,               # number of predictions in current period
        "feature_drift_details": dict,  # per-feature drift scores
        "checked_at": str (ISO 8601),
        "error": str | None             # set if report could not be computed
    }
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import IAPrediction

logger = logging.getLogger(__name__)

# Minimum sample size — below this we skip drift check to avoid false positives
_MIN_SAMPLES = 20


async def generate_drift_report(
    db: AsyncSession,
    reference_period_days: int = 30,
    current_period_days: int = 7,
) -> dict[str, Any]:
    """
    Generate a feature drift report comparing two windows of IA predictions.

    Args:
        db:                     Async database session.
        reference_period_days:  Lookback for the stable reference window (default 30d).
        current_period_days:    Lookback for the current production window (default 7d).

    Returns:
        Drift report dict (see module docstring for schema).
    """
    now = datetime.now(timezone.utc)
    current_cutoff   = now - timedelta(days=current_period_days)
    reference_cutoff = now - timedelta(days=reference_period_days + current_period_days)
    reference_end    = current_cutoff  # reference window ends where current begins

    checked_at = now.isoformat()

    try:
        # ── Load predictions from both periods ───────────────────────────────
        stmt_reference = (
            select(IAPrediction)
            .where(
                IAPrediction.created_at >= reference_cutoff,
                IAPrediction.created_at < reference_end,
                IAPrediction.input_features.isnot(None),
            )
        )
        stmt_current = (
            select(IAPrediction)
            .where(
                IAPrediction.created_at >= current_cutoff,
                IAPrediction.input_features.isnot(None),
            )
        )

        ref_rows    = (await db.execute(stmt_reference)).scalars().all()
        curr_rows   = (await db.execute(stmt_current)).scalars().all()

        n_ref  = len(ref_rows)
        n_curr = len(curr_rows)

        if n_ref < _MIN_SAMPLES or n_curr < _MIN_SAMPLES:
            logger.warning(
                f"Drift check skipped — insufficient data "
                f"(reference={n_ref}, current={n_curr}, min={_MIN_SAMPLES})"
            )
            return {
                "drift_detected": False,
                "drifted_features": [],
                "drift_score": 0.0,
                "n_reference": n_ref,
                "n_current": n_curr,
                "feature_drift_details": {},
                "checked_at": checked_at,
                "error": f"Insufficient data: reference={n_ref}, current={n_curr} (min={_MIN_SAMPLES})",
            }

        # ── Build DataFrames from stored input_features snapshots ────────────
        df_reference = pd.DataFrame([r.input_features for r in ref_rows])
        df_current   = pd.DataFrame([r.input_features for r in curr_rows])

        # Align columns — keep only features present in both windows
        common_cols = sorted(set(df_reference.columns) & set(df_current.columns))
        if not common_cols:
            return {
                "drift_detected": False,
                "drifted_features": [],
                "drift_score": 0.0,
                "n_reference": n_ref,
                "n_current": n_curr,
                "feature_drift_details": {},
                "checked_at": checked_at,
                "error": "No common feature columns between reference and current windows.",
            }

        df_reference = df_reference[common_cols].astype(float, errors="ignore")
        df_current   = df_current[common_cols].astype(float, errors="ignore")

        # ── Run Evidently DataDrift report ────────────────────────────────────
        from evidently import ColumnMapping
        from evidently.report import Report
        from evidently.metric_presets import DataDriftPreset

        column_mapping = ColumnMapping(numerical_features=common_cols)
        report = Report(metrics=[DataDriftPreset()])
        report.run(
            reference_data=df_reference,
            current_data=df_current,
            column_mapping=column_mapping,
        )

        result_dict = report.as_dict()
        drift_data  = result_dict["metrics"][0]["result"]

        feature_details: dict[str, float] = {}
        drifted_features: list[str] = []

        for col, col_result in drift_data.get("drift_by_columns", {}).items():
            score = float(col_result.get("drift_score", 0.0))
            feature_details[col] = score
            if col_result.get("drift_detected", False):
                drifted_features.append(col)

        drift_score = (
            sum(feature_details.values()) / len(feature_details)
            if feature_details
            else 0.0
        )
        drift_detected = drift_data.get("dataset_drift", False)

        logger.info(
            f"Drift report: detected={drift_detected}, "
            f"score={drift_score:.4f}, drifted_features={drifted_features}"
        )

        return {
            "drift_detected": drift_detected,
            "drifted_features": drifted_features,
            "drift_score": round(drift_score, 4),
            "n_reference": n_ref,
            "n_current": n_curr,
            "feature_drift_details": {k: round(v, 4) for k, v in feature_details.items()},
            "checked_at": checked_at,
            "error": None,
        }

    except Exception as exc:
        logger.error(f"Drift report generation failed: {exc}", exc_info=True)
        return {
            "drift_detected": False,
            "drifted_features": [],
            "drift_score": 0.0,
            "n_reference": 0,
            "n_current": 0,
            "feature_drift_details": {},
            "checked_at": checked_at,
            "error": str(exc),
        }
