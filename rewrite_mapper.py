with open("../finaces-front/src/app/core/mappers/ratio.mapper.ts", "r") as f:
    text = f.read()

# 1. Update `toRatioValue`
text = text.replace(
    "function toRatioValue(current: any, unit: RatioValue['unit'] = 'ratio'): RatioValue {",
    "function toRatioValue(current: any, variation_pct: any = 0, unit: RatioValue['unit'] = 'ratio'): RatioValue {"
)
text = text.replace(
    "    variation_pct: 0,",
    "    variation_pct: variation_pct != null ? parseFloat(String(variation_pct)) : 0,"
)

# 2. Update all liquidity
text = text.replace("toRatioValue(flat.current_ratio)", "toRatioValue(flat.current_ratio, flat.current_ratio_variation_pct)")
text = text.replace("toRatioValue(flat.quick_ratio)", "toRatioValue(flat.quick_ratio, flat.quick_ratio_variation_pct)")
text = text.replace("toRatioValue(flat.cash_ratio)", "toRatioValue(flat.cash_ratio, flat.cash_ratio_variation_pct)")
text = text.replace("toRatioValue(flat.working_capital, 'currency')", "toRatioValue(flat.working_capital, flat.working_capital_variation_pct, 'currency')")
text = text.replace("toRatioValue(flat.working_capital_requirement, 'currency')", "toRatioValue(flat.working_capital_requirement, flat.working_capital_requirement_variation_pct, 'currency')")
text = text.replace("toRatioValue(flat.working_capital_requirement_pct_revenue, '%')", "toRatioValue(flat.working_capital_requirement_pct_revenue, flat.working_capital_requirement_pct_revenue_variation_pct, '%')")
text = text.replace("toRatioValue(flat.dso_days, 'days')", "toRatioValue(flat.dso_days, flat.dso_days_variation_pct, 'days')")
text = text.replace("toRatioValue(flat.dpo_days, 'days')", "toRatioValue(flat.dpo_days, flat.dpo_days_variation_pct, 'days')")
text = text.replace("toRatioValue(flat.dio_days ?? null, 'days')", "toRatioValue(flat.dio_days ?? null, flat.dio_days_variation_pct ?? null, 'days')")
text = text.replace("toRatioValue(flat.cash_conversion_cycle ?? null, 'days')", "toRatioValue(flat.cash_conversion_cycle ?? null, flat.cash_conversion_cycle_variation_pct ?? null, 'days')")

# Solvency
text = text.replace("toRatioValue(flat.debt_to_equity)", "toRatioValue(flat.debt_to_equity, flat.debt_to_equity_variation_pct)")
text = text.replace("toRatioValue(flat.financial_autonomy)", "toRatioValue(flat.financial_autonomy, flat.financial_autonomy_variation_pct)")
text = text.replace("toRatioValue(flat.gearing)", "toRatioValue(flat.gearing, flat.gearing_variation_pct)")
text = text.replace("toRatioValue(flat.interest_coverage ?? null)", "toRatioValue(flat.interest_coverage ?? null, flat.interest_coverage_variation_pct ?? null)")
text = text.replace("toRatioValue(flat.debt_repayment_years ?? null)", "toRatioValue(flat.debt_repayment_years ?? null, flat.debt_repayment_years_variation_pct ?? null)")
text = text.replace("toRatioValue(flat.negative_equity ?? 0, 'binary')", "toRatioValue(flat.negative_equity ?? 0, 0, 'binary')")

# Profitability
text = text.replace("toRatioValue(flat.net_margin, '%')", "toRatioValue(flat.net_margin, flat.net_margin_variation_pct, '%')")
text = text.replace("toRatioValue(flat.ebitda_margin, '%')", "toRatioValue(flat.ebitda_margin, flat.ebitda_margin_variation_pct, '%')")
text = text.replace("toRatioValue(flat.operating_margin, '%')", "toRatioValue(flat.operating_margin, flat.operating_margin_variation_pct, '%')")
text = text.replace("toRatioValue(flat.roa, '%')", "toRatioValue(flat.roa, flat.roa_variation_pct, '%')")
text = text.replace("toRatioValue(flat.roe, '%')", "toRatioValue(flat.roe, flat.roe_variation_pct, '%')")

# Capacity
text = text.replace("toRatioValue(flat.cash_flow_capacity ?? null)", "toRatioValue(flat.cash_flow_capacity ?? null, flat.cash_flow_capacity_variation_pct ?? null)")
text = text.replace("toRatioValue(flat.cash_flow_capacity_margin_pct ?? null, '%')", "toRatioValue(flat.cash_flow_capacity_margin_pct ?? null, flat.cash_flow_capacity_margin_pct_variation_pct ?? null, '%')")
text = text.replace("toRatioValue(null, 'currency')", "toRatioValue(null, 0, 'currency')")

# ZScore
text = text.replace("toRatioValue(flat.z_score_altman)", "toRatioValue(flat.z_score_altman, 0) # Altman doesn't have variation stored or maybe it does? Assume 0 for now since z_score variations are tricky")


# 3. Delete applyVariations cleanly (find index)
apply_var_idx = text.find("  /**\n   * Computes variation_pct")
if apply_var_idx != -1:
    end_idx = text.find("  }", apply_var_idx) + 4
    # we need to find the final closing bracket of the class
    end_idx2 = text.find("}", end_idx)
    text = text[:apply_var_idx] + "}\n"

with open("../finaces-front/src/app/core/mappers/ratio.mapper.ts", "w") as f:
    f.write(text)
