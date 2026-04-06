from fastapi import FastAPI, APIRouter, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import logging
import os
import secrets
from contextlib import asynccontextmanager
from redis.asyncio import Redis
from fastapi_limiter import FastAPILimiter

from app.core.security import get_current_user
from app.core.config import settings

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
from app.api.routes import settings as settings_router
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


# ── XSRF Middleware ────────────────────────────────────────────────────────────
# The API is stateless JWT-Bearer: CSRF via session cookie is NOT a direct risk.
# We still implement the XSRF-TOKEN cookie pattern for defense-in-depth and to
# satisfy Angular's built-in withXsrfConfiguration() mechanism.
#
# Strategy:
#   - Every GET response sets a fresh XSRF-TOKEN cookie (SameSite=Strict,
#     HttpOnly=False so Angular JS can read it).
#   - Every mutation (POST / PUT / PATCH / DELETE) must echo the token in the
#     X-XSRF-TOKEN request header. Mismatch → 403.
#   - OPTIONS (CORS preflight) is always let through without token check.
#   - `secure` flag is driven by settings.ENVIRONMENT at app startup:
#     automatically True in production/staging, False in development.
# ──────────────────────────────────────────────────────────────────────────────
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_COOKIE_NAME  = "XSRF-TOKEN"
_HEADER_NAME  = "X-XSRF-TOKEN"


class XSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secure: bool = False):
        super().__init__(app)
        self.secure = secure

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in _SAFE_METHODS:
            cookie_token = request.cookies.get(_COOKIE_NAME, "")
            header_token = request.headers.get(_HEADER_NAME, "")
            if not cookie_token or not secrets.compare_digest(cookie_token, header_token):
                return Response(
                    content='{"detail":"XSRF token missing or invalid."}',
                    status_code=403,
                    media_type="application/json",
                )
        response = await call_next(request)
        if request.method == "GET":
            token = secrets.token_hex(32)
            response.set_cookie(
                key=_COOKIE_NAME,
                value=token,
                httponly=False,       # Angular JS must read it to inject X-XSRF-TOKEN
                samesite="strict",
                secure=self.secure,   # True in production/staging — driven by ENVIRONMENT
            )
        return response


# ── Security Headers Middleware ───────────────────────────────────────────────
# Injects hardening headers on every response.
#
# Design decisions:
#   - Strict-Transport-Security: production only. In local HTTP it would lock
#     the browser to HTTPS for 31536000 seconds — very hard to revert.
#     NOTE: `preload` is intentionally omitted. It submits the domain to the
#     HSTS Preload List (Chrome/Firefox), which is irreversible for months and
#     requires a manual submission to hstspreload.org. Add it in Phase 3 once
#     the production domain is stable and the team has validated the decision.
#   - Content-Security-Policy:
#       • /docs and /redoc serve Swagger UI (CDN assets, inline scripts/styles).
#         A strict CSP would break them. We apply a Swagger-safe CSP on those
#         paths only — and only in non-production environments (see create_app()).
#       • All other paths get default-src 'none' — the API serves JSON only.
#   - X-Frame-Options: redundant with CSP frame-ancestors but kept for legacy
#     browser compatibility (IE11, older Safari).
# ──────────────────────────────────────────────────────────────────────────────
_DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}

# Swagger UI needs: CDN scripts/styles + inline execution + data: worker blobs
_CSP_SWAGGER = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "worker-src blob:;"
)

# Pure JSON API — nothing should load or execute
_CSP_API = "default-src 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, is_production: bool = False):
        super().__init__(app)
        self.is_production = is_production

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # MIME sniffing protection
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Clickjacking protection (legacy browsers — modern ones use CSP frame-ancestors)
        response.headers["X-Frame-Options"] = "DENY"

        # Referrer leak mitigation
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Disable unused browser APIs
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()"
        )

        # HSTS — production only (would permanently break local HTTP dev if set globally).
        # `preload` deliberately omitted — requires explicit submission to hstspreload.org.
        if self.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # CSP — permissive on /docs & /redoc (dev/staging only, disabled in prod),
        # strict default-src 'none' on all API routes.
        path = request.url.path
        if any(path.startswith(doc) for doc in _DOCS_PATHS):
            response.headers["Content-Security-Policy"] = _CSP_SWAGGER
        else:
            response.headers["Content-Security-Policy"] = _CSP_API

        return response


def create_app() -> FastAPI:
    """
    FastAPI application factory — enforces modularity and core server isolation.
    """
    is_production = settings.ENVIRONMENT == "production"

    # Disable /docs and /redoc in production — full API schema is a reconnaissance
    # vector. In development and staging they remain accessible normally.
    docs_url  = None if is_production else "/docs"
    redoc_url = None if is_production else "/redoc"

    app = FastAPI(
        title="FinaCES API MCC",
        version="1.2.0",
        description="IFRS-compliant Async Financial Evaluation Engine",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
    )

    # 1. Configure middleware (CORS) - Secure (P2-04)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:4200", "http://localhost:8000"],  # WARNING: To be restricted in staging/production
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],  # <-- FIXED: wild card removed
        allow_headers=["Authorization", "Content-Type", "Accept", "X-XSRF-TOKEN"],  # <-- P2-05: X-XSRF-TOKEN added for XSRF protection
    )

    # XSRF protection (defense-in-depth — JWT Bearer is the primary auth mechanism).
    # secure flag auto-activates Secure=True cookie when ENVIRONMENT=production or staging.
    app.add_middleware(XSRFMiddleware, secure=settings.ENVIRONMENT in ("production", "staging"))

    # Security response headers (HSTS active in production only).
    # Middleware execution order (Starlette reverses declaration order):
    #   Request:  CORSMiddleware → XSRFMiddleware → SecurityHeadersMiddleware → route
    #   Response: route → SecurityHeadersMiddleware → XSRFMiddleware → CORSMiddleware
    app.add_middleware(
        SecurityHeadersMiddleware,
        is_production=is_production,
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
    api_v1_router.include_router(settings_router.router)
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
