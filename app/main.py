from fastapi import FastAPI, APIRouter, Depends
from fastapi.middleware.cors import CORSMiddleware
import logging
import os
from contextlib import asynccontextmanager
from redis.asyncio import Redis
from fastapi_limiter import FastAPILimiter

from app.core.security import get_current_user

from app.api.routes import normalization
from app.api.routes import ratios
from app.api.routes import scoring
from app.api.routes import gate
from app.api.routes import consortium
from app.api.routes import stress
from app.api.routes import experts
from app.api.routes import cases
from app.api.routes import financials
from app.api.routes import documents
from app.api.routes import export
from app.api.routes import dashboard
from app.api.routes import system
from app.api.routes import settings
from app.api.routes import audit
from app.api.routes import comparison
from app.api.routes import report
from app.api.routes import ia
from app.api import auth
from app.api.exception_handlers import add_exception_handlers

# Logger config setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connecting to Redis at startup (uses docker-compose URL)
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    await FastAPILimiter.init(redis)
    yield
    # Clean closing when stopped
    await redis.close()

def create_app() -> FastAPI:
    """
    FastAPI application factory — enforces modularity and core server isolation.
    """
    app = FastAPI(
        title="FinaCES API MCC",
        version="1.2.0",
        description="IFRS-compliant Async Financial Evaluation Engine",
        lifespan=lifespan  # <-- AJOUT DU CYCLE DE VIE REDIS
    )

    # 1. Configure middleware (CORS) - Secure (P2-04)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:4200", "http://localhost:8000"],  # WARNING: To be restricted in staging/production
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], # <-- FIXED: wild card removed
        allow_headers=["Authorization", "Content-Type", "Accept"],          # <-- FIXED: limited to what is strictly necessary (JWT, JSON)
    )

    # 2. Register global exception handlers
    add_exception_handlers(app)

    # 3. Public routes (no JWT required)
    app.include_router(auth.router)

    # 4. Aggregate protected routers under /api/v1
    api_v1_router = APIRouter(prefix="/api/v1")
    
    # Mount validated routers
    api_v1_router.include_router(normalization.router)
    api_v1_router.include_router(ratios.router)
    api_v1_router.include_router(gate.router)
    api_v1_router.include_router(scoring.router)
    api_v1_router.include_router(consortium.router)
    api_v1_router.include_router(stress.router)
    api_v1_router.include_router(experts.router)
    api_v1_router.include_router(cases.router)
    api_v1_router.include_router(financials.router)
    api_v1_router.include_router(documents.router)
    api_v1_router.include_router(export.router)
    api_v1_router.include_router(dashboard.router)
    api_v1_router.include_router(system.router)
    api_v1_router.include_router(settings.router)
    api_v1_router.include_router(audit.router)
    api_v1_router.include_router(comparison.router)
    api_v1_router.include_router(report.router)
    api_v1_router.include_router(ia.router)
    
    # Master registration
    app.include_router(api_v1_router)

    # 4. Route Healthcheck
    @app.get("/health", tags=["System"])
    async def health_check():
        return {"status": "OK", "version": app.version}

    return app

# Gunicorn / Uvicorn entrypoint explicit
app = create_app()
