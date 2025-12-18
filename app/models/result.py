"""Result model - результаты проверок."""
import uuid
from sqlalchemy.dialects.postgresql import UUID
from app.extensions import db


class Result(db.Model):
    """Результаты проверок."""
    
    __tablename__ = "hcs_results"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id = db.Column(UUID(as_uuid=True), db.ForeignKey("hcs_scans.id"), nullable=False)
    device_id = db.Column(db.String(100), nullable=False)  # Hostname or IP
    rule_id = db.Column(UUID(as_uuid=True), db.ForeignKey("hcs_rules.id"), nullable=False)
    
    # PASS, FAIL, ERROR, SKIPPED (если есть exception)
    status = db.Column(db.String(20), nullable=False)
    
    # Детали результата
    diff_data = db.Column(db.Text)  # Почему упало / что нашли
    raw_value = db.Column(db.Text)  # Фактическое значение из конфига
    message = db.Column(db.Text)  # Human-readable message
    
    checked_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Relationships
    scan = db.relationship("Scan", back_populates="results")
    rule = db.relationship("Rule", back_populates="results")
    
    # Indexes for fast queries
    __table_args__ = (
        db.Index("ix_hcs_results_scan_device", "scan_id", "device_id"),
        db.Index("ix_hcs_results_scan_status", "scan_id", "status"),
    )
    
    def __repr__(self):
        return f"<Result {self.device_id}:{self.rule_id} = {self.status}>"
    
    def to_dict(self, include_rule=False):
        data = {
            "id": str(self.id),
            "scan_id": str(self.scan_id),
            "device_id": self.device_id,
            "rule_id": str(self.rule_id),
            "status": self.status,
            "diff_data": self.diff_data,
            "raw_value": self.raw_value,
            "message": self.message,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }
        if include_rule and self.rule:
            data["rule"] = self.rule.to_dict(include_payload=False)
        return data
