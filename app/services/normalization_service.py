import logging
from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import FinancialStatementRaw, FinancialStatementNormalized
from app.schemas.normalization_schema import FinancialStatementRawSchema, FinancialStatementNormalizedSchema
from app.engines.normalization_engine import calculate_normalized_aggregates
from app.exceptions.finaces_exceptions import MissingFinancialDataError
from app.schemas.policy_schema import PolicyConfigurationSchema
from app.services.audit_service import log_event
from app.services.policy_service import get_active_policy

logger = logging.getLogger(__name__)

async def process_normalization(case_id: UUID, db: AsyncSession) -> List[FinancialStatementNormalizedSchema]:
    """
    Asynchronous Orchestrator:
    1. Retrieves raw data via SQLAlchemy 2.0 Async.
    2. Converts ORMs to Pydantic schemas.
    3. Executes the calculation through the pure math engine.
    4. Persists the normalized results in the database.
    """
    logger.info(f"Starting async normalization process for case {case_id}")

    # 1. Fetch raw statements
    stmt = select(FinancialStatementRaw).where(FinancialStatementRaw.case_id == case_id)
    result = await db.execute(stmt)
    raw_statements_orm = result.scalars().all()

    if not raw_statements_orm:
        logger.warning(f"No raw financial statements found for case {case_id}")
        raise MissingFinancialDataError(f"Raw financial data missing for case evaluation id: {case_id}")

    # 2. Conversion ORM -> Pydantic Schema
    raw_schemas = [
        FinancialStatementRawSchema.model_validate(orm)
        for orm in raw_statements_orm
    ]

    # 3. Policy recovery (Real DB Fetch - P0-ASYNC-01 Fixed)
    policy_dict = await get_active_policy(db)
    policy = PolicyConfigurationSchema(**policy_dict)

    # 4. Engine Call (Pure Function - Intelligence Matrix)
    try:
        normalized_schemas = [
            calculate_normalized_aggregates(
                raw=raw_schema,
                adjustments=[] # Future feature: Fetch adjustments
            ) for raw_schema in raw_schemas
        ]
    except Exception as e:
        logger.error(f"Computation failure during Pure Normalizer execution on case {case_id}: {str(e)}")
        raise # Reroute EngineComputationError if failed upstream.

    # 5. Asynchronous Persistence
    db_entities = []
    for norm_schema in normalized_schemas:
        # Prevent insertion collision -> Check if exists
        existing_stmt = select(FinancialStatementNormalized).where(
            FinancialStatementNormalized.raw_statement_id == norm_schema.raw_statement_id,
            FinancialStatementNormalized.fiscal_year == norm_schema.fiscal_year
        )
        existing_result = await db.execute(existing_stmt)
        existing_norm = existing_result.scalars().first()
        
        if existing_norm:
            # Update fields safely through dump bypass mapping explicitly (excluding internal attributes)
            for key, value in norm_schema.model_dump(exclude={'id'}).items():
                setattr(existing_norm, key, value)
            db_entities.append(existing_norm)
        else:
            # Create a brand new ORM entry
            new_norm = FinancialStatementNormalized(**norm_schema.model_dump(exclude={'id'}))
            db.add(new_norm)
            db_entities.append(new_norm)

    # Save transaction
    await db.commit()
    
    # 1. Refresh all entities first
    for entity in db_entities:
        await db.refresh(entity)
        
    # 2. ─ Audit Trail (MCC-Grade Compliance - P0-TXSAFE-01 Fixed) ─
    for entity in db_entities:
        try:
            await log_event(
                db=db,
                event_type="STATEMENTS_NORMALIZED",
                entity_type="FinancialStatementNormalized",
                entity_id=str(entity.id),
                case_id=str(case_id),
                description=f"Raw statements normalized and persisted for fiscal year {entity.fiscal_year}"
            )
        except Exception as e:
            # Non-blocking error logging for audit failure
            logger.critical(f"CRITICAL: AUDIT TRAIL FAILURE for normalized entity {entity.id} (Case {case_id}): {str(e)}")
            
    logger.info(f"Async normalization committed successfully for case {case_id}")
    
    return normalized_schemas
