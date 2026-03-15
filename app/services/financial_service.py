import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.db.models import FinancialStatementRaw
from app.services.case_service import invalidate_case_pipeline

logger = logging.getLogger(__name__)

async def upsert_financial_statement(case_uuid: uuid.UUID, fiscal_year: int, data: dict, db: AsyncSession) -> tuple[uuid.UUID, str]:
    result = await db.execute(
        select(FinancialStatementRaw).where(
            FinancialStatementRaw.case_id == case_uuid,
            FinancialStatementRaw.fiscal_year == fiscal_year,
        )
    )
    existing_stmt = result.scalars().first()

    # [IRB] Purge downstream calculations BEFORE modifying the raw data
    await invalidate_case_pipeline(case_uuid, db)

    if existing_stmt:
        for key, value in data.items():
            if hasattr(existing_stmt, key):
                setattr(existing_stmt, key, value)
        existing_stmt.updated_at = datetime.now(timezone.utc)
        stmt_id = existing_stmt.id
        event_type = "FINANCIAL_UPDATED"
    else:
        new_stmt = FinancialStatementRaw(case_id=case_uuid, **data)
        db.add(new_stmt)
        await db.flush()
        stmt_id = new_stmt.id
        event_type = "FINANCIAL_CREATED"

    await db.commit()
    return stmt_id, event_type

async def delete_financial_statement(case_uuid: uuid.UUID, statement_id: uuid.UUID, db: AsyncSession):
    result = await db.execute(
        select(FinancialStatementRaw).where(
            FinancialStatementRaw.id == statement_id,
            FinancialStatementRaw.case_id == case_uuid,
        )
    )
    stmt = result.scalars().first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Financial statement not found.")

    # [IRB] Purge pipeline BEFORE deletion commit
    await invalidate_case_pipeline(case_uuid, db)

    await db.delete(stmt)
    await db.commit()
