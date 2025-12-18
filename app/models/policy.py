"""Policy model - группы проверок."""
import uuid
from sqlalchemy.dialects.postgresql import UUID
from app.extensions import db


class Policy(db.Model):
    """Группы проверок (политики)."""
    
    __tablename__ = "hcs_policies"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    severity = db.Column(db.String(20), default="medium")  # critical, high, medium, low
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    # Relationships
    rules = db.relationship("Rule", back_populates="policy", lazy="dynamic")
    
    def __repr__(self):
        return f"<Policy {self.name}>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "is_active": self.is_active,
            "rules_count": self.rules.count(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
