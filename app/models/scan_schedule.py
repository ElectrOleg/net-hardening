"""ScanSchedule model — scheduled scan configurations."""
import uuid
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.extensions import db


class ScanSchedule(db.Model):
    """Scheduled scan configuration with cron expression."""
    
    __tablename__ = "hcs_scan_schedules"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    
    # Cron expression (minute hour day_of_month month day_of_week)
    cron_expression = db.Column(db.String(100), nullable=False, default="0 2 * * *")
    
    # What to scan
    policies_filter = db.Column(JSONB)   # list of policy IDs, or null = all
    devices_filter = db.Column(JSONB)    # {"vendor": "...", "group_id": "..."} or null = all
    
    # State
    is_enabled = db.Column(db.Boolean, default=True)
    last_run_at = db.Column(db.DateTime)
    next_run_at = db.Column(db.DateTime)
    last_scan_id = db.Column(UUID(as_uuid=True))  # reference to last created Scan
    
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    def __repr__(self):
        return f"<ScanSchedule {self.name} ({self.cron_expression})>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "cron_expression": self.cron_expression,
            "policies_filter": self.policies_filter,
            "devices_filter": self.devices_filter,
            "is_enabled": self.is_enabled,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_scan_id": str(self.last_scan_id) if self.last_scan_id else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    
    def calculate_next_run(self) -> datetime:
        """Calculate the next run time based on cron expression."""
        try:
            from croniter import croniter
            base = self.last_run_at or datetime.utcnow()
            cron = croniter(self.cron_expression, base)
            return cron.get_next(datetime)
        except ImportError:
            # Fallback: if croniter not installed, run daily at same time
            from datetime import timedelta
            base = self.last_run_at or datetime.utcnow()
            return base + timedelta(days=1)
        except Exception:
            from datetime import timedelta
            return datetime.utcnow() + timedelta(hours=1)
