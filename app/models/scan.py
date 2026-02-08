"""Scan model - журнал запусков сканирования."""
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.extensions import db


class Scan(db.Model):
    """Журнал запусков сканирования."""
    
    __tablename__ = "hcs_scans"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at = db.Column(db.DateTime, server_default=db.func.now())
    finished_at = db.Column(db.DateTime)
    started_by = db.Column(db.String(100))  # Username
    status = db.Column(db.String(20), default="pending")  # pending, running, completed, failed
    
    # Filter options
    devices_filter = db.Column(JSONB)  # Какие устройства сканировались
    policies_filter = db.Column(JSONB)  # Какие политики применялись
    
    # Stats
    total_devices = db.Column(db.Integer, default=0)
    total_rules = db.Column(db.Integer, default=0)
    passed_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    error_count = db.Column(db.Integer, default=0)
    
    # Error info if failed
    error_message = db.Column(db.Text)
    
    # Celery task tracking
    celery_task_id = db.Column(db.String(200))
    
    # Relationships
    results = db.relationship("Result", back_populates="scan", lazy="dynamic")
    
    def __repr__(self):
        return f"<Scan {self.id} ({self.status})>"
    
    @property
    def score(self):
        """Calculate security score as percentage.
        
        Errors count against the score (treated as non-passing results).
        """
        total = self.passed_count + self.failed_count + self.error_count
        if total == 0:
            return 100.0
        return round((self.passed_count / total) * 100, 1)
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "started_by": self.started_by,
            "status": self.status,
            "devices_filter": self.devices_filter,
            "policies_filter": self.policies_filter,
            "total_devices": self.total_devices,
            "total_rules": self.total_rules,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "error_count": self.error_count,
            "score": self.score,
            "error_message": self.error_message,
        }
