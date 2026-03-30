"""
scripts/seed_e2e.py — E2E Test Data Seed
=========================================
Creates in the LOCAL database:
  1. A test user :  e2e.analyst@finaces.test  / E2eFinaCES2026!  (role=ANALYST)
  2. A PolicyVersion: "E2E-Test-Policy-v1" (active)
  3. A Bidder       : "Société de Test E2E SA"
  4. An EvaluationCase: market_reference="E2E-TEST-DOSSIER-001" (SINGLE, DRAFT)

IDEMPOTENT — safe to run multiple times, never deletes existing data.

Usage:
    cd finaces-api
    python -m scripts.seed_e2e
"""

import asyncio
import logging
import sys
from pathlib import Path
from uuid import uuid4

# ── Ensure project root is on sys.path ────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.db.models import User, Bidder, EvaluationCase, PolicyVersion
from app.schemas.enums import UserRole, CaseType, CaseStatus
from app.schemas.policy_schema import PolicyConfigurationSchema
from app.core.security import get_password_hash
from app.core.config import settings

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SEED-E2E] %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── E2E Constants — MUST match e2e/fixtures/test-data.ts ─────────────────────
E2E_USER_EMAIL = "e2e.analyst@finaces.test"
E2E_USER_PASSWORD = "E2eFinaCES2026!"
E2E_USER_FIRST_NAME = "E2E"
E2E_USER_LAST_NAME = "Analyst"

E2E_POLICY_LABEL = "E2E-Test-Policy-v1"

E2E_BIDDER_NAME = "Société de Test E2E SA"
E2E_BIDDER_LEGAL_FORM = "SA"
E2E_BIDDER_COUNTRY = "Morocco"
E2E_BIDDER_SECTOR = "BTP"

E2E_CASE_REFERENCE = "E2E-TEST-DOSSIER-001"
E2E_CASE_LABEL = "E2E Integration Test Case"
E2E_CASE_CONTRACT_VALUE = 5_000_000.0
E2E_CASE_CURRENCY = "USD"
E2E_CASE_DURATION_MONTHS = 24


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE CONNECTION
# ══════════════════════════════════════════════════════════════════════════════

def _get_db_url() -> str:
    """
    Returns the database URL.
    Uses DATABASE_URL from settings (which reads from .env or env vars).
    NEVER uses a test-only DB — this seed targets the local dev database.
    """
    url = settings.DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL is not configured. Check your .env file.")
    logger.info(f"Target database: {url.split('@')[-1]}")  # Log host+db only, not credentials
    return url


def _create_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(_get_db_url(), echo=False, future=True)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ══════════════════════════════════════════════════════════════════════════════
# SEED FUNCTIONS (each is idempotent)
# ══════════════════════════════════════════════════════════════════════════════

async def seed_user(session: AsyncSession) -> User:
    """Create the E2E ANALYST user if not already present."""
    result = await session.execute(
        select(User).where(User.email == E2E_USER_EMAIL)
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.info(f"✓ User already exists: {E2E_USER_EMAIL} (id={str(existing.id)[:8]}...)")
        return existing

    user = User(
        id=uuid4(),
        email=E2E_USER_EMAIL,
        hashed_password=get_password_hash(E2E_USER_PASSWORD),
        first_name=E2E_USER_FIRST_NAME,
        last_name=E2E_USER_LAST_NAME,
        role=UserRole.ANALYST,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    logger.info(f"✅ User created: {E2E_USER_EMAIL} (id={str(user.id)[:8]}...)")
    return user


async def seed_policy(session: AsyncSession) -> PolicyVersion:
    """
    Create and activate an E2E PolicyVersion if not already present.

    The config_json is built from PolicyConfigurationSchema defaults —
    this produces a fully valid policy without any hardcoding.
    """
    result = await session.execute(
        select(PolicyVersion).where(PolicyVersion.version_label == E2E_POLICY_LABEL)
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.info(f"✓ Policy already exists: '{E2E_POLICY_LABEL}' (id={str(existing.id)[:8]}...)")
        # Ensure it is still active
        if not existing.is_active:
            existing.is_active = 1
            logger.info("  → Re-activated.")
        return existing

    # Build a valid policy config from all Pydantic defaults
    policy_version_id = f"e2e-policy-{uuid4().hex[:8]}"
    config = PolicyConfigurationSchema(
        version_id=policy_version_id,
        version_label=E2E_POLICY_LABEL,
    ).model_dump(mode="json")

    # Deactivate any previously active policy
    active_result = await session.execute(
        select(PolicyVersion).where(PolicyVersion.is_active == 1)
    )
    active_policies = active_result.scalars().all()
    for p in active_policies:
        p.is_active = 0
        logger.info(f"  → Deactivated previous policy: {p.version_label}")

    policy = PolicyVersion(
        id=uuid4(),
        version_label=E2E_POLICY_LABEL,
        effective_date="2026-01-01",
        description="Auto-generated policy for E2E integration tests. Do not use in production.",
        config_json=config,
        is_active=1,
        created_by="seed_e2e",
    )
    session.add(policy)
    await session.flush()
    logger.info(f"✅ Policy created & activated: '{E2E_POLICY_LABEL}' (id={str(policy.id)[:8]}...)")
    return policy


async def seed_bidder(session: AsyncSession) -> Bidder:
    """Create the E2E test bidder if not already present."""
    result = await session.execute(
        select(Bidder).where(Bidder.name == E2E_BIDDER_NAME)
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.info(f"✓ Bidder already exists: '{E2E_BIDDER_NAME}' (id={str(existing.id)[:8]}...)")
        return existing

    bidder = Bidder(
        id=uuid4(),
        name=E2E_BIDDER_NAME,
        legal_form=E2E_BIDDER_LEGAL_FORM,
        country=E2E_BIDDER_COUNTRY,
        sector=E2E_BIDDER_SECTOR,
        contact_email=E2E_USER_EMAIL,
    )
    session.add(bidder)
    await session.flush()
    logger.info(f"✅ Bidder created: '{E2E_BIDDER_NAME}' (id={str(bidder.id)[:8]}...)")
    return bidder


async def seed_case(session: AsyncSession, bidder: Bidder, policy: PolicyVersion) -> EvaluationCase:
    """Create the E2E test evaluation case if not already present."""
    result = await session.execute(
        select(EvaluationCase).where(EvaluationCase.market_reference == E2E_CASE_REFERENCE)
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.info(
            f"✓ Case already exists: '{E2E_CASE_REFERENCE}' "
            f"(id={str(existing.id)[:8]}..., status={existing.status})"
        )
        return existing

    case = EvaluationCase(
        id=uuid4(),
        case_type=CaseType.SINGLE,
        bidder_id=bidder.id,
        policy_version_id=policy.id,
        market_reference=E2E_CASE_REFERENCE,
        market_object=E2E_CASE_LABEL,
        contract_value=E2E_CASE_CONTRACT_VALUE,
        contract_currency=E2E_CASE_CURRENCY,
        contract_duration_months=E2E_CASE_DURATION_MONTHS,
        status=CaseStatus.DRAFT,
    )
    session.add(case)
    await session.flush()
    logger.info(
        f"✅ Case created: '{E2E_CASE_REFERENCE}' (id={str(case.id)[:8]}..., status=DRAFT)"
    )
    return case


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

async def run_seed() -> None:
    logger.info("=" * 60)
    logger.info("FinaCES — E2E Seed")
    logger.info("=" * 60)

    session_factory = _create_session_factory()

    async with session_factory() as session:
        try:
            user = await seed_user(session)
            policy = await seed_policy(session)
            bidder = await seed_bidder(session)
            _case = await seed_case(session, bidder, policy)

            await session.commit()

            logger.info("")
            logger.info("=" * 60)
            logger.info("✅ E2E seed completed successfully.")
            logger.info("")
            logger.info("  Login credentials:")
            logger.info(f"    Email    : {E2E_USER_EMAIL}")
            logger.info(f"    Password : {E2E_USER_PASSWORD}")
            logger.info("")
            logger.info("  Test case:")
            logger.info(f"    Reference: {E2E_CASE_REFERENCE}")
            logger.info(f"    Case ID  : {str(_case.id)}")
            logger.info("=" * 60)

        except Exception as exc:
            await session.rollback()
            logger.error(f"❌ Seed failed: {exc}")
            raise


def main() -> None:
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
