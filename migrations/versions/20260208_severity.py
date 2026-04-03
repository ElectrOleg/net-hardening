"""add severity column to hcs_rules

Revision ID: 20260208_sev
Revises: 20260208_todo
Create Date: 2026-02-08 16:50:00

NOTE: severity column is now created in the initial migration (20260208_init).
      This migration is kept for chain integrity but is a no-op.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260208_sev'
down_revision = '20260208_todo'
branch_labels = None
depends_on = None


def upgrade():
    # severity is now created in 20260208_init — no-op
    pass


def downgrade():
    pass

