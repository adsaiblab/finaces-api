import uuid
import logging
from decimal import Decimal
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.db.models import FinancialStatementRaw
from app.services.case_service import invalidate_case_pipeline

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# PURE AGGREGATES CALCULATOR — Single Source of Truth
# Called once before every DB write. No DB access. No HTTP logic.
# ════════════════════════════════════════════════════════════════

def _d(value) -> Optional[Decimal]:
    """Safe cast to Decimal, returns None if value is None."""
    return Decimal(str(value)) if value is not None else None

def _sum(*values) -> Optional[Decimal]:
    """Sum non-None Decimals. Returns None if ALL values are None."""
    parts = [_d(v) for v in values if v is not None]
    return sum(parts) if parts else None

def calculate_financial_aggregates(data: dict) -> dict:
    """
    Calculates all financial aggregates from atomic fields.
    Overwrites only the fields that CAN be derived — never overwrites
    a field that was explicitly provided by the user AND cannot be verified.
    
    Rule: if a total was sent by the frontend, it is REPLACED by the
    backend calculation to guarantee mathematical integrity.
    """
    d = data  # shorthand

    # ── A. BALANCE SHEET — ASSETS ─────────────────────────────────────
    non_current_assets = _sum(
        d.get("intangible_assets"),
        d.get("tangible_assets"),
        d.get("financial_assets"),
        d.get("other_noncurrent_assets"),
    )
    current_assets = _sum(
        d.get("liquid_assets"),
        d.get("inventory"),
        d.get("accounts_receivable"),
        d.get("other_current_assets"),
    )
    total_assets = _sum(non_current_assets, current_assets)

    if non_current_assets is not None:
        d["non_current_assets"] = non_current_assets
    if current_assets is not None:
        d["current_assets"] = current_assets
    if total_assets is not None:
        d["total_assets"] = total_assets

    # ── B. BALANCE SHEET — LIABILITIES & EQUITY ──────────────────────
    equity = _sum(
        d.get("share_capital"),
        d.get("reserves"),
        d.get("retained_earnings_prior"),
        d.get("current_year_earnings"),
    )
    non_current_liabilities = _sum(
        d.get("long_term_debt"),
        d.get("long_term_provisions"),
    )
    current_liabilities = _sum(
        d.get("short_term_debt"),
        d.get("accounts_payable"),
        d.get("tax_and_social_liabilities"),
        d.get("other_current_liabilities"),
    )
    total_liabilities_and_equity = _sum(equity, non_current_liabilities, current_liabilities)

    if equity is not None:
        d["equity"] = equity
    if non_current_liabilities is not None:
        d["non_current_liabilities"] = non_current_liabilities
    if current_liabilities is not None:
        d["current_liabilities"] = current_liabilities
    if total_liabilities_and_equity is not None:
        d["total_liabilities_and_equity"] = total_liabilities_and_equity

    # ── C. INCOME STATEMENT (P&L) ─────────────────────────────────────
    gross_revenue = _sum(
        d.get("revenue"),
        d.get("sold_production"),
        d.get("other_operating_revenue"),
    )
    total_operating_charges = _sum(
        d.get("cost_of_goods_sold"),
        d.get("external_expenses"),
        d.get("personnel_expenses"),
        d.get("taxes_and_duties"),
        d.get("depreciation_and_amortization"),
        d.get("other_operating_expenses"),
    )

    operating_income = None
    if gross_revenue is not None and total_operating_charges is not None:
        operating_income = gross_revenue - total_operating_charges

    ebitda = None
    dna = _d(d.get("depreciation_and_amortization"))
    if operating_income is not None and dna is not None:
        ebitda = operating_income + dna
    elif operating_income is not None:
        ebitda = operating_income  # fallback if D&A not provided

    # financial_income = saisie directe utilisateur (produits financiers)
    # financial_expenses = saisie directe utilisateur (charges financières)
    # net_financial_result = financial_income - financial_expenses (calculé, NON persisté)
    fin_income = _d(d.get("financial_income"))
    fin_exp = _d(d.get("financial_expenses"))

    # On préserve financial_income tel quel en DB — c'est une saisie pure
    # net_financial_result est uniquement utilisé pour calculer income_before_tax
    net_financial_result = None
    if fin_income is not None or fin_exp is not None:
        net_financial_result = (fin_income or Decimal("0")) - (fin_exp or Decimal("0"))

    income_before_tax = None
    if operating_income is not None:
        income_before_tax = operating_income + (net_financial_result or Decimal("0"))
        extraordinary = _d(d.get("extraordinary_income"))
        if extraordinary is not None:
            income_before_tax += extraordinary

    net_income = None
    if income_before_tax is not None:
        tax = _d(d.get("income_tax")) or Decimal("0")
        net_income = income_before_tax - tax

    if operating_income is not None:
        d["operating_income"] = operating_income
    if ebitda is not None:
        d["ebitda"] = ebitda
    if income_before_tax is not None:
        d["income_before_tax"] = income_before_tax
    if net_income is not None:
        d["net_income"] = net_income

    # ── D. CASH FLOW ──────────────────────────────────────────────────
    # operating_cash_flow is directly entered by user — not calculated
    # change_in_cash = operating + investing + financing
    # ending_cash = beginning_cash + change_in_cash
    cfo = _d(d.get("operating_cash_flow"))
    cfi = _d(d.get("investing_cash_flow"))
    cff = _d(d.get("financing_cash_flow"))
    beg_cash = _d(d.get("beginning_cash"))

    chic = None
    if cfo is not None or cfi is not None or cff is not None:
        chic = (cfo or Decimal("0")) + (cfi or Decimal("0")) + (cff or Decimal("0"))
        d["change_in_cash"] = chic

    if beg_cash is not None or chic is not None:
        d["ending_cash"] = (beg_cash or Decimal("0")) + (chic or Decimal("0"))

    return d


# ════════════════════════════════════════════════════════════════
# SERVICE
# ════════════════════════════════════════════════════════════════

async def upsert_financial_statement(
    case_uuid: uuid.UUID,
    fiscal_year: int,
    data: dict,
    db: AsyncSession
) -> tuple[uuid.UUID, str]:

    result = await db.execute(
        select(FinancialStatementRaw).where(
            FinancialStatementRaw.case_id == case_uuid,
            FinancialStatementRaw.fiscal_year == fiscal_year,
        )
    )
    existing_stmt = result.scalars().first()

    # [IRB] Purge downstream calculations BEFORE modifying the raw data
    await invalidate_case_pipeline(case_uuid, db)

    # [AGGREGATES] Calculate all totals server-side before persistence
    data = calculate_financial_aggregates(data)

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


async def delete_financial_statement(
    case_uuid: uuid.UUID,
    statement_id: uuid.UUID,
    db: AsyncSession
):
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