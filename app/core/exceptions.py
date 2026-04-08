"""
app/core/exceptions.py — FinaCES domain exceptions
FinaCES V1.2 — Async Migration Sprint 2B
"""

from fastapi import HTTPException


class FinaCESBaseException(HTTPException):
    """
    Base exception for all FinaCES domain errors.

    Inherits from HTTPException so FastAPI can handle it natively
    and route handlers peuvent la re-raise directement sans wrapper.

    Usage:
        raise FinaCESBaseException(status_code=400, detail="Business rule violated")
    """

    def __init__(self, status_code: int = 500, detail: str = "An internal error occurred."):
        super().__init__(status_code=status_code, detail=detail)


class CaseNotFoundException(FinaCESBaseException):
    """Raised when a case_id does not exist in the database."""

    def __init__(self, case_id: str):
        super().__init__(status_code=404, detail=f"Case '{case_id}' not found.")


class PolicyNotFoundException(FinaCESBaseException):
    """Raised when no active scoring policy is found."""

    def __init__(self):
        super().__init__(status_code=404, detail="No active scoring policy found.")


class ReportNotFoundException(FinaCESBaseException):
    """Raised when a report_id does not exist."""

    def __init__(self, report_id: str):
        super().__init__(status_code=404, detail=f"Report '{report_id}' not found.")


class ReportAlreadyFinalizedException(FinaCESBaseException):
    """Raised when trying to modify a report that is already FINAL."""

    def __init__(self, report_id: str):
        super().__init__(
            status_code=409,
            detail=f"Report '{report_id}' is already finalized and cannot be modified.",
        )


class UnauthorizedAccessException(FinaCESBaseException):
    """Raised when a user attempts an action beyond their role."""

    def __init__(self, detail: str = "Insufficient permissions."):
        super().__init__(status_code=403, detail=detail)