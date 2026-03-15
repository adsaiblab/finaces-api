import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.engines.ia.feature_engineering import FeatureEngineeringEngine
from app.db.models import IAFeatures

async def generate_and_save_ia_features(case_id: uuid.UUID, db: AsyncSession) -> dict:
    """
    Orchestrates the computation of IA features and saves them to the database.
    """
    engine = FeatureEngineeringEngine()
    
    # 1. Compute features
    result = await engine.compute_all_features(str(case_id), db)
    
    # 2. Save to database
    ia_features_record = IAFeatures(
        case_id=case_id,
        features=result["features"]
    )
    db.add(ia_features_record)
    await db.commit()
    await db.refresh(ia_features_record)
    
    return result
