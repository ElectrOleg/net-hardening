"""add device_uuid to result and celery_task_id to scan

Revision ID: 20260208_todo
Revises: None
Create Date: 2026-02-08 16:40:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260208_todo'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add device_uuid FK to hcs_results
    op.add_column('hcs_results', sa.Column(
        'device_uuid',
        UUID(as_uuid=True),
        sa.ForeignKey('hcs_devices.id'),
        nullable=True,
    ))
    op.create_index('ix_hcs_results_device_uuid', 'hcs_results', ['device_uuid'])

    # Add celery_task_id to hcs_scans
    op.add_column('hcs_scans', sa.Column(
        'celery_task_id',
        sa.String(200),
        nullable=True,
    ))


def downgrade():
    op.drop_index('ix_hcs_results_device_uuid', table_name='hcs_results')
    op.drop_column('hcs_results', 'device_uuid')
    op.drop_column('hcs_scans', 'celery_task_id')
