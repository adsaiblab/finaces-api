"""
app/services/comparison_service.py
FinaCES V1.2 — Comparison and Benchmarking Engine (Async Migration)

RISK_PRIORITY and SECTOR_BENCHMARKS business constants kept identical.
All functions are now async and use the injected db:AsyncSession.
"""

import json
import uuid
import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db.models import (
    EvaluationCase, Scorecard, RatioSet, Bidder, ComparisonSession
)
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# BUSINESS CONSTANTS (kept identical)
# ════════════════════════════════════════════════════════════════

# Priority for Risk Ranking (Competition of solidity, not beauty)
RISK_PRIORITY: Dict[str, int] = {
    "FAIBLE":   4,
    "MODERE":   3,
    "ELEVE":    2,
    "CRITIQUE": 1,
    "N/A":      0,
}

# Simplified benchmarks (based on benchmarks_sectorials.md)
SECTOR_BENCHMARKS: Dict[str, Dict] = {
    "BTP": {
        "debt_to_equity": {"max_tolerated": 4.0,   "name": "Endettement (D/E)"},
        "dso_days":       {"max_tolerated": 150.0,  "name": "Days Sales Outstanding (DSO)"},
        "marge_nette":    {"min_tolerated": 0.5,    "name": "Marge Nette (%)"},
    },
    "SERVICES": {
        "debt_to_equity": {"max_tolerated": 2.0,   "name": "Endettement (D/E)"},
        "dso_days":       {"max_tolerated": 120.0,  "name": "Days Sales Outstanding (DSO)"},
        "marge_nette":    {"min_tolerated": 1.0,    "name": "Marge Nette (%)"},
    },
    "DEFAULT": {
        "debt_to_equity": {"max_tolerated": 3.0,   "name": "Endettement (D/E)"},
        "dso_days":       {"max_tolerated": 120.0,  "name": "Days Sales Outstanding (DSO)"},
        "marge_nette":    {"min_tolerated": 1.0,    "name": "Marge Nette (%)"},
    },
}


# ════════════════════════════════════════════════════════════════
# 1. ANALYSE TEMPORELLE (AXE 1)
# ════════════════════════════════════════════════════════════════

async def compare_temporal(case_id: str, db: AsyncSession) -> Dict[str, Any]:
    """
    Analyzes the evolution of the ratios of a file over several years.
    Detects trends and dynamic risks (e.g. debt hypergrowth).
    """
    try:
        if not case_id:
            return {"status": "EMPTY", "message": "Insufficient data"}

        result = await db.execute(
            select(RatioSet)
            .where(RatioSet.case_id == uuid.UUID(case_id))
            .order_by(RatioSet.fiscal_year.asc())
        )
        ratios = result.scalars().all()

        if not ratios:
            return {"status": "NO_DATA", "message": "Aucun ratio disponible pour l'analyse temporelle."}

        years_data = {}
        for r in ratios:
            years_data[r.fiscal_year] = {
                "current_ratio":  r.current_ratio,
                "debt_to_equity": r.debt_to_equity,
                "marge_nette":    r.marge_nette,
                "caf":            r.caf if hasattr(r, "caf") else None,
            }

        trend = "INSUFFISANT"
        risk_alerts: list = []

        if len(ratios) >= 2:
            first_year = ratios[0]
            last_year  = ratios[-1]

            # Margin trend calculation
            y_marge = [r.marge_nette for r in ratios if r.marge_nette is not None]
            if len(y_marge) == len(ratios) and len(y_marge) >= 2:
                # Simple linear regression (slope via least squares)
                n   = len(y_marge)
                x   = list(range(n))
                x_m = sum(x) / n
                y_m = sum(y_marge) / n
                num = sum((xi - x_m) * (float(yi) - y_m) for xi, yi in zip(x, y_marge))
                den = sum((xi - x_m) ** 2 for xi in x) or 1
                slope_marge = num / den
                if slope_marge >= 0.5:
                    trend = "PROGRESSION"
                elif slope_marge <= -0.5:
                    trend = "DEGRADATION"
                else:
                    trend = "STABLE"

            # Debt Hypergrowth Alert (MCC Expert Rule)
            if last_year.debt_to_equity is not None and first_year.debt_to_equity is not None:
                val_n1 = first_year.debt_to_equity
                if val_n1 and val_n1 != 0:
                    growth_debt = (float(last_year.debt_to_equity) - float(val_n1)) / float(val_n1)
                    if growth_debt > 0.5 and float(last_year.debt_to_equity) > 2.0:
                        risk_alerts.append(
                            f"⚠️ Rapid degradation of the financial structure: "
                            f"the D/E ratio has increased by {growth_debt:.0%}."
                        )

        return {
            "status":              "OK",
            "case_id":             case_id,
            "years_covered":       list(years_data.keys()),
            "data":                years_data,
            "trend":               trend,
            "dynamic_risk_alerts": risk_alerts,
        }

    except Exception as exc:
        logger.error(f"TEMPORAL ENGINE CRASH [{case_id}]: {exc}")
        from app.exceptions.finaces_exceptions import EngineComputationError
        raise EngineComputationError("Temporal analysis failed due to an internal error.") from exc


# ════════════════════════════════════════════════════════════════
# 2. ANALYSE COMPARATIVE / RISK RANKING (AXE 2)
# ════════════════════════════════════════════════════════════════

async def compare_by_market(
    market_ref:       str,
    db:               AsyncSession,
    specific_case_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compares bidders in the same call for tenders.
    Applique le "Risk Ranking" : Tri par classe de risque fiduciaire, puis par score.
    """
    query = select(EvaluationCase).where(EvaluationCase.market_reference == market_ref)
    if specific_case_ids:
        uuids = [uuid.UUID(cid) for cid in specific_case_ids]
        query = query.where(EvaluationCase.id.in_(uuids))

    cases_result = await db.execute(query)
    cases = cases_result.scalars().all()

    candidates = []
    for case in cases:
        # Bidder — SSOT
        bidder_name = "Inconnu"
        if case.bidder_id:
            bidder_result = await db.execute(
                select(Bidder).where(Bidder.id == case.bidder_id)
            )
            bidder = bidder_result.scalars().first()
            if bidder:
                bidder_name = bidder.name

        # Most recent scorecard
        sc_result = await db.execute(
            select(Scorecard)
            .where(Scorecard.case_id == case.id)
            .order_by(desc(Scorecard.computed_at))
            .limit(1)
        )
        scorecard = sc_result.scalars().first()

        if scorecard:
            risk_class     = scorecard.risk_class.value if hasattr(scorecard.risk_class, "value") else (scorecard.risk_class or "N/A")
            score          = float(scorecard.score_global or 0.0)
            overrides_json = scorecard.overrides_applied_json
            scores_piliers = {
                "liquidite":   round(float(scorecard.score_liquidity   or 0) * 20, 0), 
                "solvabilite": round(float(scorecard.score_solvency    or 0) * 20, 0), 
                "rentabilite": round(float(scorecard.score_profitability or 0) * 20, 0), 
                "capacite":    round(float(scorecard.score_capacity    or 0) * 20, 0), 
            }
        else:
            risk_class     = "N/A"
            score          = 0.0
            overrides_json = "[]"
            scores_piliers = {"liquidite": 0.0, "solvabilite": 0.0, "rentabilite": 0.0, "capacite": 0.0}

        # Overrides check (transparency)
        try:
            overrides = json.loads(overrides_json) if isinstance(overrides_json, str) else (overrides_json or [])
        except Exception:
            overrides = []
        has_manual_override = any(o.get("type") in ["MANUAL_UPGRADE", "MANUAL_DOWNGRADE"] for o in overrides)

        # Temporal ratios last year N
        ratio_result = await db.execute(
            select(RatioSet)
            .where(RatioSet.case_id == case.id)
            .order_by(desc(RatioSet.fiscal_year))
            .limit(1)
        )
        ratio_set = ratio_result.scalars().first()
        ratios_bruts = {}
        if ratio_set:
            ratios_bruts = {
                "current_ratio":  ratio_set.current_ratio,
                "debt_to_equity": ratio_set.debt_to_equity,
                "marge_nette":    ratio_set.marge_nette,
            }

        candidates.append({
            "case_id":                        str(case.id),
            "bidder_name":                    bidder_name,
            "risk_class":                     risk_class,
            "score_global":                   round(score, 3),
            "scores_piliers":                 scores_piliers,
            "has_manual_override":            has_manual_override,
            "indicateurs_financiers_bruts":   ratios_bruts,
            "risk_priority":                  RISK_PRIORITY.get(risk_class, 0),
        })

    # Tri Risk Ranking : classe de risque (FAIBLE > MODERE > ELEVE > CRITIQUE), puis score
    candidates.sort(key=lambda x: (x["risk_priority"], x["score_global"]), reverse=True)

    for idx, cand in enumerate(candidates):
        cand["risk_rank"] = idx + 1
        del cand["risk_priority"]

    return {
        "market_ref":                  market_ref,
        "total_candidates_evaluated":  len(candidates),
        "candidates":                  candidates,
        "generated_at":                datetime.now(timezone.utc),
    }


# ════════════════════════════════════════════════════════════════
# 3. BENCHMARKS SECTORIELS (AXE 3)
# ════════════════════════════════════════════════════════════════

async def compute_sector_benchmark(case_id: str, db: AsyncSession) -> Dict[str, Any]:
    """
    Compares a candidate's latest RatioSet with industry standards.
    """
    if not case_id:
        return {"status": "EMPTY", "message": "Insufficient data"}

    case_result = await db.execute(
        select(EvaluationCase).where(EvaluationCase.id == uuid.UUID(case_id))
    )
    case = case_result.scalars().first()
    if not case:
        return {"status": "ERROR", "message": "Case not found."}

    # Secteur via Bidder
    sector_key = "DEFAULT"
    if case.bidder_id:
        bidder_result = await db.execute(
            select(Bidder).where(Bidder.id == case.bidder_id)
        )
        bidder = bidder_result.scalars().first()
        if bidder and bidder.sector:
            sector_raw = bidder.sector.upper()
            if "BTP" in sector_raw or "CONSTRUCTION" in sector_raw or "TRAVAUX" in sector_raw:
                sector_key = "BTP"
            elif "SERVICE" in sector_raw or "CONSULTING" in sector_raw or "ETUDES" in sector_raw:
                sector_key = "SERVICES"

    benchmark = SECTOR_BENCHMARKS.get(sector_key, SECTOR_BENCHMARKS["DEFAULT"])

    ratio_result = await db.execute(
        select(RatioSet)
        .where(RatioSet.case_id == uuid.UUID(case_id))
        .order_by(desc(RatioSet.fiscal_year))
        .limit(1)
    )
    latest_ratio = ratio_result.scalars().first()

    if not latest_ratio:
        return {"status": "NO_DATA", "message": "Aucun ratio disponible pour le benchmark."}

    analysis: dict = {}

    if latest_ratio.debt_to_equity is not None:
        val     = float(latest_ratio.debt_to_equity)
        max_tol = benchmark["debt_to_equity"]["max_tolerated"]
        analysis["debt_to_equity"] = {
            "value": round(val, 2), "sector_max": max_tol,
            "statut": "HORS_NORME" if val > max_tol else "DANS_LA_NORME",
        }

    if latest_ratio.dso_days is not None:
        val     = float(latest_ratio.dso_days)
        max_tol = benchmark["dso_days"]["max_tolerated"]
        analysis["dso_days"] = {
            "value": round(val, 0), "sector_max": max_tol,
            "statut": "HORS_NORME" if val > max_tol else "DANS_LA_NORME",
        }

    if latest_ratio.marge_nette is not None:
        val     = float(latest_ratio.marge_nette)
        min_tol = benchmark["marge_nette"]["min_tolerated"]
        analysis["marge_nette"] = {
            "value": round(val, 2), "sector_min": min_tol,
            "statut": "HORS_NORME" if val < min_tol else "DANS_LA_NORME",
        }

    return {
        "status":             "OK",
        "case_id":            case_id,
        "secteur_detecte":    sector_key,
        "benchmark_analysis": analysis,
    }


# ════════════════════════════════════════════════════════════════
# 4. MANAGEMENT OF COMPARISON SESSIONS
# ════════════════════════════════════════════════════════════════

async def save_comparison_session(
    market_ref:  str,
    name:        str,
    case_ids:    List[str],
    db:          AsyncSession,
    created_by:  str = "Analyste",
) -> str:
    """
    Registers the intention to compare a specific group of candidates.
    Does not duplicate any financial data (SSOT).
    """
    new_session = ComparisonSession(
        id=uuid.uuid4(),
        market_ref=market_ref,
        name=name,
        created_by=created_by,
        case_ids_json=case_ids,   # JSONB — liste Python directement
    )
    db.add(new_session)
    try:
        await db.commit()
        await db.refresh(new_session)
        
        # ─ Audit Trail (MCC-Grade Compliance) ─────────────────────
        await log_event(
            db=db,
            event_type="COMPARISON_SESSION_CREATED",
            entity_type="ComparisonSession",
            entity_id=str(new_session.id),
            case_id=None,
            description=f"Comparison session '{name}' created for market {market_ref} with {len(case_ids)} cases"
        )
        
        return str(new_session.id)
    except Exception as exc:
        await db.rollback()
        raise exc
