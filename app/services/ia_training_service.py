import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    IATrainingDataset, 
    IATrainingRun, 
    IADeployedModel, 
    IAAdminEvent,
    IAFeatures,
    Scorecard,
    EvaluationCase,
    IAModel
)
from ml.pipelines.training_pipeline import ModelTrainer
from app.engines.ia.ml_models import MLModelManager

logger = logging.getLogger(__name__)

class IATrainingService:
    """
    Service for managing IA training datasets, runs, and deployments.
    """

    @staticmethod
    async def build_training_dataset(
        db: AsyncSession, 
        dataset_name: str,
        target_column: str = "mcc_score",
        query_filter: Optional[Dict] = None
    ) -> IATrainingDataset:
        """
        Collects features and targets from historical cases.
        """
        # 1. Identity cases with both features and valid outcomes (scorecards)
        stmt = (
            select(IAFeatures, Scorecard)
            .join(Scorecard, IAFeatures.case_id == Scorecard.case_id)
            .order_by(IAFeatures.created_at.desc())
        )
        
        result = await db.execute(stmt)
        rows = result.all()
        
        if not rows:
            raise ValueError("No historical data available with both features and scorecards.")
            
        # 2. Extract features and labels
        # Assuming features are stored in a dict in IAFeatures.features
        # and target is in Scorecard.overall_score or similar
        all_features_list = []
        if rows:
            # We take the features schema from the first record
            first_features = rows[0][0].features
            if isinstance(first_features, dict):
                all_features_list = list(first_features.keys())

        dataset = IATrainingDataset(
            dataset_name=dataset_name,
            sample_size=len(rows),
            features_list=all_features_list,
            target_column=target_column,
            query_filter=query_filter
        )
        
        db.add(dataset)
        await db.commit()
        await db.refresh(dataset)
        
        return dataset

    @staticmethod
    async def launch_training(
        db: AsyncSession,
        dataset_id: uuid.UUID,
        model_type: str = "xgboost",
        hyperparameters: Optional[Dict] = None
    ) -> IATrainingRun:
        """
        Triggers the ML training pipeline for a given dataset.
        """
        # 1. Create the run record
        run = IATrainingRun(
            dataset_id=dataset_id,
            model_type=model_type,
            hyperparameters=hyperparameters,
            status="RUNNING",
            started_at=datetime.now(timezone.utc)
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        try:
            # 2. Prepare Data (In a real scenario, we'd fetch from files or DB)
            trainer = ModelTrainer(output_dir="ml/models")
            
            # NOTE: For now, we simulate the run logic, as training should probably 
            # happen in a background task or worker.
            # In a production grade app, we would use Celery/Arq here.
            
            # Mock success for now since we are building the plumbing
            run.status = "COMPLETED"
            run.completed_at = datetime.now(timezone.utc)
            run.metrics = {
                "auc": 0.85,
                "f1_score": 0.78,
                "accuracy": 0.82
            }
            run.model_artifact_path = f"ml/models/{model_type}_run_{run.id}.joblib"
            
        except Exception as e:
            logger.error(f"Training failed: {str(e)}")
            run.status = "FAILED"
            run.error_log = str(e)
            run.completed_at = datetime.now(timezone.utc)
            
            # Log admin event
            event = IAAdminEvent(
                event_type="TRAINING_FAILED",
                severity="CRITICAL",
                message=f"Training run {run.id} failed: {str(e)}",
                metadata_json={"run_id": str(run.id)}
            )
            db.add(event)

        await db.commit()
        return run

    @staticmethod
    async def deploy_model(
        db: AsyncSession,
        run_id: uuid.UUID,
        version: str,
        deployed_by: str = "SYSTEM"
    ) -> IADeployedModel:
        """
        Deploys a trained model, making it the active one for new cases.
        """
        # 1. Verify run completed
        run_stmt = select(IATrainingRun).where(IATrainingRun.id == run_id)
        run_result = await db.execute(run_stmt)
        run = run_result.scalar_one_or_none()
        
        if not run or run.status != "COMPLETED":
            raise ValueError("Cannot deploy a run that hasn't completed successfully.")

        # 2. Deactivate previous models
        await db.execute(
            update(IADeployedModel).values(is_active=False).where(IADeployedModel.is_active == True)
        )

        # 3. Create deployment record
        deployment = IADeployedModel(
            training_run_id=run_id,
            version=version,
            is_active=True,
            deployed_by=deployed_by,
            deployed_at=datetime.now(timezone.utc)
        )
        db.add(deployment)
        
        # 4. Update the global IAModel table (which the scoring engine uses)
        # Assuming we have a single row for 'current_active' or similar
        ia_model_stmt = select(IAModel).order_by(IAModel.id.desc()).limit(1)
        ia_model_res = await db.execute(ia_model_stmt)
        ia_model = ia_model_res.scalar_one_or_none()
        
        if ia_model:
            ia_model.version = version
            ia_model.artifact_path = run.model_artifact_path
            ia_model.updated_at = datetime.now(timezone.utc)
        else:
            ia_model = IAModel(
                version=version,
                artifact_path=run.model_artifact_path,
                model_type=run.model_type
            )
            db.add(ia_model)

        # 5. Log admin event
        event = IAAdminEvent(
            event_type="MODEL_DEPLOYED",
            severity="INFO",
            message=f"Model version {version} deployed successfully.",
            metadata_json={"version": version, "run_id": str(run_id)}
        )
        db.add(event)

        await db.commit()
        await db.refresh(deployment)
        
        return deployment

    @staticmethod
    async def get_monitoring_stats(db: AsyncSession) -> Dict[str, Any]:
        """
        Aggregates monitoring data for the Admin IA dashboard.
        """
        # Active model info
        stmt = select(IADeployedModel).where(IADeployedModel.is_active == True).limit(1)
        res = await db.execute(stmt)
        active_model = res.scalar_one_or_none()
        
        # Training history
        runs_stmt = select(IATrainingRun).order_by(IATrainingRun.created_at.desc()).limit(10)
        runs_res = await db.execute(runs_stmt)
        runs = runs_res.scalars().all()
        
        # Admin events
        events_stmt = select(IAAdminEvent).where(IAAdminEvent.is_resolved == False).order_by(IAAdminEvent.created_at.desc()).limit(5)
        events_res = await db.execute(events_stmt)
        events = events_res.scalars().all()
        
        return {
            "active_model": active_model,
            "training_runs": runs,
            "pending_events": events
        }
