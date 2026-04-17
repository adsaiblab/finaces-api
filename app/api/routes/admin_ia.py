import uuid
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
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
from app.db.models import IATrainingRun, IADeployedModel, IAAdminEvent, IATrainingDataset

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
    # 1. Total runs
    total_runs = await db.scalar(select(func.count(IATrainingRun.id)))
    
    # 2. Active model
    active_stmt = select(IADeployedModel).where(IADeployedModel.is_active == True).limit(1)
    active_model = await db.scalar(active_stmt)
    
    # 3. Latest metrics (from the active model's run)
    latest_metrics = None
    if active_model:
        run_stmt = select(IATrainingRun).where(IATrainingRun.id == active_model.training_run_id)
        active_run = await db.scalar(run_stmt)
        if active_run:
            latest_metrics = active_run.metrics
            
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
    stmt = select(IATrainingRun).order_by(IATrainingRun.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post(
    "/datasets",
    response_model=IATrainingDatasetSchema,
    summary="Build a new training dataset"
)
async def build_dataset(
    dataset_name: str,
    target_column: str = "mcc_score",
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
):
    try:
        return await IATrainingService.build_training_dataset(
            db, dataset_name, target_column
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
    model_type: str = "xgboost",
    hyperparameters: Optional[Dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(get_current_user)
):
    return await IATrainingService.launch_training(
        db, dataset_id, model_type, hyperparameters
    )

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
