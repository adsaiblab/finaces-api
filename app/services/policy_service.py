"""
app/services/policy_service.py
FinaCES V1.2 — Policy Facade (Async Migration Sprint 2B, P0-11 Fix)

Provides:
  - get_active_policy(db)   : Async — reads the active PolicyVersion from DB.
  - get_risk_class(...)     : Pure — maps a score to a risk class.
  - get_scoring_grid(...)   : Pure — extracts the scoring grid (Fail-Fast).
  - save_policy(...)        : Async — creates a new policy version.
  - activate_policy(...)    : Async — activates a policy and deactivates others.
"""

import json
import uuid
import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.db.models import PolicyVersion
from app.exceptions.finaces_exceptions import PolicyNotLoadedError
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# ACTIVE POLICY LOADING
# ════════════════════════════════════════════════════════════════

async def get_active_policy(db: AsyncSession) -> dict:
    """
    Returns the JSON configuration of the active PolicyVersion.

    The configuration is the Python dict derived from the JSONB column
    (SQLAlchemy deserializes it automatically).

    Raises:
        PolicyNotLoadedError — if no PolicyVersion is active in the database.
    """
    result = await db.execute(
        select(PolicyVersion).where(PolicyVersion.is_active == 1)
    )
    policy = result.scalars().first()

    if not policy:
        raise PolicyNotLoadedError(
            "No active PolicyVersion found in the database. "
            "Create and activate a policy before starting an evaluation."
        )

    # config_json is JSONB — already deserialized by SQLAlchemy
    config = policy.config_json
    if isinstance(config, str):
        # Safeguard: if ever stored as raw text
        config = json.loads(config)

    # Injects version ID for traceability
    config.setdefault("version_id", str(policy.id))
    config.setdefault("version_label", policy.version_label)
    config.setdefault("effective_date", policy.effective_date)

    logger.debug(f"Active policy loaded: {policy.version_label} ({policy.id})")
    return config


async def get_policy_by_id(db: AsyncSession, policy_id: str) -> dict:
    """Returns the JSON configuration of a PolicyVersion by its ID."""
    result = await db.execute(
        select(PolicyVersion).where(PolicyVersion.id == uuid.UUID(policy_id))
    )
    policy = result.scalars().first()
    if not policy:
        raise PolicyNotLoadedError(f"PolicyVersion not found: {policy_id}")
    config = policy.config_json
    if isinstance(config, str):
        config = json.loads(config)
    return config


async def list_all_policies(db: AsyncSession) -> list:
    """Returns a list of all PolicyVersions (without config_json)."""
    result = await db.execute(
        select(PolicyVersion).order_by(PolicyVersion.created_at.desc())
    )
    policies = result.scalars().all()
    return [
        {
            "id":              str(p.id),
            "version_label":   p.version_label,
            "effective_date":  p.effective_date,
            "description":     p.description,
            "is_active":       bool(p.is_active),
            "created_at":      p.created_at,
        }
        for p in policies
    ]


# ════════════════════════════════════════════════════════════════
# POLICY CRUD
# ════════════════════════════════════════════════════════════════

async def save_policy(db: AsyncSession, config: dict, user_id: str = "SYSTEM") -> str:
    """
    Creates a new policy version.
    Deactivates all previous versions atomically.
    Returns the new ID.
    """
    # 1. Deactivate all active policies
    await db.execute(
        update(PolicyVersion)
        .where(PolicyVersion.is_active == 1)
        .values(is_active=0)
    )

    new_id = uuid.UUID(config["version_id"]) if config.get("version_id") else uuid.uuid4()
    config["version_id"] = str(new_id)

    new_policy = PolicyVersion(
        id=new_id,
        version_label=config.get("version_label", "v1.0"),
        effective_date=config.get("effective_date", date.today().isoformat()),
        description=config.get("description"),
        config_json=config,
        is_active=1,
        created_by=user_id,
    )
    db.add(new_policy)
    await db.commit()
    logger.info(f"Policy saved: {new_policy.version_label} ({new_id})")
    
    # ─ Audit Trail (MCC-Grade Compliance) ─────────────────────
    await log_event(
        db=db,
        event_type="POLICY_VERSION_ACTIVATED",
        entity_type="PolicyVersion",
        entity_id=str(new_id),
        case_id=None,
        description=f"New policy version {new_policy.version_label} created and activated globally by {user_id}"
    )

    return str(new_id)


async def activate_policy(db: AsyncSession, policy_id: str) -> None:
    """
    Activates an existing PolicyVersion and deactivates all others.
    """
    result = await db.execute(
        select(PolicyVersion).where(PolicyVersion.id == uuid.UUID(policy_id))
    )
    target = result.scalars().first()
    if not target:
        raise PolicyNotLoadedError(f"PolicyVersion not found: {policy_id}")

    # Deactivate all
    await db.execute(
        update(PolicyVersion)
        .where(PolicyVersion.is_active == 1)
        .values(is_active=0)
    )
    # Activate target
    target.is_active = 1
    await db.commit()
    logger.info(f"Policy activated: {target.version_label} ({policy_id})")
    
    # ─ Audit Trail (MCC-Grade Compliance) ─────────────────────
    await log_event(
        db=db,
        event_type="POLICY_VERSION_ACTIVATED",
        entity_type="PolicyVersion",
        entity_id=str(policy_id),
        case_id=None,
        description=f"Policy version {target.version_label} activated globally"
    )


# ════════════════════════════════════════════════════════════════
# PURE HELPERS (SYNCHRONOUS — only read the policy dict)
# ════════════════════════════════════════════════════════════════

def get_risk_class(score: float, policy: dict) -> str:
    """
    Maps a global score (0.0 – 5.0) to a risk class.
    Uses policy["risk_thresholds"] if available,
    otherwise falls back to standard IFRS bands.
    Evaluation order: LOW → MODERATE → HIGH → CRITICAL.
    """
    thresholds = policy.get("risk_thresholds", {})

    for risk_class in ["LOW", "MODERATE", "HIGH", "CRITICAL"]:
        band = thresholds.get(risk_class, {})
        band_min = float(band.get("min", 0))
        band_max = float(band.get("max", 5))
        if band_min <= score <= band_max:
            return risk_class

    # Standard IFRS fallback if thresholds missing or incomplete
    if score >= 4.0:
        return "LOW"
    elif score >= 3.0:
        return "MODERATE"
    elif score >= 2.0:
        return "HIGH"
    else:
        return "CRITICAL"


def get_scoring_grid(policy: dict) -> dict:
    """
    Returns the ratio-to-score conversion grid.
    MAJ-03: Strict Fail-Fast — raises PolicyNotLoadedError if missing.
    """
    grid = policy.get("scoring_grid")
    if not grid:
        raise PolicyNotLoadedError(
            "Missing Policy Configuration: The scoring grid (scoring_grid) "
            "is not configured in the active policy. Evaluation cannot proceed."
        )
    return grid


def get_scoring_weights(policy: dict, pillar: str, default: float = 0.20) -> float:
    """Returns the weight of a pillar from policy['scoring_weights']."""
    weights = policy.get("scoring_weights", {})
    return float(weights.get(pillar, default))


def get_recommendation_thresholds(policy: dict) -> dict:
    """Returns trigger thresholds for conditional recommendations."""
    return policy.get("recommendation_thresholds", {
        "capacity_warning":    2.5,
        "liquidity_warning":   2.0,
        "solvency_warning":    2.0,
    })
