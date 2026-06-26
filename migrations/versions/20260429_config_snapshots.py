"""add config_snapshots table

Revision ID: 20260429_config_snapshots
Revises: 20260208_admin
Create Date: 2026-04-29 00:00:00

Adds the hcs_config_snapshots table for persistent device configuration
storage with SHA-256 deduplication and diff tracking.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "20260429_config_snapshots"
down_revision = "20260208_admin"
branch_labels = None
depends_on = None


def _table_exists(conn, table_name: str) -> bool:
    """Check if a table already exists in the database."""
    if conn.dialect.name == "sqlite":
        result = conn.execute(
            sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:tbl"),
            {"tbl": table_name},
        )
        return result.first() is not None
    result = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :tbl)"),
        {"tbl": table_name},
    )
    return result.scalar()


def _index_exists(conn, index_name: str) -> bool:
    """Check if an index already exists."""
    if conn.dialect.name == "sqlite":
        result = conn.execute(
            sa.text("SELECT 1 FROM sqlite_master WHERE type='index' AND name=:idx"),
            {"idx": index_name},
        )
        return result.first() is not None
    result = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :idx)"),
        {"idx": index_name},
    )
    return result.scalar()


def upgrade():
    conn = op.get_bind()

    if not _table_exists(conn, "hcs_config_snapshots"):
        op.create_table(
            "hcs_config_snapshots",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "device_id",
                UUID(as_uuid=True),
                sa.ForeignKey("hcs_devices.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "source_id",
                UUID(as_uuid=True),
                sa.ForeignKey("hcs_data_sources.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "scan_id",
                UUID(as_uuid=True),
                sa.ForeignKey("hcs_scans.id", ondelete="SET NULL"),
                nullable=True,
            ),
            # Config content
            sa.Column("config_text", sa.Text, nullable=True),
            sa.Column("config_hash", sa.String(64), nullable=False),
            sa.Column("config_size", sa.Integer, server_default="0"),
            # Metadata
            sa.Column("vendor_code", sa.String(50), nullable=True),
            sa.Column("collected_at", sa.DateTime, server_default=sa.func.now()),
            # Diff tracking
            sa.Column("is_changed", sa.Boolean, server_default="true"),
            sa.Column(
                "prev_snapshot_id",
                UUID(as_uuid=True),
                sa.ForeignKey("hcs_config_snapshots.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("diff_summary", sa.Text, nullable=True),
        )

    # Indexes
    if not _index_exists(conn, "ix_config_snap_device_time"):
        op.create_index(
            "ix_config_snap_device_time", "hcs_config_snapshots", ["device_id", "collected_at"]
        )
    if not _index_exists(conn, "ix_config_snap_hash"):
        op.create_index("ix_config_snap_hash", "hcs_config_snapshots", ["config_hash"])
    if not _index_exists(conn, "ix_config_snap_scan"):
        op.create_index("ix_config_snap_scan", "hcs_config_snapshots", ["scan_id"])


def downgrade():
    op.drop_index("ix_config_snap_scan", table_name="hcs_config_snapshots")
    op.drop_index("ix_config_snap_hash", table_name="hcs_config_snapshots")
    op.drop_index("ix_config_snap_device_time", table_name="hcs_config_snapshots")
    op.drop_table("hcs_config_snapshots")
