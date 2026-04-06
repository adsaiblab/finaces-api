from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError, HTTPException as FastAPIHTTPException
import logging

from app.exceptions.finaces_exceptions import (
    FinaCESBaseException,
    MissingFinancialDataError,
    EngineComputationError,
    RateLimitExceededError,
)
from app.core.audit import security_rate_limit_hit

logger = logging.getLogger(__name__)

def add_exception_handlers(app: FastAPI) -> None:
    """
    Registers global exception handlers for the FastAPI application.
    This keeps the individual endpoint routers clean (DRY pattern).

    Handler declaration order matters: Starlette resolves exception handlers
    by MRO (most specific first). Specific subclass handlers MUST be declared
    before the FinaCESBaseException catchall.
    """

    # ── 429 Rate Limit — FinaCES explicit raise ───────────────────────────────
    # Catches RateLimitExceededError raised explicitly in application code.
    # Must be declared before the FinaCESBaseException catchall.
    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_exception_handler(request: Request, exc: RateLimitExceededError):
        logger.warning(f"429 - RateLimitExceededError: {exc.message} on {request.url.path}")
        security_rate_limit_hit(
            ip=request.client.host if request.client else "unknown",
            path=request.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": exc.message, "code": "RATE_LIMIT_EXCEEDED"},
        )

    # ── 429 Rate Limit — fastapi-limiter direct HTTPException ─────────────────
    # fastapi-limiter raises HTTPException(429) directly, bypassing FinaCES
    # exception classes. We intercept it here to attach the audit hook.
    # All other HTTPExceptions are re-raised transparently with their original
    # status code and detail.
    @app.exception_handler(FastAPIHTTPException)
    async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            security_rate_limit_hit(
                ip=request.client.host if request.client else "unknown",
                path=request.url.path,
            )
            logger.warning(f"429 - Rate limit hit (fastapi-limiter) on {request.url.path}")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(MissingFinancialDataError)
    async def missing_financial_data_exception_handler(request: Request, exc: MissingFinancialDataError):
        logger.warning(f"404 - MissingFinancialDataError: {exc.message} on path {request.url.path}")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": exc.message, "code": "MISSING_DATA"}
        )

    @app.exception_handler(EngineComputationError)
    async def engine_computation_exception_handler(request: Request, exc: EngineComputationError):
        logger.error(f"400 - EngineComputationError: {exc.message} on path {request.url.path}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": exc.message, "code": "COMPUTATION_ERROR", "metadata": exc.details}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning(f"422 - RequestValidationError on path {request.url.path}: {exc.errors()}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Payload structure validation failed.", "errors": exc.errors()}
        )

    @app.exception_handler(FinaCESBaseException)
    async def finaces_base_exception_handler(request: Request, exc: FinaCESBaseException):
        logger.warning(f"{exc.status_code} - FinaCESBaseException: {exc.message} on path {request.url.path}")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": "FINACES_ERROR"}
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"500 - Unhandled exception on path {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error."}
        )
