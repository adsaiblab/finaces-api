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

# AJOUTER CET IMPORT :
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cases",
    tags=["Financials"]
)


# ─────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────

class FinancialStatementCreate(BaseModel):
    """
    Ingestion payload for a raw financial statement.
    Keys map directly to FinancialStatementRaw ORM model columns.
    """
    fiscal_year: int = Field(..., ge=1900, le=2100)
    currency_original: str = Field("USD", min_length=3, max_length=3)  # ISO 4217
    referentiel: Optional[str] = Field(None, max_length=10)
    exchange_rate_to_usd: Optional[Decimal] = Field(default=Decimal("1.0"), ge=Decimal("0.0"))

    # ── Assets ───────────────────────────────────────────────────────
    total_assets: Optional[Decimal] = None
    current_assets: Optional[Decimal] = None
    liquid_assets: Optional[Decimal] = None
    inventory: Optional[Decimal] = None
    accounts_receivable: Optional[Decimal] = None
    other_current_assets: Optional[Decimal] = None
    non_current_assets: Optional[Decimal] = None
    intangible_assets: Optional[Decimal] = None
    tangible_assets: Optional[Decimal] = None
    financial_assets: Optional[Decimal] = None

    # ── Liabilities & Equity ──────────────────────────────────────
    total_liabilities_and_equity: Optional[Decimal] = None
    equity: Optional[Decimal] = None
    share_capital: Optional[Decimal] = None
    reserves: Optional[Decimal] = None
    retained_earnings_prior: Optional[Decimal] = None
    current_year_earnings: Optional[Decimal] = None
    non_current_liabilities: Optional[Decimal] = None
    long_term_debt: Optional[Decimal] = None
    long_term_provisions: Optional[Decimal] = None
    current_liabilities: Optional[Decimal] = None
    short_term_debt: Optional[Decimal] = None
    accounts_payable: Optional[Decimal] = None
    tax_and_social_liabilities: Optional[Decimal] = None
    other_current_liabilities: Optional[Decimal] = None

    # ── Income Statement ──────────────────────────────────────────────
    revenue: Optional[Decimal] = None
    sold_production: Optional[Decimal] = None
    other_operating_revenue: Optional[Decimal] = None
    cost_of_goods_sold: Optional[Decimal] = None
    external_expenses: Optional[Decimal] = None
    personnel_expenses: Optional[Decimal] = None
    taxes_and_duties: Optional[Decimal] = None
    depreciation_and_amortization: Optional[Decimal] = None
    other_operating_expenses: Optional[Decimal] = None
    operating_income: Optional[Decimal] = None
    financial_revenue: Optional[Decimal] = None
    financial_expenses: Optional[Decimal] = None
    financial_income: Optional[Decimal] = None
    income_before_tax: Optional[Decimal] = None
    extraordinary_income: Optional[Decimal] = None
    income_tax: Optional[Decimal] = None
    net_income: Optional[Decimal] = None
    ebitda: Optional[Decimal] = None

    # ── Cash Flows ────────────────────────────────────────────────────
    operating_cash_flow: Optional[Decimal] = None
    investing_cash_flow: Optional[Decimal] = None
    financing_cash_flow: Optional[Decimal] = None
    change_in_cash: Optional[Decimal] = None
    beginning_cash: Optional[Decimal] = None
    ending_cash: Optional[Decimal] = None

    # ── Supplementary information ─────────────────────────────────
    headcount: Optional[int] = None
    backlog_value: Optional[Decimal] = None
    dividends_distributed: Optional[Decimal] = None
    capex: Optional[Decimal] = None
    is_consolidated: Optional[int] = 0
    source_notes: str = Field("", max_length=2000)

    # ─────────────────────────────────────────────────────────────
    # Pydantic V2 balance sheet guard (F-1.4)
    # ─────────────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _check_balance_sheet(self):
        # F-1.4a — Revenue cannot be negative
        if self.revenue is not None and self.revenue < 0:
            raise ValueError("Revenue cannot be negative.")

        # F-1.4b — Balance sheet equilibrium (when totals are provided)
        a = self.total_assets
        p = self.total_liabilities_and_equity
        if a is not None and p is not None:
            if abs(a - p) >= Decimal("1.0"):
                raise ValueError(
                    f"Unbalanced balance sheet: Total Assets ({a:.2f}) ≠ "
                    f"Total Liabilities & Equity ({p:.2f}) "
                    f"(diff {abs(a - p):.2f})."
                )
        return self


class FinancialStatementRawOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    fiscal_year: int
    currency_original: Optional[str] = None
    exchange_rate_to_usd: Optional[Decimal] = None
    total_assets: Optional[Decimal] = None
    current_assets: Optional[Decimal] = None
    equity: Optional[Decimal] = None
    revenue: Optional[Decimal] = None
    net_income: Optional[Decimal] = None
    ebitda: Optional[Decimal] = None
    operating_cash_flow: Optional[Decimal] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.get("/{case_id}/financials", response_model=List[FinancialStatementRawOut])
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
    return result.scalars().all()


from sqlalchemy.exc import IntegrityError, SQLAlchemyError


@router.post("/{case_id}/financials")
async def api_create_financial(
    case_id: uuid.UUID,
    body: FinancialStatementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Creates or updates a raw financial statement (upsert by case_id + fiscal_year)."""
    try:
        data = body.model_dump(exclude_unset=True)

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
