
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging

from app.exceptions.finaces_exceptions import (
    FinaCESBaseException,
    MissingFinancialDataError,
    EngineComputationError,
)

logger = logging.getLogger(__name__)

def add_exception_handlers(app: FastAPI) -> None:
    """
    Registers global exception handlers for the FastAPI application.
    This keeps the individual endpoint routers clean (DRY pattern).
    """

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
