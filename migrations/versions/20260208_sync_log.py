"""add sync_logs table

Revision ID: 20260208_slog
Revises: 20260208_appl
Create Date: 2026-02-08 18:05:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '20260208_slog'
down_revision = '20260208_appl'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hcs_sync_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('source_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_inventory_sources.id'), nullable=False),
        sa.Column('started_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime),
        sa.Column('trigger', sa.String(30), default='manual'),
        sa.Column('created', sa.Integer, default=0),
        sa.Column('updated', sa.Integer, default=0),
        sa.Column('deactivated', sa.Integer, default=0),
        sa.Column('status', sa.String(20), default='success'),
        sa.Column('errors', JSONB, default=list),
        sa.Column('duration_seconds', sa.Float),
    )
    
    # Index for querying logs by source
    op.create_index('ix_hcs_sync_logs_source', 'hcs_sync_logs', ['source_id'])


def downgrade():
    op.drop_index('ix_hcs_sync_logs_source')
    op.drop_table('hcs_sync_logs')
