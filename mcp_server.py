"""
FEW Solo V2.0 — Serveur MCP (Cerveau Gauche)
Expose les moteurs d'intelligence financière au format READ via Model Context Protocol.
"""
import sys
import os
import json
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# Path setup to import from FEW Solo codebase
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.database import async_session_maker
from app.db.models import (
    EvaluationCase, Bidder, RatioSet, ContractCapacityAssessment,
    Scorecard, Consortium, ConsortiumMember, ConsortiumResult,
    MCCGradeReport, DueDiligenceCheck,
    ExpertInterpretation, OverrideDecision,
    FinancialStatementRaw, IAPrediction, IATension
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Instance du serveur FastMCP
mcp = FastMCP("FEW-Solo-Broker")

# --- CONTEXT MANAGER DB SESSIONS ---
@asynccontextmanager
async def get_async_db_context():
    """Fournit une session DB transactionnelle sûre."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e


# --- OUTILS READ ---

@mcp.tool()
async def read_case_summary(case_id: str) -> str:
    """PREMIER APPEL OBLIGATOIRE. Retourne le contexte du dossier d'évaluation : identité du soumissionnaire (nom, secteur, pays), paramètres du contrat (valeur en devise locale, durée en mois), type de dossier (SINGLE ou CONSORTIUM), et état d'avancement (DRAFT → FINAL). Utilise ce retour pour déterminer le workflow (SINGLE vs CONSORTIUM) et la devise de tous les montants."""
    try:
        async with get_async_db_context() as db:
            case = (await db.execute(select(EvaluationCase).where(EvaluationCase.id == case_id))).scalars().first()
            if not case:
                return json.dumps({"error": f"Case ID {case_id} not found."})
            
            result = {
                "case_id": case.id,
                "case_type": case.case_type,
                "contract": {
                    "value": case.contract_value,
                    "months": case.contract_duration_months,
                    "currency": case.contract_currency
                },
                "state": case.status,
                "policy_version": case.policy_version_id
            }

            if case.case_type == "SINGLE" and case.bidder:
                result["bidder"] = {
                    "name": case.bidder.name,
                    "sector": case.bidder.sector,
                    "country": case.bidder.country
                }
            elif case.case_type == "CONSORTIUM" and case.consortium:
                result["consortium"] = {
                    "name": case.consortium.name,
                    "jv_type": case.consortium.jv_type
                }
                
            return json.dumps(result)
            
    except Exception as e:
        return json.dumps({"error": f"Erreur interne: {str(e)}"})


@mcp.tool()
async def read_financial_ratios(case_id: str, fiscal_year: Optional[int] = None) -> str:
    """Retourne les 25+ ratios financiers calculés pour chaque exercice fiscal. Inclut le Z-Score Altman (modèle EM à 4 variables) et sa zone de risque (SAFE/GREY/DISTRESS). ATTENTION : les montants (BFR, CAF, fonds_de_roulement) sont en UNITÉS MONÉTAIRES (pas en milliers ni millions). Les pourcentages (marge_nette, ebitda_margin, roa, roe, bfr_pct_ca) sont déjà multipliés par 100 (ex: 12.5 = 12.5%). Les ratios purs (current_ratio, debt_to_equity, gearing) sont en valeur décimale."""
    try:
        async with get_async_db_context() as db:
            query = select(RatioSet).where(RatioSet.case_id == case_id)
            if fiscal_year is not None:
                query = query.where(RatioSet.fiscal_year == fiscal_year)
                
            ratios = (await db.execute(query.order_by(RatioSet.fiscal_year.asc()))).scalars().all()
            if not ratios:
                return json.dumps({"error": f"Aucun ratio trouvé pour case_id={case_id}."})

            # RT-18 : Lire la devise depuis le FS raw le plus récent
            latest_fs = (await db.execute(select(FinancialStatementRaw).where(FinancialStatementRaw.case_id == case_id).order_by(FinancialStatementRaw.fiscal_year.desc()))).scalars().first()
            currency = latest_fs.currency_original if latest_fs and latest_fs.currency_original else "USD"
            
            result_list = []
            for r in ratios:
                result_list.append({
                    "fiscal_year": r.fiscal_year,
                    "current_ratio": r.current_ratio,
                    "quick_ratio": r.quick_ratio,
                    "cash_ratio": r.cash_ratio,
                    "fonds_de_roulement": r.fonds_de_roulement,
                    "debt_to_equity": r.debt_to_equity,
                    "autonomie_financiere": r.autonomie_financiere,
                    "gearing": r.gearing,
                    "interest_coverage": r.interest_coverage,
                    "marge_nette": r.marge_nette,
                    "ebitda_margin": r.ebitda_margin,
                    "operating_margin": r.operating_margin,
                    "roa": r.roa,
                    "roe": r.roe,
                    "bfr": r.bfr,
                    "bfr_pct_ca": r.bfr_pct_ca,
                    "dio_days": r.dio_days,
                    "dso_days": r.dso_days,
                    "dpo_days": r.dpo_days,
                    "cash_conversion_cycle": r.cash_conversion_cycle,
                    "caf": r.caf,
                    "caf_margin_pct": r.caf_margin_pct,
                    "cfo_negatif": bool(r.cfo_negatif),
                    "capitaux_propres_negatifs": bool(r.capitaux_propres_negatifs),
                    "debt_repayment_years": r.debt_repayment_years,
                    "z_score_altman": r.z_score_altman,
                    "z_score_zone": r.z_score_zone,
                    "coherence_alerts": json.loads(r.coherence_alerts_json) if r.coherence_alerts_json else []
                })
                
            return json.dumps({
                "case_id": case_id, 
                "currency": currency,
                "unit_scale": "ABSOLUTE",
                "unit_note": "Unités monétaires absolues (non milliers)",
                "ratio_sets": result_list
            })
            
    except Exception as e:
        return json.dumps({"error": f"Erreur interne: {str(e)}"})


@mcp.tool()
async def read_trends_analysis(case_id: str) -> str:
    """Retourne les tendances multi-exercices : CAGR (taux de croissance annuel composé, en %) et pente de régression linéaire pour les ratios clés (current_ratio, marge_nette, dso_days, debt_to_equity). Retourne aussi les cross_pillar_patterns détectés automatiquement : FAUSSE_LIQUIDITE, SURLEVIER_MASQUE, BFR_TOXIQUE, EFFET_CISEAUX. Tu DOIS mentionner CHAQUE pattern détecté dans ton analyse."""
    try:
        async with get_async_db_context() as db:
            scorecard = (await db.execute(select(Scorecard).where(Scorecard.case_id == case_id))).scalars().first()
            if not scorecard:
                return json.dumps({"error": f"Aucun Scorecard/Tendances (case_id={case_id}). Lancer le moteur de ratios."})
            
            trends_dict = {}
            if scorecard.trends_summary:
                try:
                    trends_dict = json.loads(scorecard.trends_summary)
                except json.JSONDecodeError as e:
                    trends_dict = {"_parse_error": str(e)}
                    
            cross_alerts = []
            if scorecard.cross_analysis_alerts:
                try:
                    cross_alerts = json.loads(scorecard.cross_analysis_alerts)
                except json.JSONDecodeError as e:
                    cross_alerts = [{"_parse_error": str(e)}]
            
            return json.dumps({
                "case_id": case_id,
                "trends": trends_dict,
                "cross_pillar_patterns": cross_alerts
            })
            
    except Exception as e:
        return json.dumps({"error": f"Erreur interne: {str(e)}"})


@mcp.tool()
async def read_stress_results(case_id: str) -> str:
    """Retourne les résultats des scénarios de stress test avec la position de trésorerie minimum atteinte. Chaque scénario a un statut (SOLVENT/LIMIT/INSOLVENT) et un solde de trésorerie. Si un scénario retourne null ou est absent, écris 'Données non disponibles' — NE PAS INVENTER de résultat. Le score de capacité (0-5) intègre un plafond automatique : si stress_60d=INSOLVENT, score capé à 1.5."""
    try:
        async with get_async_db_context() as db:
            assessment = (await db.execute(select(ContractCapacityAssessment).where(ContractCapacityAssessment.case_id == case_id))).scalars().first()
            if not assessment:
                return json.dumps({"error": f"Aucun test de stress (case_id={case_id}). Lancer l'évaluation de capacité."})
            
            flows = json.loads(assessment.monthly_flows_json) if assessment.monthly_flows_json else []
            min_cash = 0
            max_cash = 0
            crit_month = None
            if flows:
                all_cash = []
                for f in flows:
                    all_cash.extend([v for k, v in f.items() if k.startswith("cash_")])
                min_cash = min(all_cash) if all_cash else 0
                max_cash = max(all_cash) if all_cash else 0
                crit_month = next((f.get("month") for f in flows if any(k.startswith("cash_") and v < 0 for k, v in f.items())), None)

            # RT-17 : Exposer TOUS les scénarios calculés
            all_scenarios = {}
            if assessment.scenarios_results_json:
                all_scenarios = json.loads(assessment.scenarios_results_json)

            # Backward compat : garder delay_60d/delay_90d + ajouter les autres
            scenarios_payload = {
                "delay_60d": {
                    "status": assessment.stress_60d_result,
                    "cash_remaining": assessment.stress_60d_cash_position
                },
                "delay_90d": {
                    "status": assessment.stress_90d_result,
                    "cash_remaining": assessment.stress_90d_cash_position
                }
            }
            # Merge les scénarios complets (peut inclure cost_overrun, ca_shock, combined…)
            for sc_name, sc_data in all_scenarios.items():
                if sc_name not in ("S2_RETARD_60", "S3_RETARD_90"):
                    scenarios_payload[sc_name] = sc_data

            return json.dumps({
                "case_id": case_id,
                "scenarios": scenarios_payload,
                "capacity_score": assessment.score_capacite,
                "conclusion": assessment.capacity_conclusion,
                "monthly_summary": {
                    "min_cash_position": min_cash,
                    "max_cash_position": max_cash,
                    "critical_month_reached": crit_month
                }
            })
            
    except Exception as e:
        return json.dumps({"error": f"Erreur interne: {str(e)}"})


@mcp.tool()
async def read_scorecard(case_id: str) -> str:
    """DERNIER OUTIL READ — Retourne le scorecard final avec les 5 scores piliers (0-5 chacun), le score global pondéré (0-5), la classification de risque (FAIBLE/MODERE/ELEVE/CRITIQUE), le profil de risque (EQUILIBRE/ASYMETRIQUE/AGRESSIF/DEFENSIF/CLASSIQUE), les interprétations expertes sauvegardées, les recommandations conditionnelles, et les overrides appliqués. CE SONT LES DONNÉES DE RÉFÉRENCE pour ton rapport."""
    try:
        async with get_async_db_context() as db:
            scorecard = (await db.execute(select(Scorecard).where(Scorecard.case_id == case_id))).scalars().first()
            if not scorecard:
                return json.dumps({"error": f"Scorecard non trouvé (case_id={case_id})."})

            # RT-20 : Déterminer le case_type pour filtrage conditionnel
            case_obj = (await db.execute(select(EvaluationCase).where(EvaluationCase.id == case_id))).scalars().first()
            case_type = case_obj.case_type if case_obj else "SINGLE"
            
            result = {
                "case_id": case_id,
                "pillar_scores": {
                    "liquidite": scorecard.score_liquidite,
                    "solvabilite": scorecard.score_solvabilite,
                    "rentabilite": scorecard.score_rentabilite,
                    "capacite": scorecard.score_capacite,
                    "qualite": scorecard.score_qualite
                },
                "global_score": scorecard.score_global,
                "classification": scorecard.risk_class,
                "risk_profile": scorecard.risk_profile,
                "risk_description": scorecard.risk_description,
                "expert_interpretations": json.loads(scorecard.expert_interpretations_json) if scorecard.expert_interpretations_json else {},
                "smart_recommendations": json.loads(scorecard.smart_recommendations_json) if scorecard.smart_recommendations_json else [],
                "overrides_applied": json.loads(scorecard.overrides_applied_json) if scorecard.overrides_applied_json else [],
                "data_alerts": json.loads(scorecard.data_alerts_json) if hasattr(scorecard, 'data_alerts_json') and scorecard.data_alerts_json else [],
            }

            # RT-20 : N'inclure synergy_bonus et weak_link que pour CONSORTIUM
            if case_type == "CONSORTIUM":
                result["synergy_bonus"] = scorecard.synergy_bonus
                result["weak_link_triggered"] = scorecard.weak_link_triggered if hasattr(scorecard, 'weak_link_triggered') else None

            return json.dumps(result)
            
    except Exception as e:
        return json.dumps({"error": f"Erreur interne: {str(e)}"})


@mcp.tool()
async def read_gate_status(case_id: str) -> str:
    """DEUXIÈME APPEL OBLIGATOIRE — GATE CHECK BLOQUANT. Retourne le verdict du contrôle documentaire et de due diligence. Si verdict='BLOCKING', le dossier NE PEUT PAS être évalué — arrêter immédiatement et signaler les blocking_flags à l'analyste. Les reserve_flags sont des avertissements non-bloquants à mentionner dans la Section 13 du rapport."""
    try:
        from app.engines.gate_engine import run_gate
        from app.services.policy_service import get_active_policy

        # FIX: db was undefined — must be inside an async session context
        async with get_async_db_context() as db:
            policy = await get_active_policy(db)
            gate_res = run_gate(case_id, policy)

            return json.dumps({
                "case_id": case_id,
                "verdict": gate_res.get("verdict"),
                "blocking_flags": gate_res.get("blocking_flags", []),
                "reserve_flags": gate_res.get("reserve_flags", []),
                "dd_verdicts": gate_res.get("dd_verdicts", {})
            })

    except Exception as e:
        return json.dumps({"error": f"Erreur interne: {str(e)}"})


@mcp.tool()
async def read_consortium_data(case_id: str) -> str:
    """UNIQUEMENT pour les dossiers CONSORTIUM. Retourne la composition du consortium : membres (nom, rôle LEADER/MEMBER, participation en %), type de JV (SOLIDAIRE/CONJOINTE/SEPARATE), et les individual_case_id permettant de requêter les scorecards individuels. Tu DOIS identifier le maillon faible et mentionner explicitement le synergy_index dans ton analyse."""
    try:
        async with get_async_db_context() as db:
            case = (await db.execute(select(EvaluationCase).where(EvaluationCase.id == case_id))).scalars().first()
            if not case:
                return json.dumps({"error": f"Case ID {case_id} not found."})
                
            if case.case_type != "CONSORTIUM" or not case.consortium_id:
                return json.dumps({"error": f"Dossier {case_id} n'est pas un Consortium."})
                
            c = case.consortium
            members = []
            for m in getattr(c, 'members', []):
                members.append({
                    "role": m.role.value if hasattr(m.role, 'value') else str(m.role),
                    "bidder_name": m.bidder.name if m.bidder else "Unknown",
                    "participation_pct": float(m.participation_pct),
                    "individual_case_id": str(m.individual_case_id) if m.individual_case_id else None
                })

            # ── ENRICHMENT: ConsortiumResult analytics ──
            # Exposes synergy_index, weak_link, aggregated_stress so the LLM
            # can fulfill its mandate without hallucinating these values.
            consortium_result = (await db.execute(
                select(ConsortiumResult)
                .where(ConsortiumResult.case_id == case_id)
            )).scalars().first()

            consortium_analytics = None
            if consortium_result:
                consortium_analytics = {
                    "weighted_score": float(consortium_result.weighted_score) if consortium_result.weighted_score is not None else None,
                    "synergy_index": float(consortium_result.synergy_index) if consortium_result.synergy_index is not None else None,
                    "synergy_bonus": float(consortium_result.synergy_bonus) if consortium_result.synergy_bonus is not None else None,
                    "base_risk_class": consortium_result.base_risk_class,
                    "final_risk_class": consortium_result.final_risk_class,
                    "weak_link_triggered": consortium_result.weak_link_triggered,
                    "weak_link_member": consortium_result.weak_link_member,
                    "leader_blocking": consortium_result.leader_blocking,
                    "leader_override": consortium_result.leader_override,
                    "aggregated_stress": consortium_result.aggregated_stress,
                    "aggregation_method": consortium_result.aggregation_method,
                    "computed_at": consortium_result.computed_at.isoformat() if consortium_result.computed_at else None,
                }

            result = {
                "consortium_id": str(c.id),
                "name": c.name,
                "jv_type": c.jv_type.value if hasattr(c.jv_type, 'value') else str(c.jv_type),
                "members": members,
                "consortium_analytics": consortium_analytics
            }

            return json.dumps(result)
            
    except Exception as e:
        return json.dumps({"error": f"Erreur interne: {str(e)}"})


@mcp.tool()
async def read_report_sections(case_id: str, sections: list = None) -> str:
    """Retourne le rapport 14 sections pré-généré par le moteur Python."""
    try:
        async with get_async_db_context() as db:
            report = (await db.execute(select(MCCGradeReport).where(MCCGradeReport.case_id == case_id))).scalars().first()
            if not report:
                return json.dumps({"error": f"Aucun rapport trouvé (case_id={case_id})."})
            
            all_sections = {
                "case_id": case_id,
                "status": report.status,
                "section_01_info": report.section_01_info,
                "section_02_objectif": report.section_02_objectif,
                "section_03_perimetre": report.section_03_perimetre,
                "section_04_synthese": report.section_04_synthese,
                "section_05_profil": report.section_05_profil,
                "section_06_analyse": report.section_06_analyse,
                "section_07_capacite": report.section_07_capacite,
                "section_08_red_flags": report.section_08_red_flags,
                "section_09_attenuants": report.section_09_attenuants,
                "section_10_scoring": report.section_10_scoring,
                "section_11_appreciation": report.section_11_appreciation,
                "section_12_recommandation": report.section_12_recommandation,
                "section_13_limites": report.section_13_limites,
                "section_14_conclusion": report.section_14_conclusion
            }
            if sections:
                return json.dumps({k: v for k, v in all_sections.items() if k in sections or k == "case_id"})
            return json.dumps(all_sections)
            
    except Exception as e:
        return json.dumps({"error": f"Erreur interne: {str(e)}"})

@mcp.tool()
async def read_ia_analysis(case_id: str) -> str:
    """Retourne le score alternatif calculé par l'Intelligence Artificielle (XGBoost) et l'analyse des tensions (écarts) entre le modèle MCC officiel et l'IA. Tu DOIS consulter cet outil pour challenger les résultats du scorecard classique et enrichir ton rapport d'une perspective data-driven. ATTENTION : Pour les dossiers CONSORTIUM, le modèle IA évalue les entités individuellement — les scores retournés sont par membre et NE DOIVENT PAS être comparés directement au score MCC global du consortium."""
    try:
        async with get_async_db_context() as db:
            # ── STEP 0: Detect case_type for consortium guard ──
            case_obj = (await db.execute(
                select(EvaluationCase).where(EvaluationCase.id == case_id)
            )).scalars().first()

            if not case_obj:
                return json.dumps({"error": f"Case ID {case_id} not found."})

            # ── CONSORTIUM GUARD ──
            # XGBoost evaluates individual corporate entities, not consortiums.
            # For CONSORTIUM cases, return per-member IA scores with an explicit warning.
            if case_obj.case_type == "CONSORTIUM" and case_obj.consortium_id:
                members = (await db.execute(
                    select(ConsortiumMember)
                    .where(ConsortiumMember.consortium_id == case_obj.consortium_id)
                )).scalars().all()

                member_predictions = []
                for m in members:
                    member_pred = None
                    if m.individual_case_id:
                        member_pred = (await db.execute(
                            select(IAPrediction)
                            .where(IAPrediction.case_id == m.individual_case_id)
                            .order_by(IAPrediction.created_at.desc())
                        )).scalars().first()

                    member_predictions.append({
                        "bidder_name": m.bidder.name if m.bidder else "N/A",
                        "role": m.role.value if hasattr(m.role, 'value') else str(m.role),
                        "participation_pct": float(m.participation_pct),
                        "individual_case_id": str(m.individual_case_id) if m.individual_case_id else None,
                        "ia_score": float(member_pred.ia_score) if member_pred else None,
                        "ia_risk_class": member_pred.ia_risk_class if member_pred else None,
                        "probability_of_default": float(member_pred.ia_probability_default) if member_pred else None,
                    })

                return json.dumps({
                    "case_id": case_id,
                    "case_type": "CONSORTIUM",
                    "warning": (
                        "Le modèle IA (XGBoost) évalue les entités individuellement. "
                        "Les scores ci-dessous ne reflètent PAS la structure consortium "
                        "(synergies, maillon faible, solidarité JV). NE PAS comparer "
                        "directement avec le score MCC global du consortium."
                    ),
                    "member_ia_scores": member_predictions
                })

            # ── SINGLE ENTITY PATH ──
            # FIX: predicted_at → created_at (column does not exist on IAPrediction)
            pred_result = await db.execute(
                select(IAPrediction)
                .where(IAPrediction.case_id == case_id)
                .order_by(IAPrediction.created_at.desc())
            )
            prediction = pred_result.scalars().first()

            # Fetch Tension
            tens_result = await db.execute(
                select(IATension)
                .where(IATension.case_id == case_id)
                .order_by(IATension.created_at.desc())
            )
            tension = tens_result.scalars().first()

            if not prediction:
                return json.dumps({"message": "Aucune prédiction IA disponible pour ce dossier."})

            # ── STALENESS DETECTION ──
            # Compare prediction timestamp against latest financial statement update.
            # If financials were updated after the prediction was computed, the AI score
            # may no longer reflect the current financial reality.
            latest_fs = (await db.execute(
                select(FinancialStatementRaw)
                .where(FinancialStatementRaw.case_id == case_id)
                .order_by(FinancialStatementRaw.updated_at.desc().nullslast())
            )).scalars().first()

            is_stale = False
            staleness_warning = None
            if latest_fs and prediction:
                fs_updated = latest_fs.updated_at or latest_fs.created_at
                pred_computed = prediction.created_at
                if fs_updated and pred_computed and fs_updated > pred_computed:
                    is_stale = True
                    staleness_warning = (
                        f"ATTENTION : Les états financiers ont été mis à jour le "
                        f"{fs_updated.isoformat()} mais la prédiction IA date du "
                        f"{pred_computed.isoformat()}. Le score IA est potentiellement "
                        f"obsolète. Relancer le moteur IA avant d'utiliser ce score."
                    )

            result = {
                "case_id": case_id,
                "case_type": "SINGLE",
                "ia_score": float(prediction.ia_score),
                "ia_risk_class": prediction.ia_risk_class,
                "probability_of_default": float(prediction.ia_probability_default),
                "model_version": prediction.model_version,
                "predicted_at": prediction.created_at.isoformat() if prediction.created_at else None,
                "is_stale": is_stale,
                "staleness_warning": staleness_warning,
                "tension_analysis": {
                    # FIX: tension_severity does not exist on IATension model — removed
                    "type": tension.tension_type if tension else "N/A",
                    "explanation": tension.explanation if tension else "Aucune divergence majeure détectée."
                }
            }

            return json.dumps(result)

    except Exception as e:
        return json.dumps({"error": f"Erreur interne IA: {str(e)}"})

# --- OUTILS ORCHESTRATION & WRITE-BACK ---

@mcp.tool()
async def trigger_full_evaluation(
    case_id: str,
    contract_value: float,
    contract_months: int,
    advance_pct: float = 0.0
) -> str:
    """DÉCLENCHEUR DE PIPELINE — Exécute séquentiellement : Normalisation → Ratios → Stress Tests → Scoring → Rapport. ATTENTION CRITIQUE : Si le retour contient status='error' OU si le champ scoring contient 'FAILED', NE PAS CONSIDÉRER la pipeline comme réussie. Tu DOIS résoudre l'erreur (souvent : interprétation manquante → appeler write_interpretation d'abord) avant de poursuivre."""
    from app.engines.normalization_engine import normalize_all_statements
    from app.engines.ratio_engine import compute_all_ratios
    from app.engines.stress_engine import compute_capacity
    from app.engines.scoring_engine import compute_scorecard
    from app.engines.report_builder import build_full_report
    from app.services.policy_service import get_active_policy
    from app.services.audit_service import log_event

    try:
        # FIX: policy fetch must be inside an async db session context.
        # Previously, `db` was used at line 419 before any session was opened → RuntimeError.
        async with get_async_db_context() as db:
            policy = await get_active_policy(db)

        # 1. Normalisation
        norms = normalize_all_statements(case_id)

        # 2. Ratios & Tendances & Patterns
        ratios = compute_all_ratios(case_id)

        # 3. Stress Tests (Capacité)
        async with get_async_db_context() as db:
            # FinancialStatementRaw is now imported at module level
            fs = (await db.execute(
                select(FinancialStatementRaw)
                .where(FinancialStatementRaw.case_id == case_id)
                .order_by(FinancialStatementRaw.fiscal_year.desc())
            )).scalars().first()

            if not fs or not fs.chiffre_affaires:
                return json.dumps({"status": "error", "error": "CA manquant ou nul pour le calcul du stress test"})

            annual_ca_avg = float(fs.chiffre_affaires)
            if fs.actif_liquide is None:
                return json.dumps({"status": "error", "error": "Donnée manquante : L'actif liquide est requis pour déterminer le cash disponible."})
            cash_available = float(fs.actif_liquide)

        stress = compute_capacity(
            case_id=case_id,
            contract_value=contract_value,
            contract_months=contract_months,
            annual_ca_avg=annual_ca_avg,
            cash_available=cash_available,
            advance_pct=advance_pct
        )

        # 4. Scoring (Si interprétation valide, sinon plantera ce qui est attendu)
        score = compute_scorecard(case_id, policy)

        # 5. Report Builder
        report = build_full_report(case_id, policy)

        async with get_async_db_context() as db:
            log_event(
                case_id=case_id,
                event_type="CASE_UPDATED",
                description="Pipeline d'évaluation déclenchée par l'agent IA via MCP",
                user_id="CLAUDE_COWORK",
                db_session=db
            )

        return json.dumps({
            "status": "success",
            "message": "Pipeline executée avec succès.",
            "steps": {
                "normalization": f"{len(norms)} statements processed",
                "ratios": f"{len(ratios)} ratio sets computed",
                "stress_tests": "Completed 6 scenarios",
                "scoring": "Completed",
                "report": "Generated 14 sections"
            }
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": str(e),
            "action_required": "Vérifiez les données du dossier (financières, qualitatives, etc.) et corrigez l'erreur avant de relancer l'évaluation."
        })


@mcp.tool()
async def write_interpretation(
    case_id: str,
    liquidite_label: str, liquidite_comment: str,
    solvabilite_label: str, solvabilite_comment: str,
    rentabilite_label: str, rentabilite_comment: str,
    capacite_label: str, capacite_comment: str,
    qualite_label: str, qualite_comment: str,
    analyse_dynamique_comment: str
) -> str:
    """ÉCRITURE PHASE 2 — Persiste ton interprétation experte des 5 piliers. Chaque label DOIT être parmi : INSUFFISANT, FAIBLE, MODERE, FORT, TRES_FORT. Chaque commentaire DOIT faire entre 2 et 5 phrases avec des chiffres issus de read_financial_ratios. L'analyse_dynamique_comment DOIT faire au moins 100 caractères et mentionner les cross_pillar_patterns. Si l'outil retourne des warnings de cohérence, AJUSTE tes labels ou JUSTIFIE explicitement l'écart."""
    from app.engines.interpretation_engine import validate_interpretation, save_interpretation
    
    data = {
        "liquidite_label": liquidite_label, "liquidite_comment": liquidite_comment,
        "solvabilite_label": solvabilite_label, "solvabilite_comment": solvabilite_comment,
        "rentabilite_label": rentabilite_label, "rentabilite_comment": rentabilite_comment,
        "capacite_label": capacite_label, "capacite_comment": capacite_comment,
        "qualite_label": qualite_label, "qualite_comment": qualite_comment,
        "analyse_dynamique_comment": analyse_dynamique_comment
    }
    
    async_session = async_session_maker()
    db = async_session
    try:
        validation = validate_interpretation(case_id, data, db=db)
        
        interp_id = save_interpretation(
            case_id,
            liquidite_label=liquidite_label, liquidite_comment=liquidite_comment,
            solvabilite_label=solvabilite_label, solvabilite_comment=solvabilite_comment,
            rentabilite_label=rentabilite_label, rentabilite_comment=rentabilite_comment,
            capacite_label=capacite_label, capacite_comment=capacite_comment,
            qualite_label=qualite_label, qualite_comment=qualite_comment,
            analyse_dynamique_comment=analyse_dynamique_comment,
            coherence_warnings=validation.get("warnings", []),
            db=db
        )
        
        await db.commit()
        return json.dumps({
            "status": "success",
            "interpretation_id": interp_id,
            "coherence_ok": validation.get("coherence_ok", True),
            "warnings": validation.get("warnings", [])
        })
    except Exception as e:
        await db.rollback()
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        await db.close()


@mcp.tool()
async def write_report_narrative(
    case_id: str,
    section_key: str,
    narrative_content: str,
    append_mode: bool = True
) -> str:
    """ÉCRITURE PHASE 3 — Enrichit une section narrative du rapport MCC. Les sections 05, 07, 08, 10 sont VERROUILLÉES (auto-générées par Python). Seules les sections narratives sont modifiables : 01 (info), 02 (objectif), 03 (périmètre), 04 (synthèse exécutive — RÉDIGER EN DERNIER), 06 (analyse détaillée), 09 (atténuants), 11 (appréciation), 12 (recommandation), 13 (limites), 14 (conclusion). Mode append=true ajoute au contenu existant, append=false remplace."""
    # Architecture Garde-fou ADR-05 : Interdiction de modifier les sections quantitatives (chiffrées)
    LOCKED_SECTIONS = ["section_05_profil", "section_07_capacite", "section_08_red_flags", "section_10_scoring"]
    
    if section_key in LOCKED_SECTIONS:
        return json.dumps({
            "status": "error", 
            "message": f"Access denied: Section {section_key} is auto-generated by left-brain deterministic engines and cannot be modified."
        })
        
    VALID_NARRATIVE_SECTIONS = [
        "section_01_info", "section_02_objectif", "section_03_perimetre", 
        "section_04_synthese", "section_06_analyse", "section_09_attenuants", 
        "section_11_appreciation", "section_12_recommandation", "section_13_limites", "section_14_conclusion"
    ]
    
    if section_key not in VALID_NARRATIVE_SECTIONS:
        return json.dumps({"status": "error", "message": f"Section key '{section_key}' invalid."})

    from app.services.audit_service import log_event
    try:
        async with get_async_db_context() as db:
            # CRI-04 : Hard Guard — Vérifier que l'interprétation existe
            interp = (await db.execute(select(ExpertInterpretation).where(ExpertInterpretation.case_id == case_id))).scalars().first()
            if not interp:
                return json.dumps({
                    "status": "error",
                    "error": "Interprétation manquante. Vous devez d'abord écrire l'interprétation via write_interpretation."
                })

            report = (await db.execute(select(MCCGradeReport).where(MCCGradeReport.case_id == case_id).order_by(MCCGradeReport.version_number.desc()))).scalars().first()
            if not report:
                return json.dumps({"status": "error", "message": "Aucun rapport existant. Lancez l'évaluation complète d'abord."})
                
            current_content = getattr(report, section_key, "") or ""
            new_content = current_content + "\n\n" + narrative_content if append_mode else narrative_content
            
            setattr(report, section_key, new_content)
            
            # DB transaction via context
            log_event(
                case_id=case_id,
                event_type="REPORT_SECTION_UPDATED",
                entity_type="MCCGradeReport",
                entity_id=report.id,
                description=f"Claude a édité le narratif de la {section_key}",
                user_id="CLAUDE_COWORK",
                db_session=db
            )
            await db.commit()
            
            return json.dumps({"status": "success", "section": section_key, "action": "appended" if append_mode else "replaced"})
            
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def write_override_decision(
    case_id: str,
    original_score: float,
    adjusted_score: float,
    justification: str,
    override_type: str,
    authorized_by: str
) -> str:
    """RÉSERVÉ SENIOR FIDUCIARY — Force un ajustement manuel du score global. L'écart maximum autorisé est de ±1.0 point. Toute tentative au-delà sera REJETÉE par le système. Nécessite une justification écrite obligatoire et l'identité de l'autorisant. L'override est tracé dans l'audit trail et déclenche un recalcul automatique de la classification de risque."""
    import uuid
    from datetime import datetime
    from app.services.audit_service import log_event
    
    # Garde-fou 1 : L'override max est 1.0 point
    diff = abs(adjusted_score - original_score)
    if diff > 1.0:
        return json.dumps({
            "status": "error", 
            "message": f"Violation des limites: L'écart de score ({diff} pts) dépasse le seuil autorisé de 1.0 point."
        })
        
    try:
        async with get_async_db_context() as db:
            scorecard = (await db.execute(select(Scorecard).where(Scorecard.case_id == case_id))).scalars().first()
            if not scorecard:
                return json.dumps({"status": "error", "message": "Scorecard introuvable."})
                
            ov_id = str(uuid.uuid4())
            new_override = OverrideDecision(
                id=ov_id,
                case_id=case_id,
                original_score=original_score,
                adjusted_score=adjusted_score,
                justification=justification,
                override_type=override_type,
                authorized_by=authorized_by,
                created_at=datetime.utcnow()
            )
            db.add(new_override)
            
            # Recalcul des labels suite à l'override
            from app.services.policy_service import get_active_policy, get_risk_band
            pol = await get_active_policy(db)
            new_risk_class, new_recommendation, _ = get_risk_band(adjusted_score, pol)
            
            old_val = {"score_global": scorecard.score_global, "risk_class": scorecard.risk_class}
            
            scorecard.score_global = adjusted_score
            scorecard.risk_class = new_risk_class
            
            # Gestion append historique JSON
            import json as _json
            overrides = _json.loads(scorecard.overrides_applied_json) if scorecard.overrides_applied_json else []
            overrides.append(ov_id)
            scorecard.overrides_applied_json = _json.dumps(overrides)
            
            log_event(
                case_id=case_id,
                event_type="OVERRIDE_ADDED",
                entity_type="OverrideDecision",
                entity_id=ov_id,
                description=f"Fiduciary Override: Score {original_score} -> {adjusted_score}. Motif: {justification}",
                old_value=old_val,
                new_value={"score_global": adjusted_score, "risk_class": new_risk_class},
                user_id=authorized_by,
                db_session=db
            )
            await db.commit()
            
            return json.dumps({
                "status": "success",
                "message": f"Score modifié de {original_score} à {adjusted_score}. Profil de risque mis à jour: {new_risk_class}",
                "override_id": ov_id
            })
            
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


if __name__ == "__main__":
    # Démarrage du serveur en mode web (SSE) pour Docker network
    # La protection DNS Rebinding du SDK MCP (CVE-2025-66416) valide
    # les headers Host et Origin. En production derrière Traefik → Nginx,
    # le Host reçu est "localhost" (réécrit par Nginx) sur le port 8080.
    # On autorise explicitement ces hôtes internes Docker.
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = 8080
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "localhost",
            "localhost:8080",
            "127.0.0.1",
            "127.0.0.1:8080",
            "few-mcp:8080",      # Nom de service Docker interne
        ],
        allowed_origins=[
            "http://localhost:*",
            "http://127.0.0.1:*",
            "http://few-mcp:*",
            "https://adsa.cloud",
        ],
    )
    mcp.run(transport="sse")
