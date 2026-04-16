import logging
from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import FinancialStatementNormalized, RatioSet, FinancialStatementRaw
from app.schemas.normalization_schema import NormalizedStatementUIResponse
from app.schemas.ratio_schema import RatioSetSchema
from app.engines.ratio_engine import compute_ratios
from app.exceptions.finaces_exceptions import MissingFinancialDataError
from app.schemas.policy_schema import PolicyConfigurationSchema
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

async def _get_active_policy(db: AsyncSession) -> PolicyConfigurationSchema:
    """
    Mock Service: Returns the default PolicyConfigurationSchema.
    This injects the dynamic configuration like Z-Score bounds.
    """
    return PolicyConfigurationSchema(version_id="mock_active_policy")

async def process_ratios(case_id: UUID, db: AsyncSession) -> List[RatioSetSchema]:
    """
    Asynchronous Orchestrator:
    1. Retrieves normalized data via SQLAlchemy 2.0 Async.
    2. Converts ORMs to Pydantic immutable schemas.
    3. Executes the calculation through the pure math engine.
    4. Persists key figure sets in the database transactionally.
    """
    logger.info(f"Starting async ratio computation process for case {case_id}")

    # 1. Fetch normalized statements (Explicit Async JOIN - P0-ASYNC-02 Fixed)
    stmt = (
        select(FinancialStatementNormalized)
        .join(FinancialStatementRaw, FinancialStatementNormalized.raw_statement_id == FinancialStatementRaw.id)
        .where(FinancialStatementRaw.case_id == case_id)
    )
    result = await db.execute(stmt)
    normalized_statements_orm = result.scalars().all()

    if not normalized_statements_orm:
        logger.warning(f"No normalized financial statements found for case {case_id}")
        raise MissingFinancialDataError(f"No normalized financial statements found for ratio computation.")

    # 2. Conversion ORM -> Pydantic Schema (pipeline architecture respected)
    # The engine handles the float -> Decimal casting internally for absolute algebraic security.
    normalized_schemas = [
        NormalizedStatementUIResponse.model_validate(orm)
        for orm in normalized_statements_orm
    ]

    # 3. Policy recovery (Policy Injection)
    policy = await _get_active_policy(db)

    # 4. Engine Calls & Asynchronous Persistence
    ratio_sets_generated = []
    db_entities = []
    
    for norm_schema in normalized_schemas:
        try:
            # Mathematical engine compute iteration per fiscal year statement
            ratio_set_schema = compute_ratios(
                norm=norm_schema, 
                case_id=case_id, 
                policy=policy
            )
            ratio_sets_generated.append(ratio_set_schema)
            
            # 5. Asynchronous Persistence of the RatioSetSchema
            exclude_keys = {'id', 'created_at'} | {k for k in ratio_set_schema.model_fields.keys() if k.endswith('_variation_pct')}
            
            existing_stmt = select(RatioSet).where(
                RatioSet.normalized_statement_id == ratio_set_schema.normalized_statement_id,
                RatioSet.fiscal_year == ratio_set_schema.fiscal_year
            )
            existing_result = await db.execute(existing_stmt)
            existing_ratio_set = existing_result.scalars().first()
            
            if existing_ratio_set:
                for key, value in ratio_set_schema.model_dump(exclude=exclude_keys).items():
                    setattr(existing_ratio_set, key, value)
                db_entities.append(existing_ratio_set)
            else:
                exclude_keys_insert = {'id'} | {k for k in ratio_set_schema.model_fields.keys() if k.endswith('_variation_pct')}
                new_ratio_set = RatioSet(**ratio_set_schema.model_dump(exclude=exclude_keys_insert))
                db.add(new_ratio_set)
                db_entities.append(new_ratio_set)
                
        except Exception as e:
            logger.error(f"Computation failure during Pure Ratio Builder mapping on case {case_id}: {str(e)}")
            raise

    # Save transaction
    await db.commit()
    for entity in db_entities:
        await db.refresh(entity)
        # ─ Audit Trail (MCC-Grade Compliance) ─────────────────────
        await log_event(
            db=db,
            event_type="RATIOS_COMPUTED",
            entity_type="RatioSet",
            entity_id=str(entity.id),
            case_id=str(case_id),
            description=f"Ratios computed successfully for fiscal year {entity.fiscal_year}"
        )
        
    logger.info(f"Async ratio computation committed successfully for case {case_id} ({len(ratio_sets_generated)} years processed)")

    # 6. Compute Variations (P3)
    from app.engines.ratio_engine import compute_variations
    ratio_sets_generated.sort(key=lambda x: x.fiscal_year)
    for i in range(1, len(ratio_sets_generated)):
        current = ratio_sets_generated[i]
        previous = ratio_sets_generated[i-1]
        variations = compute_variations(current, previous)
        for k, v in variations.items():
            setattr(current, k, v)

    # 7. Cross-pillar pattern detection (needs all years — runs AFTER all individual computations)
    from app.engines.ratio_engine import generate_cross_pillar_patterns
    cross_pillar_alerts = generate_cross_pillar_patterns(ratio_sets_generated, policy)
    if cross_pillar_alerts and ratio_sets_generated:
        # Attach cross-pillar alerts to the most recent year's schema
        latest = max(ratio_sets_generated, key=lambda r: r.fiscal_year)
        existing_alerts = list(latest.coherence_alerts_json or [])
        for alert in cross_pillar_alerts:
            existing_alerts.append(alert.model_dump(exclude_none=True))
        latest.coherence_alerts_json = existing_alerts

    return ratio_sets_generated
