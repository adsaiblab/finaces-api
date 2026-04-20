import uuid
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.database import get_db
from app.core.security import get_current_user
from app.services.ia_training_service import IATrainingService
from app.schemas.ia_schema import (
    IATrainingDatasetSchema,
    IATrainingRunSchema,
    IADeployedModelSchema,
    IAAdminStats
)
from app.db.models import IAModel, IATrainingRun, IADeployedModel, IAAdminEvent, IATrainingDataset

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin-ia", tags=["AI Administration"])

@router.get(
    "/stats",
    response_model=IAAdminStats,
    summary="Get Admin IA dashboard stats"
)
async def get_admin_stats(
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
):
    """
    Returns high-level stats for the Admin IA dashboard.
    """
    # 1. Total models/runs
    total_runs = await db.scalar(select(func.count(IAModel.id)))
    
    # 2. Active model — lit IAModel (table réelle), construit un IADeployedModelSchema-compatible dict
    ia_model_stmt = select(IAModel).where(IAModel.is_active.is_(True)).limit(1)
    ia_model = await db.scalar(ia_model_stmt)

    active_model = IADeployedModelSchema(
        id=ia_model.id,
        training_run_id=ia_model.id,
        version=ia_model.version,
        is_active=ia_model.is_active,
        deployed_by=None,
        deployed_at=ia_model.trained_at,
    ) if ia_model else None

    # 3. Latest metrics
    latest_metrics = None
    if ia_model and ia_model.metrics:
        raw = ia_model.metrics
        latest_metrics = {
            "accuracy":  raw.get("accuracy", 0),
            "f1_score":  raw.get("f1_score", 0),
            "auc":       raw.get("roc_auc", 0),
            "recall":    raw.get("recall", 0),
            "precision": raw.get("precision", 0),
            "threshold": raw.get("threshold", 0.5),
            "feature_importance": raw.get("feature_importance", []),  # ✅ FIX
        }
            
    # 4. Pending alerts
    alerts_count = await db.scalar(
        select(func.count(IAAdminEvent.id)).where(IAAdminEvent.is_resolved == False)
    )
    
    return IAAdminStats(
        active_model=active_model,
        total_training_runs=total_runs or 0,
        latest_metrics=latest_metrics,
        pending_alerts_count=alerts_count or 0
    )

@router.get(
    "/runs",
    response_model=List[IATrainingRunSchema],
    summary="List training runs"
)
async def list_training_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
):
    stmt = select(IAModel).order_by(IAModel.trained_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return [
        IATrainingRunSchema(
            id=m.id,
            dataset_id=m.id,
            model_type=m.model_name,
            status="COMPLETED",
            hyperparameters=m.hyperparameters or {},
            metrics={
                "accuracy":  (m.metrics or {}).get("accuracy", 0),
                "f1_score":  (m.metrics or {}).get("f1_score", 0),
                "auc":       (m.metrics or {}).get("roc_auc", 0),
                "threshold": (m.metrics or {}).get("threshold", 0.5),
                "feature_importance": (m.metrics or {}).get("feature_importance", []),  # ✅ FIX
            },
            model_artifact_path=m.file_path,
            error_log=None,
            started_at=m.trained_at,
            completed_at=m.trained_at,
            created_at=m.created_at,
        )
        for m in result.scalars().all()
    ]

@router.post(
    "/datasets",
    response_model=IATrainingDatasetSchema,
    summary="Build a new training dataset"
)
async def build_dataset(
    dataset_name: str,
    target_column: str = "mcc_score",
    query_filter: Optional[Dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
):
    try:
        return await IATrainingService.build_training_dataset(
            db, dataset_name, target_column, query_filter
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post(
    "/train/{dataset_id}",
    response_model=IATrainingRunSchema,
    summary="Launch a training run"
)
async def launch_training(
    dataset_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    model_type: str = "xgboost",
    hyperparameters: Optional[Dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
):
    run = await IATrainingService.launch_training(
        db, dataset_id, model_type, hyperparameters
    )
    background_tasks.add_task(IATrainingService.run_training_background, run.id)
    return run

@router.get(
    "/runs/{run_id}/convergence",
    summary="Get convergence data for a training run"
)
async def get_run_convergence(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
):
    """
    Returns the convergence history (LogLoss per iteration) for a run.
    Data is extracted from ia_models.metrics['convergence'].
    """
    # ✅ FIX — chercher dans IAModel, pas IATrainingRun
    stmt = select(IAModel.metrics).where(IAModel.id == run_id)
    metrics = await db.scalar(stmt)

    if not metrics or "convergence" not in metrics:
        return []

    convergence_raw = metrics["convergence"]
    # XGBoost evals_result: {'validation_0': {'logloss': [...]}, 'validation_1': {'logloss': [...]}}
    # Frontend expects: [{"epoch": 0, "train_loss": 0.75, "val_loss": 0.76}, ...]

    formatted_data = []

    train_key = "validation_0"
    val_key = "validation_1"

    metric_name = (
        "logloss" if "logloss" in convergence_raw.get(train_key, {}) else
        "binary_logloss" if "binary_logloss" in convergence_raw.get(train_key, {}) else
        "rmse" if "rmse" in convergence_raw.get(train_key, {}) else
        None
    )

    if not metric_name and convergence_raw:
        first_group = list(convergence_raw.values())[0]
        if first_group:
            metric_name = list(first_group.keys())[0]

    if metric_name:
        train_vals = convergence_raw.get(train_key, {}).get(metric_name, [])
        val_vals = convergence_raw.get(val_key, {}).get(metric_name, [])

        for i, t_val in enumerate(train_vals):
            point = {"epoch": i, "train_loss": float(t_val)}
            if i < len(val_vals):
                point["val_loss"] = float(val_vals[i])
            formatted_data.append(point)

    return formatted_data

@router.post(
    "/deploy/{run_id}",
    response_model=IADeployedModelSchema,
    summary="Deploy a trained model"
)
async def deploy_model(
    run_id: uuid.UUID,
    version: str,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
):
    try:
        return await IATrainingService.deploy_model(
            db, run_id, version, deployed_by=current_user.get("sub", "SYSTEM")
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get(
    "/events",
    response_model=List[Dict[str, Any]],
    summary="List admin events/alerts"
)
async def list_admin_events(
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
):
    stmt = select(IAAdminEvent).order_by(IAAdminEvent.created_at.desc()).limit(50)
    result = await db.execute(stmt)
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "severity": e.severity,
            "message": e.message,
            "created_at": e.created_at,
            "is_resolved": e.is_resolved
        }
        for e in result.scalars().all()
    ]