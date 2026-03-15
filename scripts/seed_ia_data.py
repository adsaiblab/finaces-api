"""
Seed IA historical data into test database.

Objectifs:
- Créer des entrées ia_models (si besoin)
- Créer des EvaluationCase / IAFeatures / IAPrediction / IATension historiques
- Simuler un historique de prédictions IA passées (pour dashboards, courbes, tensions)

Usage:
    TEST_DATABASE_URL=... python -m scripts.seed_ia_data \
        --days 90 \
        --cases 30
"""

import argparse
import asyncio
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
from uuid import uuid4

import joblib
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.db.database import Base
from app.db.models import (
    EvaluationCase,
    Bidder,
    IAFeatures,
    IAPrediction,
    IATension,
    IAModel,
)
from app.core.config import settings
from app.schemas.ia_schema import IARiskClass


# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------

RISK_CLASSES = [IARiskClass.LOW, IARiskClass.MODERATE, IARiskClass.HIGH, IARiskClass.CRITICAL]


def get_test_db_url() -> str:
    # Priorité à TEST_DATABASE_URL, sinon DATABASE_URL
    return (
        getattr(settings, "TEST_DATABASE_URL", None)
        or getattr(settings, "DATABASE_URL", None)
        or getattr(settings, "SQLALCHEMY_DATABASE_URI", None)
    )


def create_async_session_factory() -> async_sessionmaker[AsyncSession]:
    db_url = get_test_db_url()
    if not db_url:
        raise RuntimeError("Test database URL not configured.")
    if "test" not in db_url:
        raise RuntimeError(f"Refuse to seed non-test DB: {db_url}")
    engine = create_async_engine(db_url, echo=False, future=True)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------

def generate_fake_features(n_features: int = 40) -> Dict[str, float]:
    """Génère un dict de features IA plausibles mais synthétiques."""
    feats = {}
    for i in range(n_features):
        feats[f"feature_{i}"] = random.uniform(-1.0, 1.0)
    return feats


def simulate_risk_from_probability(p_default: float) -> IARiskClass:
    """Map une probabilité de défaut à une classe de risque."""
    if p_default < 0.15:
        return IARiskClass.LOW
    elif p_default < 0.30:
        return IARiskClass.MODERATE
    elif p_default < 0.55:
        return IARiskClass.HIGH
    else:
        return IARiskClass.CRITICAL


async def get_or_create_active_model(
    session: AsyncSession,
    model_path: str | None = None,
) -> IAModel:
    """Retourne un IAModel actif, ou en crée un minimal si aucun n'existe."""
    result = await session.execute(
        select(IAModel).where(IAModel.is_active.is_(True))
    )
    model = result.scalar_one_or_none()
    if model:
        return model

    # Sinon créer un modèle de test minimal
    model = IAModel(
        id=uuid4(),
        model_name="xgboost_seed_test",
        version="seed_v1.0",
        file_path=model_path or "ml/models/seed_model.joblib",
        hyperparameters={"n_estimators": 50, "max_depth": 4},
        metrics={"roc_auc": 0.80, "precision": 0.75, "recall": 0.78, "f1_score": 0.76},
        feature_names=[f"feature_{i}" for i in range(40)],
        is_active=True,
        trained_at=datetime.utcnow(),
    )
    session.add(model)
    await session.flush()
    await session.refresh(model)
    return model


# ---------------------------------------------------------------------
# MAIN SEED LOGIC
# ---------------------------------------------------------------------

async def seed_data(args: argparse.Namespace) -> None:
    session_factory = create_async_session_factory()

    async with session_factory() as session:
        # 1) Vérifier/créer un modèle IA actif
        model = await get_or_create_active_model(session)
        await session.commit()

    async with session_factory() as session:
        # 2) Créer des bidders + cases + prédictions historiques
        base_date = datetime.utcnow()
        total_cases = args.cases
        days_back = args.days

        for i in range(total_cases):
            # Choisir une date historique aléatoire dans la fenêtre
            delta_days = random.randint(0, days_back)
            created_at = base_date - timedelta(days=delta_days)

            # Bidder
            bidder = Bidder(
                id=uuid4(),
                name=f"Seed Company {i+1}",
                legal_form="SARL",
                country="Morocco",
                sector="Construction",
            )
            session.add(bidder)
            await session.flush()

            # Case
            case = EvaluationCase(
                id=uuid4(),
                case_type="SINGLE",
                bidder_id=bidder.id,
                market_reference=f"SEED-{i+1:04d}",
                contract_value=random.uniform(1_000_000, 10_000_000),
                contract_currency="USD",
                contract_duration_months=random.choice([12, 24, 36, 48]),
                status="COMPLETED",
                created_at=created_at,
            )
            session.add(case)
            await session.flush()

            # Features (simplifiées : 40 features synthétiques)
            features_dict = generate_fake_features(40)
            ia_features = IAFeatures(
                id=uuid4(),
                case_id=case.id,
                features={
                    "features": features_dict,
                    "metadata": {
                        "case_id": str(case.id),
                        "computed_at": created_at.isoformat(),
                        "feature_count": len(features_dict),
                        "fiscal_years_used": [created_at.year - 1, created_at.year],
                    },
                },
            )
            session.add(ia_features)
            await session.flush()

            # Probabilité défaut random mais biaisée
            # plus le montant du contrat est élevé, plus on peut augmenter la proba
            base_prob = random.uniform(0.05, 0.60)
            amount_factor = (case.contract_value / 10_000_000) * 0.2
            p_default = min(base_prob + amount_factor, 0.95)

            risk_class = simulate_risk_from_probability(p_default)
            ia_score = (1 - p_default) * 5.0

            prediction_time = created_at + timedelta(hours=random.randint(1, 24))

            prediction = IAPrediction(
                id=uuid4(),
                case_id=case.id,
                ia_model_id=model.id,
                ia_score=ia_score,
                ia_probability_default=p_default,
                ia_risk_class=risk_class.value,
                model_version=model.version,
                predicted_at=prediction_time,
            )
            session.add(prediction)
            await session.flush()

            # Optionnel : créer quelques tensions simulées
            if random.random() < args.tension_rate:
                # MCC risk class simulée, souvent plus "optimiste"
                mcc_risk_class = random.choice(
                    ["LOW", "MODERATE", "HIGH"]
                )  # éviter CRITICAL pour divergence
                tension_type = "CONVERGENCE"
                gap = 0

                # si MCC < IA -> tension_up
                r_map = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
                if r_map[mcc_risk_class] < r_map[risk_class.value]:
                    gap = r_map[risk_class.value] - r_map[mcc_risk_class]
                    tension_type = "TENSION_UP" if gap == 1 else "MAJOR_DIVERGENCE"

                tension = IATension(
                    id=uuid4(),
                    case_id=case.id,
                    mcc_risk_class=mcc_risk_class,
                    ia_risk_class=risk_class.value,
                    tension_type="TENSION_UP" if gap >= 2 else "MODERATE" if gap == 1 else "NONE",
                    explanation=f"Seeded historical tension for testing. Gap detected: {gap}",
                    created_at=prediction_time + timedelta(minutes=15)
                )
                session.add(tension)

        await session.commit()

    print(f"Seeded IA historical data: {total_cases} cases over last {days_back} days.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed IA historical data into test database."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Fenêtre de jours dans le passé pour la génération des dates.",
    )
    parser.add_argument(
        "--cases",
        type=int,
        default=30,
        help="Nombre de dossiers d'évaluation à créer.",
    )
    parser.add_argument(
        "--tension-rate",
        type=float,
        default=0.3,
        help="Proportion approximative de dossiers avec tension MCC-IA.",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    asyncio.run(seed_data(args))


if __name__ == "__main__":
    main()
