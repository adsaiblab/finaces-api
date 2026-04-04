"""
scripts/seed_e2e.py — E2E Test Data Seed
=========================================
Crée dans la base locale dans l'ordre exact requis par les specs E2E :

  1.  User ANALYST         (e2e.analyst@finaces.test / E2eFinaCES2026!)
  2.  PolicyVersion        (E2E-Test-Policy-v1, is_active=1)
  3.  Bidder               (Société de Test E2E SA)
  4.  EvaluationCase       (market_reference=E2E-TEST-DOSSIER-001, status=IN_ANALYSIS)
  5.  FinancialStatementRaw x2  (fiscal_year 2022 + 2023)
  6.  process_normalization()   → FinancialStatementNormalized x2
  7.  process_ratios()          → RatioSet x2
  8.  GateResult               (is_gate_blocking=False, reliability_score=4.0)
  9.  process_scoring()         → Scorecard
  10. IAPrediction             (ia_score=72.5, ia_risk_class=MODERATE)
  11. IAModel                  (model_name=XGBoost Risk Classifier, is_active=True)

IDEMPOTENT — sûr à relancer plusieurs fois, ne supprime pas les données existantes.
À la fin, loggue :  E2E_CASE_ID=<uuid>  pour que global-setup.ts puisse le lire.

Usage:
    cd finaces-api
    python -m scripts.seed_e2e
"""

import asyncio
import logging
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

# ── Ensure project root is on sys.path ────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.db.models import (
    User,
    Bidder,
    EvaluationCase,
    PolicyVersion,
    FinancialStatementRaw,
    GateResult,
    IAPrediction,
    IAModel,  # Migration confirmée ✅ abe7f8b87247_add_ia_module_tables.py
)
from app.schemas.enums import UserRole, CaseType, CaseStatus
from app.schemas.policy_schema import PolicyConfigurationSchema
from app.core.security import get_password_hash
from app.core.config import settings

# Services de pipeline
from app.services.normalization_service import process_normalization
from app.services.ratio_service import process_ratios
from app.services.scoring_service import process_scoring

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SEED-E2E] %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# E2E CONSTANTS — doivent correspondre exactement à e2e/fixtures/test-data.ts
# ══════════════════════════════════════════════════════════════════════════════

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
E2E_CASE_CONTRACT_VALUE = Decimal("5000000.00")
E2E_CASE_CURRENCY = "USD"
E2E_CASE_DURATION_MONTHS = 24

# IA stub
E2E_IA_MODEL_VERSION = "e2e-stub-v1.0"
E2E_IA_SCORE = 72.5
E2E_IA_PROBA = 0.18
E2E_IA_RISK_CLASS = "MODERATE"


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE CONNECTION
# ══════════════════════════════════════════════════════════════════════════════

def _get_db_url() -> str:
    url = settings.DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL is not configured. Check your .env file.")
    logger.info(f"Target database: {url.split('@')[-1]}")
    return url


def _create_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(_get_db_url(), echo=False, future=True)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — USER
# ══════════════════════════════════════════════════════════════════════════════

async def seed_user(session: AsyncSession) -> User:
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


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — POLICY VERSION
# ══════════════════════════════════════════════════════════════════════════════

async def seed_policy(session: AsyncSession) -> PolicyVersion:
    result = await session.execute(
        select(PolicyVersion).where(PolicyVersion.version_label == E2E_POLICY_LABEL)
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.info(f"✓ Policy already exists: '{E2E_POLICY_LABEL}' (id={str(existing.id)[:8]}...)")
        if not existing.is_active:
            existing.is_active = 1
            logger.info("  → Re-activated.")
        return existing

    policy_version_id = f"e2e-policy-{uuid4().hex[:8]}"
    config = PolicyConfigurationSchema(
        version_id=policy_version_id,
        version_label=E2E_POLICY_LABEL,
    ).model_dump(mode="json")

    # Désactiver toute policy précédemment active
    active_result = await session.execute(
        select(PolicyVersion).where(PolicyVersion.is_active == 1)
    )
    for p in active_result.scalars().all():
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


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — BIDDER
# ══════════════════════════════════════════════════════════════════════════════

async def seed_bidder(session: AsyncSession) -> Bidder:
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


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — EVALUATION CASE  (status = IN_ANALYSIS, pas DRAFT)
# ══════════════════════════════════════════════════════════════════════════════

async def seed_case(
    session: AsyncSession,
    bidder: Bidder,
    policy: PolicyVersion,
) -> EvaluationCase:
    result = await session.execute(
        select(EvaluationCase).where(
            EvaluationCase.market_reference == E2E_CASE_REFERENCE
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.info(
            f"✓ Case already exists: '{E2E_CASE_REFERENCE}' "
            f"(id={str(existing.id)[:8]}..., status={existing.status})"
        )
        if existing.status == CaseStatus.DRAFT:
            existing.status = CaseStatus.IN_ANALYSIS
            logger.info("  → Status upgraded: DRAFT → IN_ANALYSIS")
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
        status=CaseStatus.IN_ANALYSIS,
    )
    session.add(case)
    await session.flush()
    logger.info(
        f"✅ Case created: '{E2E_CASE_REFERENCE}' "
        f"(id={str(case.id)[:8]}..., status=IN_ANALYSIS)"
    )
    return case


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — FINANCIAL STATEMENTS RAW (2022 + 2023)
# ══════════════════════════════════════════════════════════════════════════════

_FINANCIAL_DATA = {
    2022: dict(
        total_assets=Decimal("12_500_000.00"),
        current_assets=Decimal("4_800_000.00"),
        liquid_assets=Decimal("1_200_000.00"),
        inventory=Decimal("1_600_000.00"),
        accounts_receivable=Decimal("2_000_000.00"),
        non_current_assets=Decimal("7_700_000.00"),
        tangible_assets=Decimal("6_500_000.00"),
        intangible_assets=Decimal("1_200_000.00"),
        total_liabilities_and_equity=Decimal("12_500_000.00"),
        equity=Decimal("5_000_000.00"),
        share_capital=Decimal("3_000_000.00"),
        reserves=Decimal("1_200_000.00"),
        current_year_earnings=Decimal("800_000.00"),
        non_current_liabilities=Decimal("3_500_000.00"),
        long_term_debt=Decimal("3_000_000.00"),
        current_liabilities=Decimal("4_000_000.00"),
        short_term_debt=Decimal("1_000_000.00"),
        accounts_payable=Decimal("1_800_000.00"),
        revenue=Decimal("9_500_000.00"),
        cost_of_goods_sold=Decimal("6_200_000.00"),
        personnel_expenses=Decimal("1_500_000.00"),
        depreciation_and_amortization=Decimal("400_000.00"),
        operating_income=Decimal("1_400_000.00"),
        financial_expenses=Decimal("300_000.00"),
        income_before_tax=Decimal("1_100_000.00"),
        income_tax=Decimal("300_000.00"),
        net_income=Decimal("800_000.00"),
        ebitda=Decimal("1_800_000.00"),
        operating_cash_flow=Decimal("1_200_000.00"),
        investing_cash_flow=Decimal("-600_000.00"),
        financing_cash_flow=Decimal("-300_000.00"),
    ),
    2023: dict(
        total_assets=Decimal("14_200_000.00"),
        current_assets=Decimal("5_500_000.00"),
        liquid_assets=Decimal("1_500_000.00"),
        inventory=Decimal("1_800_000.00"),
        accounts_receivable=Decimal("2_200_000.00"),
        non_current_assets=Decimal("8_700_000.00"),
        tangible_assets=Decimal("7_300_000.00"),
        intangible_assets=Decimal("1_400_000.00"),
        total_liabilities_and_equity=Decimal("14_200_000.00"),
        equity=Decimal("5_900_000.00"),
        share_capital=Decimal("3_000_000.00"),
        reserves=Decimal("1_600_000.00"),
        current_year_earnings=Decimal("1_300_000.00"),
        non_current_liabilities=Decimal("3_800_000.00"),
        long_term_debt=Decimal("3_200_000.00"),
        current_liabilities=Decimal("4_500_000.00"),
        short_term_debt=Decimal("1_200_000.00"),
        accounts_payable=Decimal("2_000_000.00"),
        revenue=Decimal("11_200_000.00"),
        cost_of_goods_sold=Decimal("7_100_000.00"),
        personnel_expenses=Decimal("1_700_000.00"),
        depreciation_and_amortization=Decimal("450_000.00"),
        operating_income=Decimal("1_950_000.00"),
        financial_expenses=Decimal("320_000.00"),
        income_before_tax=Decimal("1_630_000.00"),
        income_tax=Decimal("330_000.00"),
        net_income=Decimal("1_300_000.00"),
        ebitda=Decimal("2_400_000.00"),
        operating_cash_flow=Decimal("1_700_000.00"),
        investing_cash_flow=Decimal("-800_000.00"),
        financing_cash_flow=Decimal("-400_000.00"),
    ),
}


async def seed_financials(
    session: AsyncSession,
    case: EvaluationCase,
) -> list[FinancialStatementRaw]:
    raws: list[FinancialStatementRaw] = []

    for year, data in _FINANCIAL_DATA.items():
        result = await session.execute(
            select(FinancialStatementRaw).where(
                FinancialStatementRaw.case_id == case.id,
                FinancialStatementRaw.fiscal_year == year,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            logger.info(f"✓ FinancialStatementRaw already exists: year={year}")
            raws.append(existing)
            continue

        raw = FinancialStatementRaw(
            id=uuid4(),
            case_id=case.id,
            fiscal_year=year,
            currency_original="USD",
            exchange_rate_to_usd=Decimal("1.0"),
            **data,
        )
        session.add(raw)
        await session.flush()
        logger.info(f"✅ FinancialStatementRaw created: year={year} (id={str(raw.id)[:8]}...)")
        raws.append(raw)

    return raws


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — GATE RESULT
# ══════════════════════════════════════════════════════════════════════════════

async def seed_gate_result(
    session: AsyncSession,
    case: EvaluationCase,
) -> GateResult:
    result = await session.execute(
        select(GateResult).where(GateResult.case_id == case.id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.info(f"✓ GateResult already exists for case {str(case.id)[:8]}...")
        return existing

    gate = GateResult(
        id=uuid4(),
        case_id=case.id,
        is_gate_blocking=False,
        blocking_reasons_json=[],
        is_passed=True,
        verdict="PASS",
        reliability_level="HIGH",
        reliability_score=Decimal("4.0"),
        missing_mandatory_json=[],
        missing_optional_json=[],
        reserve_flags_json=[],
    )
    session.add(gate)
    await session.flush()
    logger.info("✅ GateResult created: is_passed=True, reliability_score=4.0")
    return gate


# ══════════════════════════════════════════════════════════════════════════════
# STEP 10 — IA PREDICTION
# ══════════════════════════════════════════════════════════════════════════════

async def seed_ia_prediction(
    session: AsyncSession,
    case: EvaluationCase,
) -> IAPrediction:
    result = await session.execute(
        select(IAPrediction)
        .where(IAPrediction.case_id == case.id)
        .order_by(IAPrediction.created_at.desc())
    )
    existing = result.scalars().first()

    if existing:
        logger.info(
            f"✓ IAPrediction already exists for case {str(case.id)[:8]}... "
            f"(risk={existing.ia_risk_class}, score={existing.ia_score})"
        )
        return existing

    prediction = IAPrediction(
        id=uuid4(),
        case_id=case.id,
        ia_score=E2E_IA_SCORE,
        ia_probability_default=E2E_IA_PROBA,
        ia_risk_class=E2E_IA_RISK_CLASS,
        model_version=E2E_IA_MODEL_VERSION,
    )
    session.add(prediction)
    await session.flush()
    logger.info(
        f"✅ IAPrediction created: risk={E2E_IA_RISK_CLASS}, "
        f"score={E2E_IA_SCORE}, proba={E2E_IA_PROBA} "
        f"(id={str(prediction.id)[:8]}...)"
    )
    return prediction


# ══════════════════════════════════════════════════════════════════════════════
# STEP 11 — IA MODEL (stub)
# ══════════════════════════════════════════════════════════════════════════════

async def seed_ia_model(session: AsyncSession) -> None:
    result = await session.execute(
        select(IAModel).where(IAModel.is_active == True)
    )
    existing = result.scalars().first()

    if existing:
        logger.info(
            f"✓ IAModel already exists: '{existing.model_name}' v{existing.version} "
            f"(id={str(existing.id)[:8]}...)"
        )
        return

    model = IAModel(
        id=uuid4(),
        model_name="XGBoost Risk Classifier",
        version=E2E_IA_MODEL_VERSION,
        file_path="/dev/null",
        metrics={
            "auc_roc": 0.89,
            "accuracy": 0.85,
            "f1_score": 0.82,
        },
        is_active=True,
    )
    session.add(model)
    await session.flush()
    logger.info(
        f"✅ IAModel (stub) created: 'XGBoost Risk Classifier' v{E2E_IA_MODEL_VERSION} "
        f"(id={str(model.id)[:8]}...)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN — PIPELINE COMPLET DANS L'ORDRE EXACT
# ══════════════════════════════════════════════════════════════════════════════

async def run_seed() -> None:
    logger.info("=" * 70)
    logger.info("FinaCES — E2E Seed (pipeline complet)")
    logger.info("=" * 70)

    session_factory = _create_session_factory()

    async with session_factory() as session:
        try:
            # ── 1-4 : Entités de base ─────────────────────────────────────────
            _user = await seed_user(session)
            _policy = await seed_policy(session)
            _bidder = await seed_bidder(session)
            _case = await seed_case(session, _bidder, _policy)
            await session.commit()
            logger.info("── Étape 1-4 ✅ (user, policy, bidder, case)")

            # ── 5 : Financial Statements Raw ──────────────────────────────────
            await seed_financials(session, _case)
            await session.commit()
            logger.info("── Étape 5 ✅ (financials raw ×2)")

            # ── 6 : Normalisation ─────────────────────────────────────────────
            # process_normalization() attend UUID natif (signature: case_id: UUID)
            # Il fait son propre commit en interne — pas de commit après.
            from app.db.models import FinancialStatementNormalized
            norm_check = await session.execute(
                select(FinancialStatementNormalized)
                .join(
                    FinancialStatementRaw,
                    FinancialStatementNormalized.raw_statement_id == FinancialStatementRaw.id,
                )
                .where(FinancialStatementRaw.case_id == _case.id)
            )
            if norm_check.scalars().first() is None:
                await process_normalization(_case.id, session)  # ← UUID natif, pas str()
                logger.info("── Étape 6 ✅ (normalization done)")
            else:
                logger.info("── Étape 6 ✓ (normalization already done)")

            # ── 7 : Ratios ────────────────────────────────────────────────────
            # process_ratios() attend UUID natif (signature: case_id: UUID)
            # Il fait son propre commit en interne — pas de commit après.
            from app.db.models import RatioSet
            ratio_check = await session.execute(
                select(RatioSet).where(RatioSet.case_id == _case.id)
            )
            if ratio_check.scalars().first() is None:
                await process_ratios(_case.id, session)  # ← UUID natif, pas str()
                logger.info("── Étape 7 ✅ (ratios done)")
            else:
                logger.info("── Étape 7 ✓ (ratios already done)")

            # ── 8 : GateResult ────────────────────────────────────────────────
            # Commit obligatoire ICI : process_scoring lit GateResult via la même
            # session — il doit être visible avant l'appel.
            await seed_gate_result(session, _case)
            await session.commit()
            logger.info("── Étape 8 ✅ (gate result committed)")

            # ── 9 : Scoring ───────────────────────────────────────────────────
            # process_scoring() attend UUID natif (signature: case_id: UUID)
            # Il fait son propre commit en interne — pas de commit après.
            from app.db.models import Scorecard
            score_check = await session.execute(
                select(Scorecard).where(Scorecard.case_id == _case.id)
            )
            if score_check.scalars().first() is None:
                await process_scoring(_case.id, session)  # ← UUID natif, pas str()
                logger.info("── Étape 9 ✅ (scoring done)")
            else:
                logger.info("── Étape 9 ✓ (scoring already done)")

            # ── 10 : IAPrediction ─────────────────────────────────────────────
            await seed_ia_prediction(session, _case)
            await session.commit()
            logger.info("── Étape 10 ✅ (IA prediction)")

            # ── 11 : IAModel (stub) ───────────────────────────────────────────
            await seed_ia_model(session)
            await session.commit()
            logger.info("── Étape 11 ✅ (IA model stub)")

            # ── Résumé final ──────────────────────────────────────────────────
            logger.info("")
            logger.info("=" * 70)
            logger.info("✅ E2E seed completed successfully.")
            logger.info("")
            logger.info("  Login credentials (global-setup.ts):")
            logger.info(f"    Email    : {E2E_USER_EMAIL}")
            logger.info(f"    Password : {E2E_USER_PASSWORD}")
            logger.info("")
            logger.info("  Test case:")
            logger.info(f"    Reference: {E2E_CASE_REFERENCE}")
            logger.info(f"    E2E_CASE_ID={str(_case.id)}")
            logger.info("=" * 70)

        except Exception as exc:
            await session.rollback()
            logger.error(f"❌ Seed failed at step: {exc}")
            raise


def main() -> None:
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
