"""alignment_enums_and_columns

Revision ID: c3a1f9d82e01
Revises: abe7f8b87247
Create Date: 2026-03-28

Aligns enums and adds new columns per IMPLEMENTATION_ALIGNMENT_FINACES.md:
- CaseStatus: 5 -> 10 states
- CaseType: +LOTS
- RiskClass: MEDIUM -> MODERATE
- RiskProfile: FR -> EN
- FinancialStatement: +other_noncurrent_assets, +extraordinary_expenses, +dividends
- ExpertReview: per-pillar comments + new fields
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3a1f9d82e01'
down_revision: Union[str, Sequence[str], None] = 'abe7f8b87247'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════
    # T02 — CaseStatus: Add new values (5 → 10 states)
    # Note: native_enum=False means values are stored as VARCHAR,
    # so no ALTER TYPE needed — just update existing rows.
    # ═══════════════════════════════════════════════════════════
    op.execute("UPDATE evaluation_cases SET status = 'PENDING_GATE' WHERE status = 'IN_ANALYSIS'")
    op.execute("UPDATE evaluation_cases SET status = 'SCORING_DONE' WHERE status = 'SCORING'")
    op.execute("UPDATE evaluation_cases SET status = 'CLOSED' WHERE status = 'COMPLETED'")

    # ═══════════════════════════════════════════════════════════
    # T04 — RiskClass: MEDIUM → MODERATE
    # ═══════════════════════════════════════════════════════════
    op.execute("UPDATE scorecards SET risk_class = 'MODERATE' WHERE risk_class = 'MEDIUM'")
    op.execute("UPDATE consortium_results SET base_risk_class = 'MODERATE' WHERE base_risk_class = 'MEDIUM'")
    op.execute("UPDATE consortium_results SET final_risk_class = 'MODERATE' WHERE final_risk_class = 'MEDIUM'")
    op.execute("UPDATE ia_predictions SET ia_risk_class = 'MODERATE' WHERE ia_risk_class = 'MEDIUM'")

    # ═══════════════════════════════════════════════════════════
    # T05 — RiskProfile: FR → EN
    # ═══════════════════════════════════════════════════════════
    risk_profile_mapping = {
        "EQUILIBRE": "BALANCED",
        "ASYMETRIQUE": "ASYMMETRICAL",
        "AGRESSIF": "AGGRESSIVE",
        "DEFENSIF": "DEFENSIVE",
        "CLASSIQUE": "CLASSIC",
    }
    for old_val, new_val in risk_profile_mapping.items():
        op.execute(
            f"UPDATE scorecards SET risk_profile = '{new_val}' WHERE risk_profile = '{old_val}'"
        )

    # ═══════════════════════════════════════════════════════════
    # T06 — FinancialStatement: New columns
    # (investing_cash_flow, financing_cash_flow, dividends_distributed already exist in raw)
    # ═══════════════════════════════════════════════════════════
    # Add to raw statements (only truly new columns)
    op.add_column("financial_statements_raw",
        sa.Column("other_noncurrent_assets", sa.Numeric(18, 2), nullable=True, server_default="0"))
    op.add_column("financial_statements_raw",
        sa.Column("extraordinary_expenses", sa.Numeric(18, 2), nullable=True, server_default="0"))
    op.add_column("financial_statements_raw",
        sa.Column("gross_profit", sa.Numeric(18, 2), nullable=True, server_default="0"))
    op.add_column("financial_statements_raw",
        sa.Column("free_cash_flow", sa.Numeric(18, 2), nullable=True, server_default="0"))

    # Add to normalized statements
    op.add_column("financial_statements_normalized",
        sa.Column("other_noncurrent_assets", sa.Numeric(18, 2), nullable=True, server_default="0"))
    op.add_column("financial_statements_normalized",
        sa.Column("extraordinary_expenses", sa.Numeric(18, 2), nullable=True, server_default="0"))
    op.add_column("financial_statements_normalized",
        sa.Column("dividends", sa.Numeric(18, 2), nullable=True, server_default="0"))
    op.add_column("financial_statements_normalized",
        sa.Column("gross_profit", sa.Numeric(18, 2), nullable=True, server_default="0"))
    op.add_column("financial_statements_normalized",
        sa.Column("free_cash_flow", sa.Numeric(18, 2), nullable=True, server_default="0"))

    # ═══════════════════════════════════════════════════════════
    # T12 — ExpertReview: Per-pillar comments + new fields
    # ═══════════════════════════════════════════════════════════
    op.add_column("expert_reviews",
        sa.Column("liquidity_comment", sa.Text, nullable=True))
    op.add_column("expert_reviews",
        sa.Column("solvability_comment", sa.Text, nullable=True))
    op.add_column("expert_reviews",
        sa.Column("profitability_comment", sa.Text, nullable=True))
    op.add_column("expert_reviews",
        sa.Column("capacity_comment", sa.Text, nullable=True))
    op.add_column("expert_reviews",
        sa.Column("quality_comment", sa.Text, nullable=True))
    op.add_column("expert_reviews",
        sa.Column("dynamic_analysis_comment", sa.Text, nullable=True))
    op.add_column("expert_reviews",
        sa.Column("mitigating_factors", sa.JSON, nullable=True, server_default="[]"))
    op.add_column("expert_reviews",
        sa.Column("risk_factors", sa.JSON, nullable=True, server_default="[]"))
    op.add_column("expert_reviews",
        sa.Column("override_recommendation", sa.String(50), nullable=True, server_default="'NONE'"))


def downgrade() -> None:
    # ExpertReview columns
    op.drop_column("expert_reviews", "override_recommendation")
    op.drop_column("expert_reviews", "risk_factors")
    op.drop_column("expert_reviews", "mitigating_factors")
    op.drop_column("expert_reviews", "dynamic_analysis_comment")
    op.drop_column("expert_reviews", "quality_comment")
    op.drop_column("expert_reviews", "capacity_comment")
    op.drop_column("expert_reviews", "profitability_comment")
    op.drop_column("expert_reviews", "solvability_comment")
    op.drop_column("expert_reviews", "liquidity_comment")

    # Normalized financial columns
    op.drop_column("financial_statements_normalized", "free_cash_flow")
    op.drop_column("financial_statements_normalized", "gross_profit")
    op.drop_column("financial_statements_normalized", "dividends")
    op.drop_column("financial_statements_normalized", "extraordinary_expenses")
    op.drop_column("financial_statements_normalized", "other_noncurrent_assets")

    # Raw financial columns (only the ones we added)
    op.drop_column("financial_statements_raw", "free_cash_flow")
    op.drop_column("financial_statements_raw", "gross_profit")
    op.drop_column("financial_statements_raw", "extraordinary_expenses")
    op.drop_column("financial_statements_raw", "other_noncurrent_assets")

    # Reverse RiskProfile
    risk_profile_reverse = {
        "BALANCED": "EQUILIBRE",
        "ASYMMETRICAL": "ASYMETRIQUE",
        "AGGRESSIVE": "AGRESSIF",
        "DEFENSIVE": "DEFENSIF",
        "CLASSIC": "CLASSIQUE",
    }
    for new_val, old_val in risk_profile_reverse.items():
        op.execute(
            f"UPDATE scorecards SET risk_profile = '{old_val}' WHERE risk_profile = '{new_val}'"
        )

    # Reverse RiskClass
    op.execute("UPDATE ia_predictions SET ia_risk_class = 'MEDIUM' WHERE ia_risk_class = 'MODERATE'")
    op.execute("UPDATE consortium_results SET final_risk_class = 'MEDIUM' WHERE final_risk_class = 'MODERATE'")
    op.execute("UPDATE consortium_results SET base_risk_class = 'MEDIUM' WHERE base_risk_class = 'MODERATE'")
    op.execute("UPDATE scorecards SET risk_class = 'MEDIUM' WHERE risk_class = 'MODERATE'")

    # Reverse CaseStatus
    op.execute("UPDATE evaluation_cases SET status = 'COMPLETED' WHERE status = 'CLOSED'")
    op.execute("UPDATE evaluation_cases SET status = 'SCORING' WHERE status = 'SCORING_DONE'")
    op.execute("UPDATE evaluation_cases SET status = 'IN_ANALYSIS' WHERE status = 'PENDING_GATE'")
