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
        Collects features and targets from historical cases or synthetic generator.
        """
        source_type = (query_filter or {}).get("source", "REAL")
        
        if source_type == "SYNTHETIC":
            # Simulation of a large synthetic dataset
            n_samples = (query_filter or {}).get("n_samples", 3000)
            dataset = IATrainingDataset(
                dataset_name=dataset_name,
                sample_size=n_samples,
                features_list=["current_ratio", "debt_to_equity", "net_margin", "ebitda_margin", "roe", "roa"], # Representative list
                target_column=target_column,
                query_filter=query_filter
            )
            db.add(dataset)
            await db.commit()
            await db.refresh(dataset)
            return dataset

        # 1. Identity cases with both features and valid outcomes (scorecards)
        stmt = (
            select(IAFeatures, Scorecard)
            .join(Scorecard, IAFeatures.case_id == Scorecard.case_id)
            .order_by(IAFeatures.created_at.desc())
        )
        
        result = await db.execute(stmt)
        rows = result.all()
        
        if not rows:
            raise ValueError("No historical data available with both features and scorecards. Use source='SYNTHETIC' for bootstrap.")
            
        # 2. Extract features and labels
        all_features_list = []
        if rows:
            first_features = rows[0][0].features
            if isinstance(first_features, dict):
                # Ensure we handle nested structure if needed
                if 'features' in first_features:
                    all_features_list = list(first_features['features'].keys())
                else:
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
        Creates a training run record. Actual execution is triggered by the router
        via BackgroundTasks to avoid HTTP timeouts.
        """
        # 1. Verify dataset exists
        dataset_stmt = select(IATrainingDataset).where(IATrainingDataset.id == dataset_id)
        dataset = await db.scalar(dataset_stmt)
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found.")

        # 2. Create the run record
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
        
        return run

    @staticmethod
    async def run_training_background(run_id: uuid.UUID):
        """
        Actual background task for ML training.
        Creates its own session to ensure thread-safety and session availability.
        """
        from app.db.database import async_session_maker
        from app.db.models import IATrainingRun, IATrainingDataset
        
        async with async_session_maker() as db:
            run_stmt = (
                select(IATrainingRun)
                .options(selectinload(IATrainingRun.dataset))
                .where(IATrainingRun.id == run_id)
            )
            run = await db.scalar(run_stmt)
            if not run:
                logger.error(f"Background training failed: Run {run_id} not found.")
                return

            try:
                # 1. Determine data source from dataset query_filter
                source = (run.dataset.query_filter or {}).get("source", "REAL")
                n_samples = (run.dataset.query_filter or {}).get("n_samples", 3000)
                
                logger.info(f"Starting training run {run.id} (Source: {source}, Model: {run.model_type})")
                
                # 2. Configure Trainer
                trainer = ModelTrainer(output_dir="ml/models")
                
                # 3. Run Pipeline
                # If source is synthetic, we pass n_samples. If REAL, it's already using DB.
                data_kwargs = {}
                if source == "SYNTHETIC":
                    data_kwargs["n_samples"] = n_samples
                    data_source_id = "synthetic"
                else:
                    # For real data, we might need a db_session inside prepare_data
                    # but DataLoader.load_dataset currently handles finaces_db
                    data_source_id = "finaces_db"
                    data_kwargs["db_session"] = db
                
                results = trainer.run_complete_pipeline(
                    data_source=data_source_id,
                    model_type=run.model_type,
                    **data_kwargs
                )
                
                # 4. Update Run Record
                run.status = "COMPLETED"
                run.completed_at = datetime.now(timezone.utc)
                
                # Enriched metrics including convergence
                run.metrics = {
                    "accuracy": results['metrics'].get('accuracy'),
                    "f1_score": results['metrics'].get('f1_score'),
                    "auc": results['metrics'].get('roc_auc'),
                    "precision": results['metrics'].get('precision'),
                    "recall": results['metrics'].get('recall'),
                    "threshold": results['metrics'].get('threshold'),
                    "feature_importance": results.get('feature_importance', []),
                    "convergence": results.get('training_history', {}).get('convergence', {})
                }
                run.model_artifact_path = str(results['model_path'])
                
                logger.info(f"✓ Training run {run.id} completed successfully")

            except Exception as e:
                logger.exception(f"Training failed for run {run.id}")
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
