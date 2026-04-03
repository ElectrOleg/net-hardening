"""create all base tables

Revision ID: 20260208_init
Revises: None
Create Date: 2026-02-08 00:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '20260208_init'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ── hcs_vendors ──────────────────────────────────────────────
    op.create_table(
        'hcs_vendors',
        sa.Column('code', sa.String(50), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('parser_driver', sa.String(50)),
        sa.Column('description', sa.Text),
    )

    # ── hcs_data_sources ─────────────────────────────────────────
    op.create_table(
        'hcs_data_sources',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('credentials_ref', sa.String(200)),
        sa.Column('connection_params', JSONB),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── hcs_policies ─────────────────────────────────────────────
    op.create_table(
        'hcs_policies',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('description', sa.Text),
        sa.Column('severity', sa.String(20), server_default='medium'),
        sa.Column('scope_filter', JSONB),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── hcs_rules ────────────────────────────────────────────────
    op.create_table(
        'hcs_rules',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('policy_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_policies.id'), nullable=False),
        sa.Column('vendor_code', sa.String(50),
                  sa.ForeignKey('hcs_vendors.code'), nullable=False),
        sa.Column('data_source_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_data_sources.id'), nullable=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('remediation', sa.Text),
        sa.Column('logic_type', sa.String(30), nullable=False),
        sa.Column('logic_payload', JSONB, nullable=False),
        sa.Column('severity', sa.String(20), server_default='medium'),
        sa.Column('applicability', JSONB),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── hcs_scans ────────────────────────────────────────────────
    op.create_table(
        'hcs_scans',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('started_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime),
        sa.Column('started_by', sa.String(100)),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('devices_filter', JSONB),
        sa.Column('policies_filter', JSONB),
        sa.Column('total_devices', sa.Integer, server_default='0'),
        sa.Column('total_rules', sa.Integer, server_default='0'),
        sa.Column('passed_count', sa.Integer, server_default='0'),
        sa.Column('failed_count', sa.Integer, server_default='0'),
        sa.Column('error_count', sa.Integer, server_default='0'),
        sa.Column('error_message', sa.Text),
        sa.Column('celery_task_id', sa.String(200)),
    )

    # ── hcs_inventory_sources ────────────────────────────────────
    op.create_table(
        'hcs_inventory_sources',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('type', sa.String(30), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('connection_params', JSONB),
        sa.Column('credentials_ref', sa.String(200)),
        sa.Column('sync_enabled', sa.Boolean, server_default='true'),
        sa.Column('sync_interval_minutes', sa.Integer, server_default='60'),
        sa.Column('last_sync_at', sa.DateTime),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── hcs_device_groups ────────────────────────────────────────
    op.create_table(
        'hcs_device_groups',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('description', sa.Text),
        sa.Column('parent_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_device_groups.id'), nullable=True),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── hcs_devices ──────────────────────────────────────────────
    op.create_table(
        'hcs_devices',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('external_id', sa.String(200)),
        sa.Column('hostname', sa.String(200), nullable=False),
        sa.Column('ip_address', sa.String(50)),
        sa.Column('vendor_code', sa.String(50),
                  sa.ForeignKey('hcs_vendors.code'), nullable=True),
        sa.Column('group_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_device_groups.id'), nullable=True),
        sa.Column('location', sa.String(200)),
        sa.Column('os_version', sa.String(100)),
        sa.Column('hardware', sa.String(200)),
        sa.Column('extra_data', JSONB, server_default='{}'),
        sa.Column('source_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_inventory_sources.id'), nullable=True),
        sa.Column('last_sync_at', sa.DateTime),
        sa.Column('last_scan_at', sa.DateTime),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── hcs_results ──────────────────────────────────────────────
    op.create_table(
        'hcs_results',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('scan_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_scans.id'), nullable=False),
        sa.Column('device_id', sa.String(100), nullable=False),
        sa.Column('device_uuid', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_devices.id'), nullable=True),
        sa.Column('rule_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_rules.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('diff_data', sa.Text),
        sa.Column('raw_value', sa.Text),
        sa.Column('message', sa.Text),
        sa.Column('checked_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_hcs_results_scan_device', 'hcs_results', ['scan_id', 'device_id'])
    op.create_index('ix_hcs_results_scan_status', 'hcs_results', ['scan_id', 'status'])
    op.create_index('ix_hcs_results_device_uuid', 'hcs_results', ['device_uuid'])

    # ── hcs_exceptions ───────────────────────────────────────────
    op.create_table(
        'hcs_exceptions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('device_id', sa.String(100)),
        sa.Column('rule_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_rules.id'), nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('approved_by', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('expiry_date', sa.Date),
        sa.Column('is_active', sa.Boolean, server_default='true'),
    )
    op.create_index('ix_hcs_exceptions_device_rule', 'hcs_exceptions', ['device_id', 'rule_id'])
    op.create_index('ix_hcs_exceptions_active', 'hcs_exceptions', ['is_active', 'expiry_date'])

    # ── hcs_users ────────────────────────────────────────────────
    op.create_table(
        'hcs_users',
        sa.Column('id', UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('username', sa.String(100), nullable=False, unique=True),
        sa.Column('display_name', sa.String(200), server_default=''),
        sa.Column('email', sa.String(200), server_default=''),
        sa.Column('password_hash', sa.String(256)),
        sa.Column('auth_source', sa.String(20), nullable=False, server_default='local'),
        sa.Column('role', sa.String(20), nullable=False, server_default='viewer'),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('last_login_at', sa.DateTime),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('ix_hcs_users_username', 'hcs_users', ['username'])

    # ── M2M: hcs_device_policies ─────────────────────────────────
    op.create_table(
        'hcs_device_policies',
        sa.Column('device_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_devices.id'), primary_key=True),
        sa.Column('policy_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_policies.id'), primary_key=True),
        sa.Column('assigned_at', sa.DateTime, server_default=sa.func.now()),
    )

    # ── M2M: hcs_group_policies ──────────────────────────────────
    op.create_table(
        'hcs_group_policies',
        sa.Column('group_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_device_groups.id'), primary_key=True),
        sa.Column('policy_id', UUID(as_uuid=True),
                  sa.ForeignKey('hcs_policies.id'), primary_key=True),
        sa.Column('assigned_at', sa.DateTime, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('hcs_group_policies')
    op.drop_table('hcs_device_policies')
    op.drop_table('hcs_users')
    op.drop_table('hcs_exceptions')
    op.drop_table('hcs_results')
    op.drop_table('hcs_devices')
    op.drop_table('hcs_device_groups')
    op.drop_table('hcs_inventory_sources')
    op.drop_table('hcs_scans')
    op.drop_table('hcs_rules')
    op.drop_table('hcs_policies')
    op.drop_table('hcs_data_sources')
    op.drop_table('hcs_vendors')
