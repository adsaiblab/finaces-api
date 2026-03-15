"""
Train final IA model and register it in ia_models table.

- Loads training data via DataLoader / ModelTrainer
- Trains XGBoost (ou LightGBM) selon config
- Évalue le modèle (ROC-AUC, F1, etc.)
- Sauvegarde le modèle sur disque (joblib)
- Enregistre la nouvelle entrée dans ia_models via SQLAlchemy async
- (Optionnel) désactive les anciens modèles actifs

Usage:
    python -m scripts.train_and_register_model \
        --model-type xgboost \
        --data-source finaces_db \
        --as-active true
"""

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import joblib
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select, update

from app.core.config import settings
from app.db.database import Base
from app.db.models import IAModel
from ml.pipelines.training_pipeline import ModelTrainer


# ---------------------------------------------------------------------
# DB UTILS (ASYNC)
# ---------------------------------------------------------------------

def get_database_url() -> str:
    # Utilise la DB de prod ou une URL dédiée (ex: IA_TRAIN_DATABASE_URL)
    return getattr(settings, "DATABASE_URL", None) or getattr(
        settings, "SQLALCHEMY_DATABASE_URI"
    )


def create_async_session_factory() -> async_sessionmaker[AsyncSession]:
    db_url = get_database_url()
    if not db_url:
        raise RuntimeError("Database URL not configured in settings.")
    engine = create_async_engine(db_url, echo=False, future=True)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def register_model_in_db(
    session_factory: async_sessionmaker[AsyncSession],
    model_name: str,
    version: str,
    file_path: str,
    metrics: Dict[str, float],
    hyperparams: Dict[str, Any],
    feature_names: Dict[str, Any],
    set_active: bool = True,
) -> IAModel:
    """Insert new IAModel row and optionally deactivate previous active ones."""

    async with session_factory() as session:
        # Optionnel : désactiver les autres modèles actifs
        if set_active:
            await session.execute(
                update(IAModel)
                .where(IAModel.is_active.is_(True))
                .values(is_active=False)
            )

        model_row = IAModel(
            model_name=model_name,
            version=version,
            file_path=file_path,
            hyperparameters=hyperparams,
            metrics=metrics,
            feature_names=feature_names,
            is_active=set_active,
            trained_at=datetime.utcnow(),
        )
        session.add(model_row)
        await session.flush()
        await session.refresh(model_row)
        await session.commit()
        return model_row


# ---------------------------------------------------------------------
# TRAINING LOGIC
# ---------------------------------------------------------------------

async def async_main(args: argparse.Namespace) -> None:
    # 1) Instancier le pipeline de training
    trainer = ModelTrainer(
        model_config_path=args.model_config,
        features_config_path=args.features_config,
        output_dir=args.models_dir,
        plots_dir=args.plots_dir,
    )

    # 2) Préparer les données
    data = trainer.prepare_data(
        data_source=args.data_source,
        # kwargs spécifiques si besoin: années, filtres, etc.
    )
    X_train = data["X_train"]
    y_train = data["y_train"]
    X_val = data.get("X_val")
    y_val = data.get("y_val")
    X_test = data.get("X_test")
    y_test = data.get("y_test")

    # 3) Entraîner le modèle
    trainer.train_model(
        X_train=X_train,
        y_train=y_train,
        X_val=X_val,
        y_val=y_val,
        model_type=args.model_type,
    )

    # 4) Évaluer le modèle (sur test si dispo, sinon sur val)
    eval_split = "test" if X_test is not None and y_test is not None else "val"
    if eval_split == "test":
        metrics = trainer.evaluate_model(X_test, y_test)
    else:
        metrics = trainer.evaluate_model(X_val, y_val)

    # 5) Sauvegarder le modèle sur disque (joblib)
    models_dir = Path(args.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    version = args.version or f"{args.model_type}_v{timestamp}"
    filename = f"{args.model_type}_{version}.joblib"
    model_path = models_dir / filename

    joblib.dump(trainer.model, model_path)

    # 6) Récupérer infos hyperparams + features
    hyperparams = trainer.training_history.get("hyperparameters", {})
    feature_names = trainer.training_history.get("data_info", {}).get(
        "feature_names", []
    )

    # 7) Enregistrer dans ia_models via SQLAlchemy async
    session_factory = create_async_session_factory()
    model_row = await register_model_in_db(
        session_factory=session_factory,
        model_name=args.model_name or args.model_type,
        version=version,
        file_path=str(model_path),
        metrics=metrics,
        hyperparams=hyperparams,
        feature_names=feature_names,
        set_active=args.as_active,
    )

    print("Model trained and registered:")
    print(f"- id: {model_row.id}")
    print(f"- name: {model_row.model_name}")
    print(f"- version: {model_row.version}")
    print(f"- file: {model_row.file_path}")
    print(f"- is_active: {model_row.is_active}")
    print(f"- metrics: {json.dumps(model_row.metrics, indent=2)}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train IA model and register it in ia_models."
    )
    parser.add_argument(
        "--model-type",
        type=str,
        default="xgboost",
        choices=["xgboost", "lightgbm"],
        help="Type de modèle à entraîner.",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
        help="Nom logique du modèle (ex: xgboost_tabular_prod).",
    )
    parser.add_argument(
        "--version",
        type=str,
        default=None,
        help="Version explicite du modèle (sinon timestamp).",
    )
    parser.add_argument(
        "--data-source",
        type=str,
        default="synthetic",
        help="Source de données pour l'entraînement (synthetic, german, finaces_db).",
    )
    parser.add_argument(
        "--model-config",
        type=str,
        default="ml/config/model_config.yaml",
        help="Chemin fichier YAML de config modèle.",
    )
    parser.add_argument(
        "--features-config",
        type=str,
        default="ml/config/features_config.yaml",
        help="Chemin fichier YAML de config features.",
    )
    parser.add_argument(
        "--models-dir",
        type=str,
        default="ml/models",
        help="Dossier de sortie pour les modèles.",
    )
    parser.add_argument(
        "--plots-dir",
        type=str,
        default="ml/outputs/plots",
        help="Dossier de sortie pour les figures.",
    )
    parser.add_argument(
        "--as-active",
        type=lambda v: str(v).lower() in {"1", "true", "yes", "y"},
        default=True,
        help="Si true, définit ce modèle comme actif et désactive les autres.",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
