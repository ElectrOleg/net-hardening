"""add severity column to hcs_rules

Revision ID: 20260208_sev
Revises: 20260208_todo
Create Date: 2026-02-08 16:50:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260208_sev'
down_revision = '20260208_todo'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('hcs_rules', sa.Column(
        'severity',
        sa.String(20),
        server_default='medium',
        nullable=True,
    ))


def downgrade():
    op.drop_column('hcs_rules', 'severity')
