"""
app/core/audit.py — Audit event emitter.

Single entry-point for all security audit events.
Enforces:
  - Strict field schema per event type
  - No sensitive data (no passwords, no full JWTs, no financial payload)
  - Fire-and-forget: exceptions are swallowed silently — audit log failure
    must NEVER crash or delay the request.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

_AUDIT = logging.getLogger("audit")


def _emit(event: str, **fields) -> None:
    """Internal: serialize and emit one JSON audit line. Never raises."""
    try:
        record = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        _AUDIT.info(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass  # Audit write failure must not affect request lifecycle


# ── Auth events ───────────────────────────────────────────────────────────────

def auth_login_success(*, user_email: str, ip: str) -> None:
    _emit("auth.login.success", user_email=user_email, ip=ip)


def auth_login_failure(*, attempted_email: str, ip: str, reason: str) -> None:
    """
    reason values: 'user_not_found' | 'invalid_password' | 'inactive_user'
    NOTE: HTTP response is identical in all cases — no username enumeration leak.
    Only the audit log sees the distinction.
    """
    _emit("auth.login.failure", attempted_email=attempted_email, ip=ip, reason=reason)


def auth_token_invalid(*, ip: str, reason: str, path: Optional[str] = None) -> None:
    """reason values: 'token_expired' | 'token_invalid_signature' | 'token_missing_sub'"""
    _emit("auth.token.invalid", ip=ip, reason=reason, path=path)


def auth_authorization_denied(
    *, user_email: str, ip: str, path: str, required_roles: list
) -> None:
    _emit(
        "auth.authorization.denied",
        user_email=user_email,
        ip=ip,
        path=path,
        required_roles=required_roles,
    )


# ── Security events ───────────────────────────────────────────────────────────

def security_rate_limit_hit(*, ip: str, path: str) -> None:
    _emit("security.rate_limit_hit", ip=ip, path=path)


def security_xsrf_blocked(*, ip: str, path: str, method: str) -> None:
    _emit("security.xsrf_blocked", ip=ip, path=path, method=method)


# ── Data access events ────────────────────────────────────────────────────────

def data_access_sensitive(
    *, user_email: str, path: str, case_id: Optional[str] = None
) -> None:
    _emit("data.access.sensitive", user_email=user_email, path=path, case_id=case_id)
