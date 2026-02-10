"""Policy model - группы проверок."""
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.extensions import db


class Policy(db.Model):
    """Группы проверок (политики)."""
    
    __tablename__ = "hcs_policies"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    severity = db.Column(db.String(20), default="medium")  # critical, high, medium, low
    # Scope filter — JSONB conditions for device field matching.
    # Same format as Rule.applicability: {"location": "DC1", "extra_data.env": "prod"}
    # When set, the policy only applies to devices matching ALL conditions.
    scope_filter = db.Column(JSONB, nullable=True)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    # Relationships
    rules = db.relationship("Rule", back_populates="policy", lazy="dynamic")
    
    def __repr__(self):
        return f"<Policy {self.name}>"
    
    def to_dict(self, include_rules_count=True):
        data = {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "scope_filter": self.scope_filter,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_rules_count:
            data["rules_count"] = self.rules.count()
        return data
