from decimal import Decimal
from typing import Optional, List, Dict, Any
from app.schemas.report_schema import ReportMasterSchema
from app.schemas.gate_schema import GateDecisionSchema
from app.schemas.scoring_schema import ScorecardOutputSchema
from app.schemas.stress_schema import StressResultSchema
from app.schemas.consortium_schema import ConsortiumScorecardOutput
from datetime import date

def _fmt_amount(val: Optional[Decimal]) -> str:
    if val is None:
        return "N/A"
    return f"{val:,.2f}".replace(",", " ")

def build_section_01(
    bidder_name: str,
    market_reference: str,
    market_object: str,
    contract_value: Optional[Decimal],
    contract_currency: str,
    contract_duration_months: Optional[int],
    policy_version_id: str,
    status: str
) -> str:
    today = date.today().strftime("%d/%m/%Y")
    return (
        f"**Bidder:** {bidder_name}\n\n"
        f"**Market Reference:** {market_reference}\n\n"
        f"**Market Object:** {market_object}\n\n"
        f"**Estimated Contract Value:** {_fmt_amount(contract_value)} {contract_currency}\n\n"
        f"**Contract Duration:** {contract_duration_months or 'N/A'} months\n\n"
        f"**Analysis Date:** {today}\n\n"
        f"**Applied Policy Version:** {policy_version_id}\n\n"
        f"**Case Status:** {status}"
    )

def build_section_02(bidder_name: str, market_reference: str, policy_version_label: str, policy_effective_date: str) -> str:
    return (
        f"This note aims to evaluate the financial capability of the bidder **{bidder_name}** "
        f"under the market **{market_reference}**.\n\n"
        f"This evaluation is performed in accordance with MCC/MCA fiduciary standards "
        f"and the active analysis policy (version: {policy_version_label}, "
        f"effective: {policy_effective_date}).\n\n"
        f"It covers the analysis of historical financial statements, liquidity ratios, "
        f"solvency, profitability, contract capacity evaluation, and produces an audited recommendation."
    )

def build_section_03(gate_decision: Optional[GateDecisionSchema]) -> str:
    if not gate_decision:
        return "Document gate evaluation pending or missing."
    
    verdict = gate_decision.is_passed
    verdict_str = "PASS" if verdict else "FAILED"
    reliability = gate_decision.reliability_score
    blocking_txt = "\n".join([f"- ⛔ {f}" for f in gate_decision.blocking_reasons]) if gate_decision.blocking_reasons else "No blocking reasons identified."
    
    return (
        f"**Document Gate Verdict:** {verdict_str}\n\n"
        f"**Overall Reliability Score:** {reliability:.2f}/5.00\n\n"
        f"**Blocking Elements:**\n{blocking_txt}\n\n"
        f"The analysis is based on financial data provided by the bidder, "
        f"normalized to MCC-grade standards."
    )

def build_section_04(
    bidder_name: str,
    recommendation: str,
    gate_decision: Optional[GateDecisionSchema],
    scorecard: Optional[ScorecardOutputSchema],
    stress: Optional[StressResultSchema]
) -> str:
    score = scorecard.global_score if scorecard else Decimal("0.0")
    risk_class = scorecard.final_risk_class.value if scorecard and scorecard.final_risk_class else "NOT_EVALUATED"
    auto_overrides = sum(1 for o in (scorecard.overrides_applied if scorecard else []) if "AUTO" in o)
    manual_overrides = len(scorecard.overrides_applied if scorecard else []) - auto_overrides
    gate_v = "PASS" if gate_decision and gate_decision.is_passed else "FAILED"
    stress_status = stress.capacity_conclusion if stress else "N/A"
    
    risk_icons = {"LOW": "🟢", "MODERATE": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}
    icon = risk_icons.get(risk_class, "⚪")

    return (
        f"### Summary of Analysis\n\n"
        f"| Dimension | Result |\n"
        f"|-----------|----------|\n"
        f"| Document Gate | {gate_v} |\n"
        f"| MCC Global Score | {score:.3f} / 5.000 |\n"
        f"| Final Risk Class | {icon} **{risk_class}** |\n"
        f"| Contractual Capacity | {stress_status} |\n"
        f"| Automatic Overrides | {auto_overrides} |\n"
        f"| Documented Manual Overrides | {manual_overrides} |\n\n"
        f"### Executive Conclusion\n\n"
        f"Based on the financial analysis conducted according to MCC-grade standards, "
        f"the bidder **{bidder_name}** presents a fiduciary risk profile classified as "
        f"**{risk_class}** (score: {score:.3f}/5.000).\n\n"
        f"**Recommendation: {recommendation}**\n\n"
    )

def build_final_report_context(
    report_id: str,
    case_id: str,
    bidder_name: str,
    market_reference: str,
    market_object: str,
    contract_value: Optional[Decimal],
    contract_currency: str,
    contract_duration_months: Optional[int],
    policy_version_id: str,
    policy_version_label: str,
    policy_effective_date: str,
    status: str,
    recommendation: Optional[str],
    gate_decision: Optional[GateDecisionSchema],
    scorecard: Optional[ScorecardOutputSchema],
    stress: Optional[StressResultSchema],
    consortium: Optional[ConsortiumScorecardOutput]
) -> ReportMasterSchema:

    s01 = build_section_01(bidder_name, market_reference, market_object, contract_value, contract_currency, contract_duration_months, policy_version_id, status)
    s02 = build_section_02(bidder_name, market_reference, policy_version_label, policy_effective_date)
    s03 = build_section_03(gate_decision)
    s04 = build_section_04(bidder_name, recommendation or "NOT_EVALUATED", gate_decision, scorecard, stress)

    # Missing implementations for s05-s14 are stubs to strictly adhere to pure function architecture mappings without polluting DB lookups.
    return ReportMasterSchema(
        report_id=report_id,
        case_id=case_id,
        bidder_name=bidder_name,
        recommendation=recommendation,
        section_01_info=s01,
        section_02_objective=s02,
        section_03_scope=s03,
        section_04_executive_summary=s04,
        section_05_profile="Entity profile generation stub...",
        section_06_analysis="Analysis metrics generating natively...",
        section_07_capacity="Capacity limits bounding mapping...",
        section_08_red_flags="Red flag aggregator capturing auto rules...",
        section_09_mitigants="Mitigations mapping resolving overrides...",
        section_10_scoring="Deep scoring generation bounding tables...",
        section_11_assessment="Risk qualitative bounds mapped to strings...",
        section_12_recommendation=recommendation or "NOT_EVALUATED",
        section_13_limitations="Extrapolated documentation bounds...",
        section_14_conclusion=f"Final analysis concluded with scoring: {scorecard.global_score if scorecard else 0}",
        complete_flags={
            "section_01_info": True,
            "section_02_objective": True,
            "section_03_scope": True,
            "section_04_executive_summary": True,
        },
        sections_complete=4,
        sections_total=14
    )
