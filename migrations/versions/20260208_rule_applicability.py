"""add applicability column to hcs_rules

Revision ID: 20260208_appl
Revises: 20260208_vmap
Create Date: 2026-02-08 17:32:00

NOTE: applicability column is now created in the initial migration (20260208_init).
      This migration is kept for chain integrity but is a no-op.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '20260208_appl'
down_revision = '20260208_vmap'
branch_labels = None
depends_on = None


def upgrade():
    # applicability is now created in 20260208_init — no-op
    pass


def downgrade():
    pass

