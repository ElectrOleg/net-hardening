"""Sync audit log model — tracks inventory sync operations."""
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.extensions import db


class SyncLog(db.Model):
    """Log of inventory sync operations for auditing and troubleshooting."""
    
    __tablename__ = "hcs_sync_logs"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = db.Column(UUID(as_uuid=True), db.ForeignKey("hcs_inventory_sources.id"), nullable=False)
    source = db.relationship("InventorySource", backref="sync_logs")
    
    started_at = db.Column(db.DateTime, server_default=db.func.now())
    finished_at = db.Column(db.DateTime)
    
    # Trigger: manual, scheduled, api
    trigger = db.Column(db.String(30), default="manual")
    
    # Counts
    created = db.Column(db.Integer, default=0)
    updated = db.Column(db.Integer, default=0)
    deactivated = db.Column(db.Integer, default=0)
    
    # Status: success, partial, failed
    status = db.Column(db.String(20), default="success")
    errors = db.Column(JSONB, default=list)  # List of error strings
    
    # Duration in seconds
    duration_seconds = db.Column(db.Float)
    
    def __repr__(self):
        return f"<SyncLog {self.source_id} at {self.started_at} ({self.status})>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "source_id": str(self.source_id),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "trigger": self.trigger,
            "created": self.created,
            "updated": self.updated,
            "deactivated": self.deactivated,
            "status": self.status,
            "errors": self.errors,
            "duration_seconds": self.duration_seconds,
        }
