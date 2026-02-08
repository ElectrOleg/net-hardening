"""add system_settings and scan_schedules tables

Revision ID: 20260208_admin
Revises: 20260208_slog
Create Date: 2026-02-08 18:25:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '20260208_admin'
down_revision = '20260208_slog'
branch_labels = None
depends_on = None


def upgrade():
    # System settings (key-value)
    op.create_table(
        'hcs_system_settings',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('value', sa.Text, nullable=False, server_default=''),
        sa.Column('description', sa.Text),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )
    
    # Scan schedules
    op.create_table(
        'hcs_scan_schedules',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('cron_expression', sa.String(100), nullable=False,
                  server_default='0 2 * * *'),
        sa.Column('policies_filter', JSONB),
        sa.Column('devices_filter', JSONB),
        sa.Column('is_enabled', sa.Boolean, server_default='true'),
        sa.Column('last_run_at', sa.DateTime),
        sa.Column('next_run_at', sa.DateTime),
        sa.Column('last_scan_id', UUID(as_uuid=True)),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('hcs_scan_schedules')
    op.drop_table('hcs_system_settings')
