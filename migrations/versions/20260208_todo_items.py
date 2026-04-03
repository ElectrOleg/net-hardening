"""add device_uuid to result and celery_task_id to scan

Revision ID: 20260208_todo
Revises: 20260208_init
Create Date: 2026-02-08 16:40:00

NOTE: These columns are now created in the initial migration (20260208_init).
      This migration is kept for chain integrity but is a no-op.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '20260208_todo'
down_revision = '20260208_init'
branch_labels = None
depends_on = None


def upgrade():
    # Columns device_uuid and celery_task_id are now created in 20260208_init.
    # This migration is a no-op but kept for chain integrity.
    pass


def downgrade():
    # No-op: columns are managed by 20260208_init
    pass

