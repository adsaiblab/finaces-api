"""
app/core/logging_config.py — Structured audit logger configuration.

Provides a dedicated 'audit' logger that writes JSON events to logs/audit.log,
one JSON object per line — ready for SIEM ingestion or grep-based monitoring.

Usage:
    from app.core.logging_config import configure_audit_logger
    configure_audit_logger()  # called once from lifespan

    from app.core.audit import auth_login_success  # then use emitters
"""

import logging
import logging.handlers
import os

_AUDIT_LOGGER_NAME = "audit"
_LOG_DIR = "logs"
_AUDIT_LOG_FILE = os.path.join(_LOG_DIR, "audit.log")

_audit_logger_configured = False


def configure_audit_logger() -> None:
    """
    Idempotent setup of the 'audit' logger.
    Called once from lifespan in app/main.py.
    Safe to call multiple times (re-entrant guard via module-level flag).
    """
    global _audit_logger_configured
    if _audit_logger_configured:
        return

    os.makedirs(_LOG_DIR, exist_ok=True)

    logger = logging.getLogger(_AUDIT_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    # Never propagate to root logger — audit events must not leak to stdout
    logger.propagate = False

    # RotatingFileHandler: 10 MB per file, 5 backups → max 50 MB audit trail
    handler = logging.handlers.RotatingFileHandler(
        _AUDIT_LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    # Raw formatter: each record.message IS the JSON line — no timestamp prefix,
    # no level prefix. The JSON payload carries its own `timestamp` field.
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    _audit_logger_configured = True
