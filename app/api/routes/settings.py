"""
app/api/routes/settings.py — Policy Management
FinaCES V1.2 — Async Migration Sprint 2B

Business logic strictly preserved:
  - deep_merge()                  : recursive dict merge (UNCHANGED)
  - validate_fiduciary_integrity(): fiduciary guard (UNCHANGED)
Migrated to async: all policy_service calls are awaited.
"""

import copy
import traceback
import uuid
import json
import os
import logging
from typing import Optional, Dict, Any

import aiofiles

from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user, RequireRole
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.policy_service import (
    get_active_policy,
    list_all_policies,
    save_policy,
    activate_policy,
)
from app.services.audit_service import log_event
from app.exceptions.finaces_exceptions import PolicyNotLoadedError, FinaCESBaseException

logger = logging.getLogger(__name__)

# ── Constantes fiduciaires ─────────────────────────────────────
SACRED_KEYS = [
    "sector_benchmarks", "alert_thresholds", "risk_patterns",
    "consortium_rules", "scoring_grid", "scoring_weights",
]

router = APIRouter(tags=["Settings"])


# ════════════════════════════════════════════════════════════════
# PROFESSIONAL HELPERS (kept strictly identical)
# ════════════════════════════════════════════════════════════════

def validate_fiduciary_integrity(config: dict) -> None:
    """
    Verifies policy integrity before saving (Fiduciary Shield).
    Raises a 422 HTTPException if critical MCC rules are violated.
    """
    for key in SACRED_KEYS:
        if key not in config or not config[key]:
            raise HTTPException(
                status_code=422,
                detail=f"Fiduciary Integrity Compromised: Missing or empty sacred key '{key}'"
            )

    required_pillars = ["liquidite", "solvabilite", "rentabilite", "capacite"]
    weights = config.get("scoring_weights", {})
    for pillar in required_pillars:
        if pillar not in weights:
            raise HTTPException(
                status_code=422,
                detail=f"Fiduciary Integrity Compromised: Missing pillar '{pillar}' in scoring_weights"
            )


def deep_merge(dict1: dict, dict2: dict) -> dict:
    """
    Recursively merges dict2 into dict1.
    If both values are dicts, it merges them deeply.
    If the value is a list, dict2 overwrites dict1 without recursive merging.
    Otherwise, the value from dict2 overwrites dict1.
    """
    result = copy.deepcopy(dict1)
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif isinstance(value, list):
            result[key] = copy.deepcopy(value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# ── Diagrams ────────────────────────── ──────────────────────────
class PolicyCreate(BaseModel):
    version_label:  str
    effective_date: str
    description:    Optional[str] = ""
    config:         Dict[str, Any]


class GlobalSettings(BaseModel):
    theme:                 str = "light"
    language:              str = "fr"
    notifications_enabled: bool = True


# ── Global UI State (not persisted in DB, matching legacy behavior) ──
_global_settings: dict = {
    "theme":                 "light",
    "language":              "fr",
    "notifications_enabled": True,
}


# ════════════════════════════════════════════════════════════════
# ENDPOINTS — Global Settings
# ════════════════════════════════════════════════════════════════

@router.get("/settings")
def api_get_global_settings(current_user: dict = Depends(get_current_user)):
    """Returns the global user/system settings."""
    return _global_settings


@router.post("/settings")
def api_update_global_settings(payload: dict, current_user: dict = Depends(RequireRole(["ADMIN"]))):
    """Updates the global user settings."""
    global _global_settings
    _global_settings.update(payload)
    return {"status": "success", "settings": _global_settings}


# ════════════════════════════════════════════════════════════════
# ENDPOINTS — Policies
# ════════════════════════════════════════════════════════════════

@router.get("/policies")
async def api_list_policies(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Lists all policies."""
    return await list_all_policies(db=db)


@router.get("/policies/active")
async def api_get_active_policy(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Returns the active policy."""
    policy = await get_active_policy(db=db)
    return policy


@router.post("/policies")
async def api_create_policy(
    body: PolicyCreate,
    db:   AsyncSession = Depends(get_db),
    current_user: dict = Depends(RequireRole(["ADMIN"]))
):
    """Creates and activates a new policy by merging with the active or default policy."""
    try:
        # Failsafe au chargement
        try:
            current_policy = await get_active_policy(db=db)
        except PolicyNotLoadedError:
            current_policy = None

        if not current_policy:
            # Fallback: read the default_policy_v1.json file via aiofiles
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            policy_path = os.path.join(base_dir, "policies", "default_policy_v1.json")
            if os.path.exists(policy_path):
                async with aiofiles.open(policy_path, "r", encoding="utf-8") as f:
                    content = await f.read()
                current_policy = json.loads(content)
            else:
                current_policy = {}

        # Deep merge incoming config on top of current
        merged_config = deep_merge(current_policy, body.config)

        # Override metadata fields
        merged_config["version_id"]    = f"policy-{uuid.uuid4().hex[:8]}"
        merged_config["version_label"] = body.version_label
        merged_config["effective_date"] = body.effective_date
        merged_config["description"]   = body.description

        # Fiduciary gate (throws HTTPException 422 if invalid)
        validate_fiduciary_integrity(merged_config)

        policy_id = await save_policy(db=db, config=merged_config)

        await log_event(
            db=db,
            event_type="POLICY_CREATED",
            entity_type="PolicyVersion",
            entity_id=policy_id,
            description=f"Policy created: {body.version_label}",
            new_value={"version_label": body.version_label},
            user_id=current_user.get("sub", "SYSTEM"),
        )
        return {"policy_id": policy_id}

    except HTTPException:
        raise
    except FinaCESBaseException:
        raise
    except Exception as exc:
        logger.error(f"Error creating policy: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/policies/restore-default")
async def api_restore_default_policy(db: AsyncSession = Depends(get_db), current_user: dict = Depends(RequireRole(["ADMIN"]))):
    """Restores the default policy from the source file and activates it."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        policy_path = os.path.join(base_dir, "policies", "default_policy_v1.json")

        async with aiofiles.open(policy_path, "r", encoding="utf-8") as f:
            content = await f.read()
        default_config = json.loads(content)

        default_config["version_id"]    = f"policy-restored-{uuid.uuid4().hex[:8]}"
        default_config["version_label"] = "Default Restored"
        default_config["description"]   = "Emergency restoration"

        policy_id = await save_policy(db=db, config=default_config)
        await log_event(
            db=db,
            event_type="POLICY_LOADED",
            entity_type="PolicyVersion",
            entity_id=policy_id,
            description="Default policy restored and activated.",
            user_id=current_user.get("sub", "SYSTEM"),
        )
        return {"policy_id": policy_id, "status": "restored"}

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File default_policy_v1.json not found.")
    except HTTPException:
        raise
    except FinaCESBaseException:
        raise
    except Exception as exc:
        logger.error(f"Error restoring default policy: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/policies/{policy_id}/activate")
async def api_activate_policy(
    policy_id: str,
    db:        AsyncSession = Depends(get_db),
    current_user: dict = Depends(RequireRole(["ADMIN"]))
):
    """Activates an existing policy."""
    try:
        await activate_policy(db=db, policy_id=policy_id)
        await log_event(
            db=db,
            event_type="POLICY_LOADED",
            entity_type="PolicyVersion",
            entity_id=policy_id,
            description=f"Policy activated: {policy_id}",
            user_id=current_user.get("sub", "SYSTEM"),
        )
        return {"status": "ok"}
    except HTTPException:
        raise
    except FinaCESBaseException:
        raise
    except Exception as exc:
        logger.error(f"Error activating policy {policy_id}: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")
