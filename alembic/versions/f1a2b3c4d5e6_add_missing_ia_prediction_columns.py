"""add missing ia prediction columns

Revision ID: f1a2b3c4d5e6
Revises: c3a1f9d82e01
Create Date: 2026-04-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'c3a1f9d82e01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ia_predictions
    op.add_column('ia_predictions',
        sa.Column('input_features', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True)
    )
    op.add_column('ia_predictions',
        sa.Column('actual_outcome', sa.String(), nullable=True)
    )
    # ia_models
    op.add_column('ia_models',
        sa.Column('hyperparameters', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True)
    )
    op.add_column('ia_models',
        sa.Column('feature_names', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True)
    )
    op.add_column('ia_models',
        sa.Column('trained_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('ia_models', 'trained_at')
    op.drop_column('ia_models', 'feature_names')
    op.drop_column('ia_models', 'hyperparameters')
    op.drop_column('ia_predictions', 'actual_outcome')
    op.drop_column('ia_predictions', 'input_features')
