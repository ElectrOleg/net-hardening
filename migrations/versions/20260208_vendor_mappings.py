"""add vendor_mapping table

Revision ID: 20260208_vmap
Revises: 20260208_sev
Create Date: 2026-02-08 17:15:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = '20260208_vmap'
down_revision = '20260208_sev'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hcs_vendor_mappings',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('vendor_code', sa.String(50),
                  sa.ForeignKey('hcs_vendors.code'), nullable=False),
        sa.Column('pattern', sa.String(500), nullable=False),
        sa.Column('match_field', sa.String(50), nullable=False,
                  server_default='config_content'),
        sa.Column('priority', sa.Integer, nullable=False,
                  server_default='100'),
        sa.Column('description', sa.String(200)),
        sa.Column('is_active', sa.Boolean, server_default='true'),
    )

    # Seed default vendor mappings
    from app.models.vendor_mapping import DEFAULT_VENDOR_MAPPINGS
    
    mappings_table = sa.table(
        'hcs_vendor_mappings',
        sa.column('vendor_code', sa.String),
        sa.column('pattern', sa.String),
        sa.column('match_field', sa.String),
        sa.column('priority', sa.Integer),
        sa.column('description', sa.String),
    )
    
    op.bulk_insert(mappings_table, DEFAULT_VENDOR_MAPPINGS)


def downgrade():
    op.drop_table('hcs_vendor_mappings')
