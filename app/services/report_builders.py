"""
app/services/report_builders.py
Pure functions for generating Markdown report sections.
"""
from datetime import datetime, date

def _build_section_01(case: dict) -> str:
    today = date.today().strftime("%d/%m/%Y")
    return (
        f"**Bidder:** {case.get('bidder_name', 'N/A')}\n\n"
        f"**Market Reference:** {case.get('market_reference', 'N/A')}\n\n"
        f"**Market Subject:** {case.get('market_object', 'N/A')}\n\n"
        f"**Estimated Contract Value:** "
        f"{_fmt_amount(case.get('contract_value'))} "
        f"{case.get('contract_currency', 'USD')}\n\n"
        f"**Contract Duration:** "
        f"{case.get('contract_duration_months', 'N/A')} months\n\n"
        f"**Analysis Date:** {today}\n\n"
        f"**Applied Policy Version:** {case.get('policy_version_id', 'N/A')}\n\n"
        f"**Case Status:** {case.get('status', 'N/A')}"
    )


def _build_section_02(case: dict, policy: dict) -> str:
    return (
        f"This report assesses the financial capacity of bidder "
        f"**{case.get('bidder_name', 'N/A')}** in the context of "
        f"contract **{case.get('market_reference', 'N/A')}**.\n\n"
        f"The assessment is conducted in compliance with MCC/MCA fiduciary standards "
        f"and the applicable analysis policy "
        f"(version: {policy.get('version_label', 'N/A')}, "
        f"effective {policy.get('effective_date', 'N/A')}).\n\n"
        f"It covers the analysis of historical financial statements, "
        f"the computation of liquidity, solvency, and profitability ratios, "
        f"the assessment of contract execution capacity, "
        f"and the production of a documented, auditable recommendation."
    )


def _build_section_03(gate: dict) -> str:
    verdict      = gate.get("verdict", "N/A")
    reliability  = gate.get("reliability_level", "N/A")
    years        = gate.get("fiscal_years_covered", [])
    blocking     = gate.get("blocking_flags", [])
    reserves     = gate.get("reserve_flags", [])
    docs_summary = gate.get("documents_summary", [])

    doc_lines = "\n".join(
        f"- {d.get('doc_type')} "
        f"(fiscal year {d.get('fiscal_year', 'N/A')}) — "
        f"Status: {d.get('status')} — "
        f"Reliability: {d.get('reliability_level', 'N/A')}"
        for d in docs_summary
    ) or "No documents recorded."

    blocking_txt = "\n".join(f"- ⛔ {f}" for f in blocking) or "No documentary blocking issues identified."
    reserves_txt = "\n".join(f"- ⚠️ {r}" for r in reserves) or "No documentary reserves."
    years_txt    = ", ".join(str(y) for y in years) if years else "Not determined"

    return (
        f"**Documentary gate verdict:** {verdict}\n\n"
        f"**Overall reliability level:** {reliability}\n\n"
        f"**Fiscal years covered:** {years_txt}\n\n"
        f"**Documents submitted:**\n{doc_lines}\n\n"
        f"**Blocking issues:**\n{blocking_txt}\n\n"
        f"**Reserves:**\n{reserves_txt}\n\n"
        f"The analysis is based on financial data provided by the bidder, "
        f"normalised to the MCC-grade framework. "
        f"Any documentary limitation or reserve is taken into account "
        f"in the final risk assessment."
    )


def _build_section_04(case, scorecard, gate, capacity, sections, consortium_data=None) -> str:
    risk_class  = scorecard.get("final_risk_class", "N/A")
    score       = scorecard.get("score_global", 0)
    reco        = case.get("recommendation")
    reco_label  = RECOMMENDATION_LABELS.get(reco, reco or "Not determined")
    gate_verdict= gate.get("verdict", "N/A")
    coverage    = capacity.get("coverage_status", "N/A")
    stress_60   = capacity.get("stress_60d_result", "N/A")

    risk_icons  = {"LOW": "🟢", "MODERATE": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}
    icon        = risk_icons.get(risk_class, "⚪")

    alerts      = scorecard.get("overrides_applied", [])
    n_auto      = sum(1 for a in alerts if a.get("auto"))
    n_manual    = len(alerts) - n_auto

    contract_val = float(capacity.get("contract_value") or 0)
    currency     = case.get("contract_currency", "USD")
    bfr          = float(capacity.get("bfr_estimate") or 0)

    raw_recos = list(scorecard.get("smart_recommendations", []))
    if consortium_data:
        raw_recos.extend(consortium_data.get("mitigations_suggested", []))

    chiffred_recos = []
    for r in raw_recos:
        text = r
        if "guarantee" in text.lower() or "performance bond" in text.lower():
            mnt = contract_val * 0.10
            chiffred_recos.append(f"- Provide a first-demand bank guarantee for a minimum of {_fmt_amount(mnt)} {currency} (10% of contract value).\n  *Basis: {text}*")
        elif "wcr" in text.lower() or "credit line" in text.lower() or "liquidity" in text.lower():
            chiffred_recos.append(f"- Secure a confirmed credit line covering the Working Capital Requirement (WCR) estimated at {_fmt_amount(bfr)} {currency}.\n  *Basis: {text}*")
        else:
            chiffred_recos.append(f"- {text}")

    cond_text = "\n".join(chiffred_recos) if chiffred_recos else "No specific conditions."

    return (
        f"### Executive Summary\n\n"
        f"| Dimension | Result |\n"
        f"|-----------|--------|\n"
        f"| Documentary Gate | {gate_verdict} |\n"
        f"| Overall MCC Score | {float(score):.3f} / 5.000 |\n"
        f"| Final Risk Class | {icon} **{risk_class}** |\n"
        f"| Contract Capacity | {coverage} |\n"
        f"| 60-Day Stress Test | {stress_60} |\n"
        f"| Automatic Overrides | {n_auto} |\n"
        f"| Documented Manual Overrides | {n_manual} |\n\n"
        f"### Executive Conclusion\n\n"
        f"Based on the MCC-grade financial analysis, bidder **{case.get('bidder_name', 'N/A')}** "
        f"presents a fiduciary risk profile rated "
        f"**{risk_class}** (score: {float(score):.3f}/5.000).\n\n"
        f"**Recommendation: {reco_label}**\n\n"
        f"### Conditions Precedent and Recommendations\n\n"
        f"{cond_text}\n\n"
        f"The full analysis, including ratios, scoring breakdown, and identified red flags, "
        f"is detailed in the sections below. "
        f"This executive summary does not replace the analytical sections."
    )


def _build_section_05(case: dict) -> str:
    bidder_name = case.get("bidder_name", "N/A")
    legal_form  = case.get("legal_form",  "N/A")
    sector      = case.get("sector",      "N/A")
    country     = case.get("country",     "N/A")
    reg_number  = case.get("registration_number", "N/A")
    case_type   = case.get("case_type", "SINGLE")
    entity_desc = "consortium" if case_type == "CONSORTIUM" else "individual bidder"
    return (
        f"The {entity_desc} **{bidder_name}** is a legal entity of the form "
        f"**{legal_form}**, operating in the **{sector}** sector, "
        f"domiciled in **{country}**.\n\n"
        f"**Registration Number:** {reg_number}\n\n"
        f"The financial data submitted covers the analysed fiscal years "
        f"and has been subject to documented normalisation to the MCC-grade framework "
        f"(liquidity, solvency, profitability, contract capacity). "
        f"The declared sector of activity was taken into account for "
        f"contextualisation of sectoral benchmarks."
    )


def _build_trend_narrative(trends_summary: dict) -> str:
    if not trends_summary:
        return "No multi-year trends available."
    parts = []
    for k, v in trends_summary.items():
        if not isinstance(v, dict):
            continue
        name      = k.replace("_", " ").title()
        direction = v.get("direction", "STABLE")
        cagr      = v.get("cagr_pct", 0)
        if direction == "DEGRADATION":
            parts.append(f"- The **{name}** ratio shows a declining trend ({cagr:+.1f}%/year), signaling a risk to monitor.")
        elif direction in ("ACHIEVEMENT", "AMELIORATION"):
            parts.append(f"- The **{name}** ratio shows an improving trend ({cagr:+.1f}%/year), consolidating its strength.")
        else:
            parts.append(f"- The **{name}** ratio remains stable ({cagr:+.1f}%/year).")
    return "\n".join(parts)


def _build_section_06(ratio_sets: list, interpretation: dict, trends_summary: dict = None) -> str:
    if not ratio_sets:
        return ("Financial data not available or not yet entered. "
                "This section will be completed after financial statements are ingested.")

    years  = [str(r.get("fiscal_year", "?")) for r in ratio_sets]
    header = "| Ratio | " + " | ".join(years) + " |"
    sep    = "|" + "|".join(["---"] * (len(years) + 1)) + "|"

    def row(label, key, fmt=".3f", suffix=""):
        vals = []
        for r in ratio_sets:
            v = r.get(key)
            vals.append(f"{float(v):{fmt}}{suffix}" if v is not None else "N/A")
        return f"| {label} | " + " | ".join(vals) + " |"

    table = "\n".join([header, sep,
        row("Current Ratio",       "current_ratio"),
        row("Quick Ratio",         "quick_ratio"),
        row("Cash Ratio",          "cash_ratio"),
        row("Debt to Equity",      "debt_to_equity"),
        row("Financial Autonomy",  "financial_autonomy", ".2%"),
        row("Net Margin",          "net_margin",         ".2f", "%"),
        row("ROE",                 "roe",                 ".2f", "%"),
        row("DSO (days)",          "dso_days",            ".0f", "d"),
        row("Cash Flow (CAF)",     "caf",                 ",.0f"),
        row("Repayment Cap. (yrs)","debt_repayment_years",".1f"),
    ])

    liq_l = interpretation.get("liquidity_label",  "N/R")
    liq_c = interpretation.get("liquidity_comment", "")
    sol_l = interpretation.get("solvency_label",  "N/R")
    sol_c = interpretation.get("solvency_comment", "")
    ren_l = interpretation.get("profitability_label",  "N/R")
    ren_c = interpretation.get("profitability_comment", "")
    dyn   = interpretation.get("dynamic_analysis_comment", "")
    narrative = _build_trend_narrative(trends_summary or {})

    return (
        f"### Financial Ratio Table\n\n{table}\n\n"
        f"### Pillar Interpretation\n\n"
        f"**Liquidity ({liq_l}):** {liq_c}\n\n"
        f"**Solvency ({sol_l}):** {sol_c}\n\n"
        f"**Profitability ({ren_l}):** {ren_c}\n\n"
        f"**Dynamic Analysis (Trends):** {dyn}\n\n{narrative}"
    )


def _build_section_07(capacity: dict) -> str:
    if not capacity:
        return ("Contract capacity assessment not available. "
                "This section will be completed after market data is ingested.")
    currency     = capacity.get("currency", "USD")
    stress_rows  = []
    flows        = capacity.get("monthly_flows", [])
    bfr          = float(capacity.get("bfr_estimate") or 0)
    scenarios    = {
        "S1_BASE":      "Base Scenario (Nominal payments)",
        "S2_RETARD_60": "60-Day Stress (Payment delay)",
        "S3_RETARD_90": "90-Day Stress (Payment delay)",
        "S4_COST_OVR":  "Cost Overrun (+15%)",
        "S5_CA_SHOCK":  "Revenue Shock (-20%)",
        "S6_EXTREME":   "Major Crisis (90d delay + 15% Costs + -20% Revenue)",
    }
    if flows:
        for s_code, s_label in scenarios.items():
            min_cash = min([f.get(f"cash_{s_code}", float("inf")) for f in flows], default=float("inf"))
            if min_cash != float("inf"):
                verdict = "INSOLVENT" if min_cash < 0 else ("LIMIT" if min_cash < bfr * 0.20 else "SOLVENT")
                stress_rows.append(f"| {s_label} | {_fmt_amount(min_cash)} {currency} | {verdict} |")
    if not stress_rows:
        stress_rows.append(f"| 60-Day Stress | {_fmt_amount(capacity.get('stress_60d_cash_position'))} {currency} | {capacity.get('stress_60d_result', 'N/A')} |")
        stress_rows.append(f"| 90-Day Stress | {_fmt_amount(capacity.get('stress_90d_cash_position'))} {currency} | {capacity.get('stress_90d_result', 'N/A')} |")

    stress_table = "\n".join(stress_rows)
    return (
        f"### Contractual Parameters\n\n"
        f"| Parameter | Value |\n|-----------|-------|\n"
        f"| Contract Value | {_fmt_amount(capacity.get('contract_value'))} {currency} |\n"
        f"| Estimated Annual Disbursement | {_fmt_amount(capacity.get('annual_disbursement'))} {currency} |\n"
        f"| Average Annual Revenue | {_fmt_amount(capacity.get('annual_ca_avg'))} {currency} |\n"
        f"| Contractual Exposure | {float(capacity.get('exposition_pct') or 0):.1f}% of Revenue |\n"
        f"| Available Cash | {_fmt_amount(capacity.get('cash_available'))} {currency} |\n"
        f"| Estimated WCR for Contract | {_fmt_amount(capacity.get('bfr_estimate'))} {currency} |\n"
        f"| Average Cash Flow (CAF) | {_fmt_amount(capacity.get('caf_avg'))} {currency} |\n\n"
        f"### Multi-Factor Stress Test Results\n\n"
        f"| Scenario | Min. Cash Position | Verdict |\n|----------|-------------------|---------|"
        f"\n{stress_table}\n\n"
        f"**Capacity Score:** {float(capacity.get('score_capacite') or 0):.2f} / 5\n\n"
        f"**Conclusion:** {capacity.get('capacity_conclusion', 'N/A')}"
    )


def _build_section_08(scorecard: dict, gate: dict) -> str:
    overrides     = scorecard.get("overrides_applied", [])
    gate_blocking = gate.get("blocking_flags", [])
    gate_reserves = gate.get("reserve_flags", [])
    auto_flags    = [o for o in overrides if o.get("auto")]
    manual_flags  = [o for o in overrides if not o.get("auto")]
    all_critical  = gate_blocking + [o.get("code", str(o)) for o in auto_flags]
    if not all_critical and not gate_reserves and not manual_flags:
        return "No major red flags identified in this analysis."
    parts = []
    if all_critical:
        parts.append("### Critical / Blocking Red Flags\n")
        for f in all_critical:
            parts.append(f"- 🔴 **{f}**")
    if gate_reserves:
        parts.append("\n### Documentary Reserves\n")
        for r in gate_reserves:
            parts.append(f"- 🟠 {r}")
    if manual_flags:
        parts.append("\n### Documented Manual Overrides\n")
        for o in manual_flags:
            parts.append(f"- ⚠️ **{o.get('code', 'N/A')}** → Proposed Class: {o.get('proposed_risk_class', 'N/A')} — Justification: {o.get('justification', 'N/A')}")
    parts.append("\nEach red flag was taken into account in the final fiduciary risk classification. Manual overrides are documented and auditable.")
    return "\n".join(parts)


def _build_section_09(scorecard: dict) -> str:
    overrides = scorecard.get("overrides_applied", [])
    manual_up = [o for o in overrides if not o.get("auto") and o.get("type") == "MANUAL_UPGRADE"]
    if not manual_up:
        return ("Potential mitigating factors were examined. No formally documented mitigants were retained "
                "in this analysis.\n\nIn accordance with MCC-grade standards, a mitigant can only be "
                "integrated into the final classification if it is supported by verifiable evidence.")
    items = "\n".join(f"- **{o.get('code', 'N/A')}** — {o.get('justification', 'N/A')}" for o in manual_up)
    return (f"The following mitigating factors were identified and documented:\n\n{items}\n\n"
            "These mitigants were taken into account in the final fiduciary risk classification.")


def _build_section_10(scorecard: dict) -> str:
    if not scorecard:
        return "Scoring not available. Complete pillar interpretation."
    s  = scorecard
    sg = float(s.get("score_global") or 0)
    overrides = s.get("overrides_applied", [])
    override_txt = ""
    if overrides:
        override_lines = "\n".join(
            f"- **{o.get('code', o.get('type', 'N/A'))}** : {o.get('justification', 'N/A')} → Imposed Class: {o.get('proposed_risk_class', 'N/A')}"
            for o in overrides
        )
        override_txt = f"\n\n### Applied Overrides\n\n{override_lines}"
    return (
        f"### Pillar Scoring Details\n\n"
        f"| Pillar | Score (/5) | Weight | Contribution |\n|--------|-----------|-------|-------------|\n"
        f"| Liquidity       | {float(s.get('score_liquidite') or 0):.3f} | 25% | {float(s.get('score_liquidite') or 0)*0.25:.4f} |\n"
        f"| Solvency        | {float(s.get('score_solvabilite') or 0):.3f} | 25% | {float(s.get('score_solvabilite') or 0)*0.25:.4f} |\n"
        f"| Profitability   | {float(s.get('score_rentabilite') or 0):.3f} | 15% | {float(s.get('score_rentabilite') or 0)*0.15:.4f} |\n"
        f"| Capacity        | {float(s.get('score_capacite') or 0):.3f} | 25% | {float(s.get('score_capacite') or 0)*0.25:.4f} |\n"
        f"| Quality/Reliab. | {float(s.get('score_qualite') or 0):.3f} | 10% | {float(s.get('score_qualite') or 0)*0.10:.4f} |\n"
        f"| **Overall Score**| **{sg:.3f}** | **100%** | **{sg:.4f}** |\n\n"
        f"**Risk Class (scoring based):** {s.get('risk_class', 'N/A')}\n\n"
        f"**Final Risk Class (after overrides):** **{s.get('final_risk_class', 'N/A')}**{override_txt}"
    )


def _build_section_11(scorecard: dict) -> str:
    risk  = scorecard.get("final_risk_class", "N/A")
    score = float(scorecard.get("score_global") or 0)
    escalade_map = {
        "LOW":      "🟢 **Low Risk** — Standard validation. Financial capacity is deemed satisfactory. No specific contractual protection measures are required.",
        "MODERATE":   "🟡 **Moderate Risk** — Acceptance possible with documented mitigation measures. Standard contractual guarantees (performance bonds) are recommended.",
        "HIGH":     "🟠 **High Risk** — Mandatory senior review. Reinforced contractual protections are required (first-demand bank guarantees, retention money, conditional payment milestones).",
        "CRITICAL": "🔴 **Critical Risk** — Rejection recommended. Fiduciary risk is incompatible with program requirements.",
    }
    appreciation = escalade_map.get(risk, f"Risk Class: {risk}")
    return (f"Based on the MCC-grade scoring (score: {score:.3f}/5.000) and the qualitative elements analyzed, "
            f"the overall fiduciary risk is assessed as follows:\n\n{appreciation}\n\n"
            "This assessment incorporates all information available at the date of analysis and may be revised should material new evidence emerge.")


def _build_section_12(recommendation: str, scorecard: dict, capacity: dict) -> str:
    risk     = scorecard.get("final_risk_class", "N/A")
    coverage = capacity.get("coverage_status", "N/A") if capacity else "N/A"
    overrides= scorecard.get("overrides_applied", [])
    reco_map = {
        "ACCEPT": "**RECOMMENDATION: ACCEPTANCE**\n\nThe bidder's financial capacity is deemed satisfactory in view of the program's fiduciary requirements. Contract award is financially sustainable.\n\n**Conditions:** No specific conditions.",
        "CONDITIONAL_ACCEPT": "**RECOMMENDATION: CONDITIONAL ACCEPTANCE**\n\nFinancial capacity is acceptable under conditions. Award should only be considered after obtaining and verifying the following guarantees:\n\n- Performance bank guarantee (minimum 10% of contract amount)\n- Confirmation of committed credit lines covering the estimated WCR\n- Advance payment bond if advance > 10%\n\n**Recommended monitoring:** Quarterly financial reports during the contract term.",
        "REJECT_RECOMMENDED": "**RECOMMENDATION: REJECTION**\n\nThe bidder's financial capacity is insufficient relative to MCC program fiduciary requirements. The risk of contract default is deemed unacceptable.\n\nContract award is not recommended under current conditions.",
    }
    base_text = reco_map.get(recommendation, "**RECOMMENDATION: Not determined.** Complete analysis before finalizing the report.")
    context = f"\n\n**Risk Class:** {risk} | **Contractual Capacity:** {coverage}"
    if overrides:
        context += f" | **Applied Overrides:** {len(overrides)}"
    return base_text + context


def _build_section_13(gate: dict) -> str:
    reliability = gate.get("reliability_level", "N/A")
    reserves    = gate.get("reserve_flags", [])
    years       = gate.get("fiscal_years_covered", [])
    limits = [
        "This analysis is based on financial information provided by the bidder. Its accuracy has not been subject to independent verification by the analyst.",
        f"The reliability level of the documents is estimated as **{reliability}**. Unaudited documents or documents with limited reliability reduce confidence in the conclusions.",
    ]
    if len(years) < 3:
        limits.append(f"Time coverage is limited to {len(years)} fiscal year(s). Analysis over at least 3 fiscal years is recommended for a full trend assessment.")
    if reserves:
        limits.append("Documentary reserves were identified during the documentary gate. These reserves are detailed in Section 3.")
    limits += [
        "The analysis does not cover legal, technical, or operational aspects of the bidder's capacity.",
        "Projections and stress tests are based on simplifying assumptions. Actual results may differ significantly from estimates.",
        "This report is valid as of the date of issuance. Any material change in the bidder's financial situation after this date is not taken into account.",
    ]
    return "\n".join(f"- {l}" for l in limits)


def _build_section_14(recommendation: str, scorecard: dict) -> str:
    risk  = scorecard.get("final_risk_class", "N/A")
    score = float(scorecard.get("score_global") or 0)
    reco_map = {
        "ACCEPT": "The bidder's financial capacity is deemed satisfactory relative to program requirements. Contract award is financially sustainable.",
        "CONDITIONAL_ACCEPT": "The bidder's financial capacity is deemed acceptable under conditions. Award should only be considered after obtaining and verifying the guarantees documented in Section 12.",
        "REJECT_RECOMMENDED": "The bidder's financial capacity is insufficient relative to MCC program fiduciary requirements. The risk of contract default is deemed unacceptable. Award is not recommended.",
    }
    reco_text = reco_map.get(recommendation, "Recommendation not determined — finalize analysis.")
    computed_at = scorecard.get("computed_at", "N/A")
    if isinstance(computed_at, datetime):
        computed_at = computed_at.isoformat(sep=" ", timespec="seconds")
    audit_trail = (
        f"### Technical Annex: Audit Trail\n\n"
        f"- **Engine Version:** FinaCES V1.2\n"
        f"- **Policy Version:** {scorecard.get('policy_version_id', 'N/A')}\n"
        f"- **Scoring Timestamp:** {computed_at}\n"
        f"- **Report Identifier:** (Generated upon validation)\n"
    )
    return (
        f"This report constitutes the formal conclusion of the bidder's financial analysis, "
        f"conducted in accordance with MCC-grade standards.\n\n"
        f"**Final Risk Class: {risk}** (score: {score:.3f}/5.000)\n\n"
        f"{reco_text}\n\n"
        f"This recommendation has been produced in a standardized manner, based on versioned scoring rules "
        f"and verifiable documentary evidence. It is fully reconcilable by a third-party auditor "
        f"from the data recorded in the FinaCES system.\n\n---\n\n{audit_trail}"
    )


def _build_section_consortium(consortium: dict) -> str:
    if not consortium:
        return ""
    members_text = ""
    for m in consortium.get("members", []):
        members_text += (
            f"- **{m.get('bidder_name', 'N/A')}** "
            f"({m.get('role', 'N/A')}, {m.get('participation_pct', 0):.1f}%) — "
            f"Score: {m.get('score_global', 0):.3f} — "
            f"Class: {m.get('final_risk_class', 'N/A')}"
        )
        if m.get("is_weak_link"):
            members_text += " ⚠️ **WEAK LINK**"
        members_text += "\n"
    mitigations = "\n".join(f"- {m}" for m in consortium.get("mitigations_suggested", [])) or "No specific mitigation measures."
    ci    = consortium.get("synergy_index")
    bonus = consortium.get("synergy_bonus")
    synergy_line = f"**Complementarity Index (CI):** {ci:.4f}\n\n**Applied Synergy Bonus:** +{bonus:.2f}\n\n" if ci is not None and bonus is not None else ""
    return (
        f"### Consortium / JV Analysis\n\n"
        f"**Consortium Type:** {consortium.get('jv_type', 'N/A')}\n\n"
        f"**Aggregation Method:** {consortium.get('aggregation_method', 'N/A')}\n\n"
        f"{synergy_line}"
        f"**Members:**\n{members_text}\n"
        f"**Weighted Consolidated Score:** {consortium.get('weighted_score', 0):.4f}\n\n"
        f"**Weak Link Rule:** {'⚠️ Triggered — ' + str(consortium.get('weak_link_member', '')) if consortium.get('weak_link_triggered') else '✅ Not triggered'}\n\n"
        f"**Leader Blocking:** {'🔴 Yes' if consortium.get('leader_blocking') else '✅ No'}\n\n"
        f"**Final Consortium Classification:** **{consortium.get('final_risk_class', 'N/A')}**\n\n"
        f"**Aggregated Stress Test:** {consortium.get('aggregated_stress', 'N/A')}\n\n"
        f"**Suggested Mitigation Measures:**\n{mitigations}"
    )


def _fmt_amount(v) -> str:
    try:
        return f"{float(v):,.0f}" if v is not None else "N/A"
    except Exception:
        return "N/A"
