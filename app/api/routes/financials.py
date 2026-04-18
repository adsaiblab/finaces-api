"""
app/api/routes/financials.py — Raw financial statements ingestion
Sprint 2B: 100% Async / SQLAlchemy 2.0 / Pydantic V2
Includes systematic pipeline invalidation on every write (IRB compliance).
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, List
from decimal import Decimal

from app.core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.db.models import FinancialStatementRaw
from app.services.case_service import invalidate_case_pipeline

from app.services.audit_service import log_event
from app.schemas.financial_schema import FinancialStatementNestedOut, FinancialStatementNestedCreate

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cases",
    tags=["Financials"]
)


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.get("/{case_id}/financials", response_model=List[FinancialStatementNestedOut])
async def api_get_financials(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Returns all raw financial statements for a given case."""
    result = await db.execute(
        select(FinancialStatementRaw)
        .where(FinancialStatementRaw.case_id == case_id)
        .order_by(FinancialStatementRaw.fiscal_year.desc())
    )
    stmts = result.scalars().all()
    return [FinancialStatementNestedOut.from_orm_flat(s) for s in stmts]


from sqlalchemy.exc import IntegrityError, SQLAlchemyError


@router.post("/{case_id}/financials")
async def api_create_financial(
    case_id: uuid.UUID,
    body: FinancialStatementNestedCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Creates or updates a raw financial statement (upsert by case_id + fiscal_year)."""
    from app.services.workflow_guards import assert_gate_passed
    await assert_gate_passed(case_id=case_id, db=db)

    try:
        data = body.to_flat_dict()

        from app.services.financial_service import upsert_financial_statement
        stmt_id, event_type = await upsert_financial_statement(
            case_uuid=case_id,
            fiscal_year=body.fiscal_year,
            data=data,
            db=db
        )

        await log_event(
            db=db,
            event_type=event_type,
            entity_type="FinancialStatementRaw",
            entity_id=str(stmt_id),
            case_id=str(case_id),
            description=f"Raw financial statement {body.fiscal_year} {'updated' if event_type == 'FINANCIAL_UPDATED' else 'created'}.",
            user_id=current_user.get("sub", "SYSTEM")
        )

        logger.info(f"Financial statement {body.fiscal_year} {'updated' if event_type == 'FINANCIAL_UPDATED' else 'created'} for case {case_id}")
        return {"statement_id": str(stmt_id), "event": event_type}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Financial statement conflict or duplicate.")
    except Exception as e:
        await db.rollback()
        logger.exception("Unexpected DB error")
        raise HTTPException(status_code=500, detail="Internal processing error.")


@router.delete("/{case_id}/financials/{statement_id}")
async def api_delete_financial(
    case_id: uuid.UUID,
    statement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Deletes a raw financial statement."""
    from app.services.financial_service import delete_financial_statement
    await delete_financial_statement(case_uuid=case_id, statement_id=statement_id, db=db)

    # <-- FIX P1-AUDIT-02
    await log_event(
        db=db,
        event_type="FINANCIAL_DELETED",
        entity_type="FinancialStatementRaw",
        entity_id=str(statement_id),
        case_id=str(case_id),
        description="Raw financial statement deleted.",
        user_id=current_user.get("sub", "SYSTEM")
    )

    logger.info(f"Financial statement {statement_id} deleted for case {case_id}")
    return {"status": "deleted", "statement_id": str(statement_id)}
