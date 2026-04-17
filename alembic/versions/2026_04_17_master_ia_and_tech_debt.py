"""master_ia_and_tech_debt

Revision ID: 2026_04_17_master_ia
Revises: f1a2b3c4d5e6
Create Date: 2026-04-17 18:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2026_04_17_master_ia'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Create IA Admin Tables ─────────────────────────────────────────────
    
    # ia_training_datasets
    op.execute("""
        CREATE TABLE IF NOT EXISTS ia_training_datasets (
            id UUID PRIMARY KEY,
            dataset_name VARCHAR(100) NOT NULL,
            sample_size INTEGER NOT NULL,
            features_list JSONB NOT NULL,
            target_column VARCHAR(50) NOT NULL,
            query_filter JSONB,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL
        )
    """)

    # ia_training_runs
    op.execute("""
        CREATE TABLE IF NOT EXISTS ia_training_runs (
            id UUID PRIMARY KEY,
            dataset_id UUID NOT NULL REFERENCES ia_training_datasets(id),
            model_type VARCHAR(50) NOT NULL,
            hyperparameters JSONB,
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            metrics JSONB,
            model_artifact_path VARCHAR(255),
            error_log TEXT,
            started_at TIMESTAMP WITHOUT TIME ZONE,
            completed_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL
        )
    """)

    # ia_deployed_models
    op.execute("""
        CREATE TABLE IF NOT EXISTS ia_deployed_models (
            id UUID PRIMARY KEY,
            training_run_id UUID NOT NULL REFERENCES ia_training_runs(id),
            version VARCHAR(50) NOT NULL UNIQUE,
            is_active BOOLEAN DEFAULT FALSE,
            deployment_notes TEXT,
            deployed_by VARCHAR(100),
            deployed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL
        )
    """)

    # ia_admin_events
    op.execute("""
        CREATE TABLE IF NOT EXISTS ia_admin_events (
            id UUID PRIMARY KEY,
            event_type VARCHAR(50) NOT NULL,
            severity VARCHAR(20) NOT NULL,
            message TEXT NOT NULL,
            metadata_json JSONB,
            is_resolved BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL
        )
    """)

    # ── 2. Enrich Existing IA Tables ──────────────────────────────────────────

    # ia_predictions
    op.execute("ALTER TABLE ia_predictions ADD COLUMN IF NOT EXISTS deployed_model_id UUID REFERENCES ia_deployed_models(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE ia_predictions ADD COLUMN IF NOT EXISTS prediction_source VARCHAR(50) DEFAULT 'ML_ENGINE'")
    op.execute("ALTER TABLE ia_predictions ADD COLUMN IF NOT EXISTS input_features JSONB")
    op.execute("ALTER TABLE ia_predictions ADD COLUMN IF NOT EXISTS actual_outcome VARCHAR(50)")

    # ── 3. Technical Debt: Normalization (Local values) ───────────────────────
    
    op.execute("ALTER TABLE financial_statements_normalized ADD COLUMN IF NOT EXISTS currency_original VARCHAR")
    op.execute("ALTER TABLE financial_statements_normalized ADD COLUMN IF NOT EXISTS exchange_rate_used NUMERIC(18, 6)")
    op.execute("ALTER TABLE financial_statements_normalized ADD COLUMN IF NOT EXISTS total_assets_original NUMERIC(18, 2)")
    op.execute("ALTER TABLE financial_statements_normalized ADD COLUMN IF NOT EXISTS current_assets_original NUMERIC(18, 2)")
    op.execute("ALTER TABLE financial_statements_normalized ADD COLUMN IF NOT EXISTS inventory_original NUMERIC(18, 2)")
    op.execute("ALTER TABLE financial_statements_normalized ADD COLUMN IF NOT EXISTS accounts_receivable_original NUMERIC(18, 2)")
    op.execute("ALTER TABLE financial_statements_normalized ADD COLUMN IF NOT EXISTS revenue_original NUMERIC(18, 2)")
    op.execute("ALTER TABLE financial_statements_normalized ADD COLUMN IF NOT EXISTS operating_income_original NUMERIC(18, 2)")
    op.execute("ALTER TABLE financial_statements_normalized ADD COLUMN IF NOT EXISTS net_income_original NUMERIC(18, 2)")
    op.execute("ALTER TABLE financial_statements_normalized ADD COLUMN IF NOT EXISTS ebitda_original NUMERIC(18, 2)")

    # ── 4. Technical Debt: Ratios (Z-Score & YoY) ─────────────────────────────

    op.execute("ALTER TABLE ratio_sets ADD COLUMN IF NOT EXISTS z_score_x1 NUMERIC(18, 4)")
    op.execute("ALTER TABLE ratio_sets ADD COLUMN IF NOT EXISTS z_score_x2 NUMERIC(18, 4)")
    op.execute("ALTER TABLE ratio_sets ADD COLUMN IF NOT EXISTS z_score_x3 NUMERIC(18, 4)")
    op.execute("ALTER TABLE ratio_sets ADD COLUMN IF NOT EXISTS z_score_x4 NUMERIC(18, 4)")
    
    op.execute("ALTER TABLE ratio_sets ADD COLUMN IF NOT EXISTS revenue_growth_yoy NUMERIC(18, 4)")
    op.execute("ALTER TABLE ratio_sets ADD COLUMN IF NOT EXISTS ebitda_growth_yoy NUMERIC(18, 4)")
    op.execute("ALTER TABLE ratio_sets ADD COLUMN IF NOT EXISTS net_income_growth_yoy NUMERIC(18, 4)")
    op.execute("ALTER TABLE ratio_sets ADD COLUMN IF NOT EXISTS margin_variation_yoy NUMERIC(18, 4)")

    # ── 5. Technical Debt: Scorecard ──────────────────────────────────────────

    op.execute("ALTER TABLE scorecards ADD COLUMN IF NOT EXISTS pillars_json JSONB")


def downgrade() -> None:
    # Downgrade logic is optional but for safety let's just drop in reverse order 
    # (Note: IF EXISTS is used to avoid errors if partially applied)
    
    op.execute("ALTER TABLE scorecards DROP COLUMN IF EXISTS pillars_json")
    
    op.execute("ALTER TABLE ratio_sets DROP COLUMN IF EXISTS margin_variation_yoy")
    op.execute("ALTER TABLE ratio_sets DROP COLUMN IF EXISTS net_income_growth_yoy")
    op.execute("ALTER TABLE ratio_sets DROP COLUMN IF EXISTS ebitda_growth_yoy")
    op.execute("ALTER TABLE ratio_sets DROP COLUMN IF EXISTS revenue_growth_yoy")
    op.execute("ALTER TABLE ratio_sets DROP COLUMN IF EXISTS z_score_x4")
    op.execute("ALTER TABLE ratio_sets DROP COLUMN IF EXISTS z_score_x3")
    op.execute("ALTER TABLE ratio_sets DROP COLUMN IF EXISTS z_score_x2")
    op.execute("ALTER TABLE ratio_sets DROP COLUMN IF EXISTS z_score_x1")

    op.execute("ALTER TABLE financial_statements_normalized DROP COLUMN IF EXISTS ebitda_original")
    op.execute("ALTER TABLE financial_statements_normalized DROP COLUMN IF EXISTS net_income_original")
    op.execute("ALTER TABLE financial_statements_normalized DROP COLUMN IF EXISTS operating_income_original")
    op.execute("ALTER TABLE financial_statements_normalized DROP COLUMN IF EXISTS revenue_original")
    op.execute("ALTER TABLE financial_statements_normalized DROP COLUMN IF EXISTS accounts_receivable_original")
    op.execute("ALTER TABLE financial_statements_normalized DROP COLUMN IF EXISTS inventory_original")
    op.execute("ALTER TABLE financial_statements_normalized DROP COLUMN IF EXISTS current_assets_original")
    op.execute("ALTER TABLE financial_statements_normalized DROP COLUMN IF EXISTS total_assets_original")
    op.execute("ALTER TABLE financial_statements_normalized DROP COLUMN IF EXISTS exchange_rate_used")
    op.execute("ALTER TABLE financial_statements_normalized DROP COLUMN IF EXISTS currency_original")

    op.execute("ALTER TABLE ia_predictions DROP COLUMN IF EXISTS actual_outcome")
    op.execute("ALTER TABLE ia_predictions DROP COLUMN IF EXISTS input_features")
    op.execute("ALTER TABLE ia_predictions DROP COLUMN IF EXISTS prediction_source")
    op.execute("ALTER TABLE ia_predictions DROP COLUMN IF EXISTS deployed_model_id")

    op.execute("DROP TABLE IF EXISTS ia_admin_events")
    op.execute("DROP TABLE IF EXISTS ia_deployed_models")
    op.execute("DROP TABLE IF EXISTS ia_training_runs")
    op.execute("DROP TABLE IF EXISTS ia_training_datasets")
