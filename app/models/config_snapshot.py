"""ConfigSnapshot model — persistent storage of device configurations.

Stores config snapshots with SHA-256 deduplication:
- If config hasn't changed since last snapshot, only hash is stored (no text)
- Diff summary is computed for changed snapshots
- Retention is managed by cleanup_old_data() task
"""
import uuid
import hashlib
from datetime import datetime

from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.extensions import db


class ConfigSnapshot(db.Model):
    """Snapshot of a device's configuration at a point in time."""
    
    __tablename__ = "hcs_config_snapshots"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("hcs_devices.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    source_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("hcs_data_sources.id", ondelete="SET NULL"),
        nullable=True
    )
    scan_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("hcs_scans.id", ondelete="SET NULL"),
        nullable=True
    )
    
    # Config content
    config_text = db.Column(db.Text, nullable=True)  # NULL when is_changed=False (dedup)
    config_hash = db.Column(db.String(64), nullable=False)  # SHA-256
    config_size = db.Column(db.Integer, default=0)  # original size in bytes
    
    # Metadata
    vendor_code = db.Column(db.String(50))
    collected_at = db.Column(db.DateTime, server_default=db.func.now(), index=True)
    
    # Diff tracking
    is_changed = db.Column(db.Boolean, default=True)
    prev_snapshot_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("hcs_config_snapshots.id", ondelete="SET NULL"),
        nullable=True
    )
    diff_summary = db.Column(db.Text)  # human-readable diff summary (lines added/removed)
    
    # Relationships
    device = db.relationship("Device", backref=db.backref("config_snapshots", lazy="dynamic"))
    source = db.relationship("DataSource", backref="config_snapshots")
    scan = db.relationship("Scan", backref="config_snapshots")
    
    __table_args__ = (
        db.Index("ix_config_snap_device_time", "device_id", "collected_at"),
        db.Index("ix_config_snap_hash", "config_hash"),
        db.Index("ix_config_snap_scan", "scan_id"),
    )
    
    def __repr__(self):
        status = "changed" if self.is_changed else "unchanged"
        return f"<ConfigSnapshot {self.device_id} [{status}] {self.collected_at}>"
    
    @staticmethod
    def compute_hash(config_text: str) -> str:
        """Compute SHA-256 hash of config text."""
        return hashlib.sha256(config_text.encode("utf-8")).hexdigest()
    
    def get_config_text(self) -> str | None:
        """Get config text, resolving from previous snapshot if deduped.
        
        When is_changed=False, config_text is NULL. Walk the chain back 
        to find the last snapshot that actually stored the text.
        """
        if self.config_text is not None:
            return self.config_text
        
        # Walk back through chain to find stored text
        snap = self
        visited = set()
        while snap and snap.prev_snapshot_id and snap.prev_snapshot_id not in visited:
            visited.add(snap.prev_snapshot_id)
            snap = ConfigSnapshot.query.get(snap.prev_snapshot_id)
            if snap and snap.config_text is not None:
                return snap.config_text
        
        return None
    
    def to_dict(self, include_config=False):
        data = {
            "id": str(self.id),
            "device_id": str(self.device_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "scan_id": str(self.scan_id) if self.scan_id else None,
            "config_hash": self.config_hash,
            "config_size": self.config_size,
            "vendor_code": self.vendor_code,
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
            "is_changed": self.is_changed,
            "diff_summary": self.diff_summary,
        }
        if include_config:
            data["config_text"] = self.get_config_text()
        return data
    
    def to_dict_safe(self, sanitizer=None):
        """Serialize with sensitive data masked."""
        data = self.to_dict(include_config=True)
        if data.get("config_text") and sanitizer:
            data["config_text"] = sanitizer(data["config_text"])
        return data
