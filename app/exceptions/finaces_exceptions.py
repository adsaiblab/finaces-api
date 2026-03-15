from typing import Any, Dict, Optional

class FinaCESBaseException(Exception):
    """Base exception for all FinaCES application exceptions."""
    def __init__(self, message: str, status_code: int = 500, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}

class DatabaseConnectionError(FinaCESBaseException):
    def __init__(self, message: str = "Database connection failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 503, details)

class EntityNotFoundError(FinaCESBaseException):
    def __init__(self, message: str = "Requested entity not found", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 404, details)

class CaseNotFoundError(FinaCESBaseException):
    def __init__(self, message: str = "Evaluation case not found", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 404, details)

class EngineComputationError(FinaCESBaseException):
    def __init__(self, message: str = "Error occurred during financial computation", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 422, details)

class MissingFinancialDataError(FinaCESBaseException):
    def __init__(self, message: str = "Missing financial data required for computation", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 422, details)

class InsufficientFiscalYearsError(FinaCESBaseException):
    def __init__(self, message: str = "Insufficient number of fiscal years for analysis", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 422, details)

class InvalidRatioError(FinaCESBaseException):
    def __init__(self, message: str = "Invalid financial ratio provided", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 400, details)

class ConsortiumRuleError(FinaCESBaseException):
    def __init__(self, message: str = "Consortium rule evaluation failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 409, details)

class ModelNotFoundError(FinaCESBaseException):
    def __init__(self, message: str = "Active AI model not found", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 404, details)

class AuthenticationError(FinaCESBaseException):
    def __init__(self, message: str = "Authentication failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 401, details)

class TokenExpiredError(FinaCESBaseException):
    def __init__(self, message: str = "Authentication token has expired", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 401, details)

class AuthorizationError(FinaCESBaseException):
    def __init__(self, message: str = "Insufficient permissions", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 403, details)

class ValidationFailedError(FinaCESBaseException):
    def __init__(self, message: str = "Data validation failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 400, details)

class FileUploadError(FinaCESBaseException):
    def __init__(self, message: str = "Failed to upload file", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 400, details)

class ExportGenerationError(FinaCESBaseException):
    def __init__(self, message: str = "Failed to generate export file", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 500, details)

class ConfigurationError(FinaCESBaseException):
    def __init__(self, message: str = "System configuration error", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 500, details)

class ExternalServiceError(FinaCESBaseException):
    def __init__(self, message: str = "External service is unreachable or returned an error", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 502, details)

class RateLimitExceededError(FinaCESBaseException):
    def __init__(self, message: str = "Rate limit exceeded", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 429, details)

class PolicyNotLoadedError(FinaCESBaseException):
    """Raised when no active PolicyVersion is found in the database,
    or when the scoring_grid configuration is missing from the active policy."""
    def __init__(self, message: str = "No active policy configuration found. Cannot proceed with evaluation.", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 503, details)

class InvalidStateTransitionError(FinaCESBaseException):
    """Raised when a requested status transition is not allowed by the state machine."""
    def __init__(self, message: str = "Invalid state transition", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 400, details)
