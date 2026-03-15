from decimal import Decimal
from typing import Dict, Any, List, Optional
from app.schemas.comparison_schema import TemporalComparisonSchema, TemporalDataPoint, BenchmarkResultSchema, BenchmarkMetricResult
from app.schemas.ratio_schema import RatioSetSchema
from app.schemas.policy_schema import PolicyConfigurationSchema
import datetime

def _safe_divide(num: Optional[Decimal], den: Optional[Decimal]) -> Optional[Decimal]:
    """Safe division preventing ZeroDivisionError and handling None values."""
    if num is None or den is None or den == Decimal("0.0"):
        return None
    return num / den

def compute_temporal_comparison(case_id: str, ratio_series: List[RatioSetSchema], policy: PolicyConfigurationSchema) -> TemporalComparisonSchema:
    if not ratio_series:
        return TemporalComparisonSchema(
            status="EMPTY",
            case_id=case_id,
            years_covered=[],
            data={},
            trend="NOT_EVALUATED",
            dynamic_risk_alerts=["No historical data available for temporal analysis."]
        )
    
    margin_threshold = policy.alert_thresholds["margin_trend"].warn if "margin_trend" in policy.alert_thresholds and policy.alert_thresholds["margin_trend"].warn else Decimal("5.0")
    de_growth_threshold = policy.alert_thresholds["de_growth"].warn if "de_growth" in policy.alert_thresholds and policy.alert_thresholds["de_growth"].warn else Decimal("0.5")
    de_max_threshold = policy.alert_thresholds["de_max"].max if "de_max" in policy.alert_thresholds and policy.alert_thresholds["de_max"].max else Decimal("2.0")
    
    sorted_ratios = sorted(ratio_series, key=lambda x: x.fiscal_year)
    years_data = {}
    
    for r in sorted_ratios:
        years_data[r.fiscal_year] = TemporalDataPoint(
            fiscal_year=r.fiscal_year,
            current_ratio=r.current_ratio,
            debt_to_equity=r.debt_to_equity,
            net_margin=r.net_margin,
            cash_flow_capacity=r.cash_flow_capacity
        )
        
    trend = "STABLE"
    alerts = []
    
    if len(sorted_ratios) >= 2:
        first_yr = sorted_ratios[0]
        last_yr = sorted_ratios[-1]
        
        n_years = last_yr.fiscal_year - first_yr.fiscal_year
        
        if n_years > 0:
            # 1. Net Margin (Annualized Delta)
            if last_yr.net_margin is not None and first_yr.net_margin is not None:
                annualized_margin_delta = (last_yr.net_margin - first_yr.net_margin) / Decimal(str(n_years))
                if annualized_margin_delta > margin_threshold:
                    trend = "IMPROVEMENT"
                elif annualized_margin_delta < -margin_threshold:
                    trend = "DEGRADATION"
                    
            # 2. Debt to Equity (CAGR Calculation - P1-MULTIYEAR-02 Fixed)
            if first_yr.debt_to_equity is not None and last_yr.debt_to_equity is not None:
                if first_yr.debt_to_equity > Decimal("0.0"):
                    ratio = float(last_yr.debt_to_equity / first_yr.debt_to_equity)
                    # CAGR = (Ending Value / Beginning Value) ^ (1 / n_years) - 1
                    cagr = Decimal(str((ratio ** (1.0 / n_years)) - 1.0))
                    
                    if cagr > de_growth_threshold and last_yr.debt_to_equity > de_max_threshold:
                        alerts.append(f"⚠️ Rapid degradation of the financial structure: D/E ratio grew by {cagr*100:.1f}% per year (CAGR).")
                    
    return TemporalComparisonSchema(
        status="OK",
        case_id=case_id,
        years_covered=list(years_data.keys()),
        data=years_data,
        trend=trend,
        dynamic_risk_alerts=alerts
    )

def compute_sector_benchmark(case_id: str, sector: str, latest_ratios: RatioSetSchema, policy: PolicyConfigurationSchema) -> BenchmarkResultSchema:
    benchmarks = policy.sector_benchmarks.get(sector, policy.sector_benchmarks.get("DEFAULT"))
    if not benchmarks:
        return BenchmarkResultSchema(
            status="ERROR",
            case_id=case_id,
            detected_sector=sector,
            analysis={}
        )
        
    analysis_res = {}
    
    # Check D/E
    if latest_ratios.debt_to_equity is not None:
        val = latest_ratios.debt_to_equity
        max_tol = Decimal(str(benchmarks["debt_to_equity"]["max_tolerated"]))
        status = "OUT_OF_NORM" if val > max_tol else "WITHIN_NORM"
        analysis_res["debt_to_equity"] = BenchmarkMetricResult(
            name=benchmarks["debt_to_equity"]["name"],
            value=val,
            reference_max=max_tol,
            status=status
        )
        
    # Check DSO
    if latest_ratios.dso_days is not None:
        val = latest_ratios.dso_days
        max_tol = Decimal(str(benchmarks["dso_days"]["max_tolerated"]))
        status = "OUT_OF_NORM" if val > max_tol else "WITHIN_NORM"
        analysis_res["dso_days"] = BenchmarkMetricResult(
            name=benchmarks["dso_days"]["name"],
            value=val,
            reference_max=max_tol,
            status=status
        )
        
    # Check Net Margin
    if latest_ratios.net_margin is not None:
        val = latest_ratios.net_margin
        min_tol = Decimal(str(benchmarks["net_margin"]["min_tolerated"]))
        status = "OUT_OF_NORM" if val < min_tol else "WITHIN_NORM"
        analysis_res["net_margin"] = BenchmarkMetricResult(
            name=benchmarks["net_margin"]["name"],
            value=val,
            reference_min=min_tol,
            status=status
        )
        
    return BenchmarkResultSchema(
        status="OK",
        case_id=case_id,
        detected_sector=sector,
        analysis=analysis_res
    )
