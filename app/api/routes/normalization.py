from app.core.security import get_current_user
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from typing import List
import logging
import uuid as uuid_mod

from app.db.database import get_db
from app.services.normalization_service import process_normalization
from app.schemas.normalization_schema import FinancialStatementNormalizedSchema
from app.exceptions.finaces_exceptions import FinaCESBaseException

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/cases",
    tags=["Normalization Workflow"]
)

@router.post("/{case_id}/normalize", response_model=List[FinancialStatementNormalizedSchema])
async def api_normalize_case(case_id: UUID, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Starts the asynchronous normalization calculation for a given folder.
    The calculation is delegated to pure Engines without API I/O blocking.
    """
    try:
        normalized_statements = await process_normalization(case_id=case_id, db=db)
        return normalized_statements
        
    except FinaCESBaseException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected internal crash while processing Case UUID {case_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during normalization."
        )


@router.get("/{case_id}/normalized-financials", response_model=List[FinancialStatementNormalizedSchema])
async def get_normalized_financials(case_id: str, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Returns normalized financial statements for a case, enriched with coherence and ratio readiness.
    
    _original fields are reconstructed from FinancialStatementRaw (source MAD values)
    since the normalized table only stores USD-converted values.
    """
    from app.db.models import FinancialStatementNormalized, FinancialStatementRaw
    from app.schemas.normalization_schema import BalanceSheetCoherence, RatioReadiness, AdjustmentOut

    # Fetch raw statements indexed by id for O(1) lookup
    raw_result = await db.execute(
        select(FinancialStatementRaw).where(FinancialStatementRaw.case_id == uuid_mod.UUID(case_id))
    )
    raw_stmts = {r.id: r for r in raw_result.scalars().all()}

    if not raw_stmts:
        return []

    result = await db.execute(
        select(FinancialStatementNormalized).where(
            FinancialStatementNormalized.raw_statement_id.in_(list(raw_stmts.keys()))
        )
    )
    statements = result.scalars().all()

    # Post-processing : enrichissement de chaque bilan normalisé
    enriched = []
    for stmt in statements:
        schema = FinancialStatementNormalizedSchema.model_validate(stmt)

        # ── Reconstruction des valeurs _original depuis FinancialStatementRaw ──
        # La table normalized ne stocke que les USD. Les valeurs MAD viennent du raw.
        raw = raw_stmts.get(stmt.raw_statement_id)
        if raw:
            schema.currency_original = raw.currency_original or "MAD"
            schema.total_assets_original = float(raw.total_assets or 0)
            schema.current_assets_original = float(raw.current_assets or 0)
            schema.liquid_assets_original = float(raw.liquid_assets or 0)
            schema.inventory_original = float(raw.inventory or 0)
            schema.accounts_receivable_original = float(raw.accounts_receivable or 0)
            schema.other_current_assets_original = float(raw.other_current_assets or 0)
            schema.non_current_assets_original = float(raw.non_current_assets or 0)
            schema.intangible_assets_original = float(raw.intangible_assets or 0)
            schema.tangible_assets_original = float(raw.tangible_assets or 0)
            schema.financial_assets_original = float(raw.financial_assets or 0)
            schema.other_noncurrent_assets_original = float(getattr(raw, 'other_noncurrent_assets', None) or 0)
            schema.total_liabilities_and_equity_original = float(raw.total_liabilities_and_equity or 0)
            schema.equity_original = float(raw.equity or 0)
            schema.share_capital_original = float(raw.share_capital or 0)
            schema.reserves_original = float(raw.reserves or 0)
            schema.retained_earnings_prior_original = float(raw.retained_earnings_prior or 0)
            schema.current_year_earnings_original = float(raw.current_year_earnings or 0)
            schema.non_current_liabilities_original = float(raw.non_current_liabilities or 0)
            schema.long_term_debt_original = float(raw.long_term_debt or 0)
            schema.long_term_provisions_original = float(raw.long_term_provisions or 0)
            schema.current_liabilities_original = float(raw.current_liabilities or 0)
            schema.short_term_debt_original = float(raw.short_term_debt or 0)
            schema.accounts_payable_original = float(raw.accounts_payable or 0)
            schema.tax_and_social_liabilities_original = float(raw.tax_and_social_liabilities or 0)
            schema.other_current_liabilities_original = float(raw.other_current_liabilities or 0)
            schema.revenue_original = float(raw.revenue or 0)
            schema.sold_production_original = float(raw.sold_production or 0)
            schema.other_operating_revenue_original = float(raw.other_operating_revenue or 0)
            schema.cost_of_goods_sold_original = float(raw.cost_of_goods_sold or 0)
            schema.personnel_expenses_original = float(raw.personnel_expenses or 0)
            schema.depreciation_and_amortization_original = float(raw.depreciation_and_amortization or 0)
            schema.financial_revenue_original = float(raw.financial_revenue or 0)
            schema.financial_expenses_original = float(raw.financial_expenses or 0)
            schema.income_before_tax_original = float(raw.income_before_tax or 0)
            schema.operating_income_original = float(raw.operating_income or 0)
            schema.net_income_original = float(raw.net_income or 0)
            schema.ebitda_original = float(raw.ebitda or 0)
            schema.operating_cash_flow_original = float(getattr(raw, 'operating_cash_flow', None) or 0)
            schema.investing_cash_flow_original = float(getattr(raw, 'investing_cash_flow', None) or 0)
            schema.financing_cash_flow_original = float(getattr(raw, 'financing_cash_flow', None) or 0)
            schema.change_in_cash_original = float(getattr(raw, 'change_in_cash', None) or 0)
            schema.beginning_cash_original = float(getattr(raw, 'beginning_cash', None) or 0)
            schema.ending_cash_original = float(getattr(raw, 'ending_cash', None) or 0)
            schema.capex_original = float(raw.capex or 0) if raw.capex else None

        # ── Mission 5 : Cohérence bilan ─────────────────────────────────
        total_a = float(schema.total_assets or 0)
        total_le = float(schema.total_liabilities_and_equity or 0)
        bal = abs(total_a - total_le) / max(total_a, 1) < 0.001 if total_a > 0 else False

        ebitda_val = float(schema.ebitda or 0)
        oi = float(schema.operating_income or 0)
        da = float(schema.depreciation_and_amortization or 0)
        ebitda_ok = abs(ebitda_val - (oi + da)) / max(abs(ebitda_val), 1) < 0.05 if ebitda_val != 0 else True

        end_cash = float(schema.ending_cash or 0)
        beg_cash = float(schema.beginning_cash or 0)
        chg = float(schema.change_in_cash or 0)
        cf_ok = abs(end_cash - (beg_cash + chg)) < 1.0

        score = sum([bal, ebitda_ok, cf_ok]) / 3.0
        schema.coherence = BalanceSheetCoherence(
            assets_liabilities_balanced=bal,
            ebitda_coherent=ebitda_ok,
            cash_flow_coherent=cf_ok,
            coherence_score=round(score, 2),
        )

        # ── Mission 6 : Certification ratios ────────────────────────────
        advanced_fields = {
            "accounts_receivable": schema.accounts_receivable,
            "accounts_payable": schema.accounts_payable,
            "operating_cash_flow": schema.operating_cash_flow,
            "personnel_expenses": schema.personnel_expenses,
            "depreciation_and_amortization": schema.depreciation_and_amortization,
            "financial_expenses": schema.financial_expenses,
            "cost_of_goods_sold": schema.cost_of_goods_sold,
            "revenue": schema.revenue,
        }
        missing = [k for k, v in advanced_fields.items() if not v or float(v) == 0]
        basic_fields = ["total_assets", "equity", "revenue", "net_income"]
        basic_missing = [f for f in basic_fields if not getattr(schema, f, None)]
        schema.ratio_readiness = RatioReadiness(
            basic_ratios_ready=len(basic_missing) == 0,
            advanced_ratios_ready=len(missing) == 0,
            missing_fields=missing,
        )

        # ── Mission 3 : Ajustements ─────────────────────────────────────
        # Les ajustements sont stockés dans AdjustmentSchema (tables distinctes)
        # Pour l'instant, la liste reste vide — sera peuplée lors d'un sprint dédié
        # quand la table normalization_adjustments sera disponible
        schema.adjustments = []
        schema.adjustments_count = 0

        enriched.append(schema)

    return enriched
