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
            rate = float(schema.exchange_rate or 1)

            def _f(val) -> float:
                return float(val or 0)

            def _raw_or_reverse(raw_val, usd_schema_val) -> float:
                """Read from raw; if null (aggregate field), reverse from USD using exchange rate."""
                v = _f(raw_val)
                if v == 0 and usd_schema_val:
                    v = _f(usd_schema_val) * rate
                return v

            # ── Leaf fields: directly read from raw (source currency) ───────
            liquid     = _f(raw.liquid_assets)
            inventory  = _f(raw.inventory)
            accounts_r = _f(raw.accounts_receivable)
            other_ca   = _f(raw.other_current_assets)
            intangible = _f(raw.intangible_assets)
            tangible   = _f(raw.tangible_assets)
            fin_assets = _f(raw.financial_assets)
            other_nca  = _f(getattr(raw, 'other_noncurrent_assets', None))

            schema.liquid_assets_original           = liquid
            schema.inventory_original               = inventory
            schema.accounts_receivable_original     = accounts_r
            schema.other_current_assets_original    = other_ca
            schema.intangible_assets_original       = intangible
            schema.tangible_assets_original         = tangible
            schema.financial_assets_original        = fin_assets
            schema.other_noncurrent_assets_original = other_nca

            # ── Aggregate totals: bottom-up (mirrors engine logic) ──────────
            cur_assets_raw = _f(raw.current_assets) or (liquid + inventory + accounts_r + other_ca)
            non_cur_assets_raw = _f(raw.non_current_assets) or (intangible + tangible + fin_assets + other_nca)
            schema.current_assets_original          = cur_assets_raw
            schema.non_current_assets_original      = non_cur_assets_raw
            schema.total_assets_original            = _f(raw.total_assets) or (cur_assets_raw + non_cur_assets_raw)

            # Equity components
            schema.share_capital_original           = _f(raw.share_capital)
            schema.reserves_original                = _f(raw.reserves)
            schema.retained_earnings_prior_original = _f(raw.retained_earnings_prior)
            schema.current_year_earnings_original   = _f(raw.current_year_earnings)
            equity_raw = _f(raw.equity) or (_f(raw.share_capital) + _f(raw.reserves) + _f(raw.retained_earnings_prior) + _f(raw.current_year_earnings))
            schema.equity_original = equity_raw

            # Liabilities
            schema.long_term_debt_original          = _f(raw.long_term_debt)
            schema.long_term_provisions_original    = _f(raw.long_term_provisions)
            ncl_raw = _f(raw.non_current_liabilities) or (_f(raw.long_term_debt) + _f(raw.long_term_provisions))
            schema.non_current_liabilities_original = ncl_raw

            schema.accounts_payable_original        = _f(raw.accounts_payable)
            schema.short_term_debt_original         = _f(raw.short_term_debt)
            schema.tax_and_social_liabilities_original = _f(raw.tax_and_social_liabilities)
            schema.other_current_liabilities_original  = _f(raw.other_current_liabilities)
            cl_raw = _f(raw.current_liabilities) or (_f(raw.short_term_debt) + _f(raw.accounts_payable) + _f(raw.tax_and_social_liabilities) + _f(raw.other_current_liabilities))
            schema.current_liabilities_original     = cl_raw

            tle_raw = _f(raw.total_liabilities_and_equity) or (equity_raw + ncl_raw + cl_raw)
            schema.total_liabilities_and_equity_original = tle_raw

            # Income Statement
            schema.revenue_original                        = _f(raw.revenue)
            schema.sold_production_original                = _f(raw.sold_production)
            schema.other_operating_revenue_original        = _f(raw.other_operating_revenue)
            schema.cost_of_goods_sold_original             = _f(raw.cost_of_goods_sold)
            schema.personnel_expenses_original             = _f(raw.personnel_expenses)
            schema.depreciation_and_amortization_original  = _f(raw.depreciation_and_amortization)
            schema.financial_revenue_original              = _f(raw.financial_revenue)
            schema.financial_expenses_original             = _f(raw.financial_expenses)
            schema.income_before_tax_original              = _f(raw.income_before_tax)
            schema.operating_income_original               = _f(raw.operating_income)
            schema.net_income_original                     = _f(raw.net_income)
            schema.ebitda_original                         = _f(raw.ebitda)

            # Cash Flow
            schema.operating_cash_flow_original  = _f(getattr(raw, 'operating_cash_flow', None))
            schema.investing_cash_flow_original  = _f(getattr(raw, 'investing_cash_flow', None))
            schema.financing_cash_flow_original  = _f(getattr(raw, 'financing_cash_flow', None))
            schema.change_in_cash_original       = _f(getattr(raw, 'change_in_cash', None))
            schema.beginning_cash_original       = _f(getattr(raw, 'beginning_cash', None))
            schema.ending_cash_original          = _f(getattr(raw, 'ending_cash', None))
            schema.capex_original                = _f(raw.capex) if raw.capex else None

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
