"""Exception model - исключения (принятые риски)."""
import uuid
from datetime import date
from sqlalchemy.dialects.postgresql import UUID
from app.extensions import db


class RuleException(db.Model):
    """Исключения (waivers) — принятые риски."""
    
    __tablename__ = "hcs_exceptions"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = db.Column(db.String(100))  # None = applies to all devices
    rule_id = db.Column(UUID(as_uuid=True), db.ForeignKey("hcs_rules.id"), nullable=False)
    
    reason = db.Column(db.Text, nullable=False)  # Причина исключения
    approved_by = db.Column(db.String(100), nullable=False)  # Кто одобрил
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    expiry_date = db.Column(db.Date)  # До какой даты действует (None = бессрочно)
    
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    rule = db.relationship("Rule", back_populates="exceptions")
    
    # Indexes
    __table_args__ = (
        db.Index("ix_hcs_exceptions_device_rule", "device_id", "rule_id"),
        db.Index("ix_hcs_exceptions_active", "is_active", "expiry_date"),
    )
    
    def __repr__(self):
        return f"<RuleException {self.device_id}:{self.rule_id}>"
    
    @property
    def is_expired(self):
        """Check if exception has expired."""
        if self.expiry_date is None:
            return False
        return date.today() > self.expiry_date
    
    @property
    def is_valid(self):
        """Check if exception is currently valid."""
        return self.is_active and not self.is_expired
    
    def to_dict(self, include_rule=False):
        data = {
            "id": str(self.id),
            "device_id": self.device_id,
            "rule_id": str(self.rule_id),
            "reason": self.reason,
            "approved_by": self.approved_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "is_active": self.is_active,
            "is_expired": self.is_expired,
            "is_valid": self.is_valid,
        }
        if include_rule and self.rule:
            data["rule"] = self.rule.to_dict(include_payload=False)
        return data
