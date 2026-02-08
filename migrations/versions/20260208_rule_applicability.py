"""add applicability column to hcs_rules

Revision ID: 20260208_appl
Revises: 20260208_vmap
Create Date: 2026-02-08 17:32:00
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
    op.add_column('hcs_rules', sa.Column(
        'applicability',
        JSONB,
        nullable=True,
    ))


def downgrade():
    op.drop_column('hcs_rules', 'applicability')
