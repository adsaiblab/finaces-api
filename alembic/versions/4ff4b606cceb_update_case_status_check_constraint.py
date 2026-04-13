"""update_case_status_check_constraint

Revision ID: 4ff4b606cceb
Revises: f1a2b3c4d5e6
Create Date: 2026-04-13 12:53:28.573828

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ff4b606cceb'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE evaluation_cases DROP CONSTRAINT IF EXISTS ck_evaluation_case_status")
    op.execute("""
        ALTER TABLE evaluation_cases ADD CONSTRAINT ck_evaluation_case_status
        CHECK (status::text = ANY (ARRAY[
            'DRAFT', 'PENDING_GATE', 'FINANCIAL_INPUT',
            'NORMALIZATION_DONE', 'RATIOS_COMPUTED', 'SCORING_DONE',
            'STRESS_DONE', 'EXPERT_REVIEWED', 'CLOSED', 'ARCHIVED'
        ]))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE evaluation_cases DROP CONSTRAINT IF EXISTS ck_evaluation_case_status")
    op.execute("""
        ALTER TABLE evaluation_cases ADD CONSTRAINT ck_evaluation_case_status
        CHECK (status::text = ANY (ARRAY[
            'DRAFT', 'IN_ANALYSIS', 'SCORING', 'COMPLETED', 'ARCHIVED'
        ]))
    """)
