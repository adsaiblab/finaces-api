from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple
from app.schemas.consortium_schema import ConsortiumInputSchema, ConsortiumScorecardOutput
from app.schemas.policy_schema import PolicyConfigurationSchema
from datetime import datetime, timezone
from app.engines._risk_utils import get_risk_band

def _calculate_synergy(members: List[dict], syn_limits: dict, syn_bonus: dict) -> Tuple[Decimal, Decimal]:
    pillars = ["score_liquidity", "score_solvency", "score_profitability", "score_capacity"]
    num_members = len(members)
    
    if num_members < 2:
        return Decimal("0.0"), Decimal("0.0")
        
    total_comparisons = 0
    compensations_found = 0
    
    for i in range(num_members):
        for j in range(i + 1, num_members):
            m1 = members[i]
            m2 = members[j]
            
            for p in pillars:
                total_comparisons += 1
                s1 = getattr(m1, p, None)
                s2 = getattr(m2, p, None)
                
                if s1 is not None and s2 is not None:
                    if (s1 >= Decimal("3.5") and s2 < Decimal("2.5")) or (s2 >= Decimal("3.5") and s1 < Decimal("2.5")):
                        compensations_found += 1
                        
    ci = Decimal("0.0")
    if total_comparisons > 0:
        ci = (Decimal(compensations_found) / Decimal(total_comparisons)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        
    bonus = Decimal("0.0")
    if ci > Decimal(str(syn_limits.get("high", 0.30))):
        bonus = Decimal(str(syn_bonus.get("high", 0.50)))
    elif ci > Decimal(str(syn_limits.get("medium", 0.15))):
        bonus = Decimal(str(syn_bonus.get("medium", 0.25)))
        
    return ci, bonus

def _aggregate_stress(verdicts: List[str]) -> str:
    priority = {"INSOLVENT": 2, "LIMIT": 1, "SOLVENT": 0, "N/A": -1}
    worst = max(verdicts, key=lambda v: priority.get(v, -1))
    return worst

def _suggest_mitigations(weak_link_triggered: bool, leader_blocking: bool, final_risk_class: str) -> List[str]:
    m = []
    if leader_blocking:
        m.append("Leader replacement or reinforcement recommended (critical fiduciary risk).")
    if weak_link_triggered:
        m.append("Joint bank guarantee covering at least 30% of the contractual amount, issued by a tier-1 institution.")
        m.append("Weak link substitution clause by a financially qualified member in case of default.")
    if final_risk_class in ("HIGH", "CRITICAL"):
        m.append("Payment retention (5-10%) releasable upon completion of each contractual milestone.")
        m.append("Requirement for a performance bond (10% of the market value).")
    if final_risk_class == "MODERATE":
        m.append("Enhanced monitoring: quarterly financial reports during the contract duration.")
    if not m:
        m.append("No specific mitigation measures required.")
    return m



def compute_consortium_scorecard(consortium_input: ConsortiumInputSchema, policy: PolicyConfigurationSchema) -> ConsortiumScorecardOutput:
    members = consortium_input.members
    
    method = policy.consortium_aggregation_methods.get(consortium_input.jv_type, "weighted_average_participation")
    
    ci_score, synergy_bonus = _calculate_synergy(
        members, 
        policy.consortium.synergy_limits,
        policy.consortium.synergy_bonus
    )
    
    leader = next((m for m in members if getattr(m, "role", None) == "LEADER"), members[0] if members else None)
    
    if method == "leader_only":
        weighted_score = getattr(leader, "score_global", Decimal("0.0")) if leader else Decimal("0.0")
    else:
        # Weighted average
        weighted_sum = sum([getattr(m, "score_global", Decimal("0.0")) * (getattr(m, "participation_pct", Decimal("0.0")) / Decimal("100.0")) for m in members])
        weighted_score = weighted_sum
    
    weak_link_trigger = "HIGH"
    weak_link_member = None
    weak_link_triggered = False
    
    for member in members:
        member_class = getattr(member, "final_risk_class", "LOW")
        if not member_class:
            member_class = "LOW"
        if policy.risk_priority_map.get(member_class, 0) >= policy.risk_priority_map.get(weak_link_trigger, 3):
            weak_link_triggered = True
            weak_link_member = getattr(member, "bidder_name", None)
            break
            
    if not weak_link_triggered:
        weighted_score += synergy_bonus
    weighted_score = min(Decimal("5.0"), weighted_score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    
    base_risk_class = get_risk_band(weighted_score, policy)
    
    leader_blocking = False
    leader_override = False
    if leader:
        if getattr(leader, "final_risk_class", None) == "CRITICAL":
            leader_blocking = True
        
        leader_score = getattr(leader, "score_global", Decimal("0.0"))
        if leader_score is None:
            leader_score = Decimal("0.0")
        if leader_score < Decimal("3.0"):
            leader_override = True
            if base_risk_class not in ("HIGH", "CRITICAL"):
                base_risk_class = "HIGH"
                
    if leader_blocking:
        final_risk_class = "CRITICAL"
        weighted_score = min(weighted_score, Decimal("1.5"))
    elif weak_link_triggered:
        final_risk_class = "HIGH"
        if policy.risk_priority_map.get(base_risk_class, 0) > policy.risk_priority_map.get("HIGH", 0):
            final_risk_class = base_risk_class
        weighted_score = min(weighted_score, Decimal("2.5"))
    else:
        final_risk_class = base_risk_class
        
    stress_verdicts = [getattr(m, "stress_60d_result", "N/A") or "N/A" for m in members]
    aggregated_stress = _aggregate_stress(stress_verdicts)
    
    mitigations = _suggest_mitigations(weak_link_triggered, leader_blocking, final_risk_class)
    
    members_enriched = []
    for m in members:
        members_enriched.append({
            "bidder_id": getattr(m, "bidder_id", None),
            "bidder_name": getattr(m, "bidder_name", "N/A"),
            "role": getattr(m, "role", "MEMBER") or "MEMBER",
            "participation_pct": str(getattr(m, "participation_pct", "0.0") or "0.0"),
            "score_global": str(getattr(m, "score_global", "0.0") or "0.0"),
            "final_risk_class": getattr(m, "final_risk_class", "N/A") or "N/A",
            "stress_60d": getattr(m, "stress_60d_result", "N/A") or "N/A",
            "is_weak_link": getattr(m, "bidder_name", None) == weak_link_member,
        })

    return ConsortiumScorecardOutput(
        consortium_id=consortium_input.consortium_id,
        jv_type=consortium_input.jv_type,
        aggregation_method=method,
        weighted_score=weighted_score,
        synergy_index=ci_score,
        synergy_bonus=synergy_bonus,
        base_risk_class=base_risk_class,
        final_risk_class=final_risk_class,
        weak_link_triggered=weak_link_triggered,
        weak_link_member=weak_link_member,
        leader_blocking=leader_blocking,
        leader_override=leader_override,
        aggregated_stress=aggregated_stress,
        members=members_enriched,
        mitigations_suggested=mitigations,
        computed_at=datetime.now(timezone.utc).isoformat()
    )
