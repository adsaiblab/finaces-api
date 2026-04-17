"""merge_ia_heads

Revision ID: 6a79e08be19b
Revises: 2026_04_17_master_ia, 4ff4b606cceb
Create Date: 2026-04-17 18:50:43.830317

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a79e08be19b'
down_revision: Union[str, Sequence[str], None] = ('2026_04_17_master_ia', '4ff4b606cceb')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
