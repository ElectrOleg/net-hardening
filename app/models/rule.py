"""Rule model - ядро системы проверок."""
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.extensions import db


class Rule(db.Model):
    """Правила проверок — ядро системы."""
    
    __tablename__ = "hcs_rules"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id = db.Column(UUID(as_uuid=True), db.ForeignKey("hcs_policies.id"), nullable=False)
    vendor_code = db.Column(db.String(50), db.ForeignKey("hcs_vendors.code"), nullable=False)
    
    title = db.Column(db.String(200), nullable=False)  # "No Telnet"
    description = db.Column(db.Text)  # Описание уязвимости
    remediation = db.Column(db.Text)  # CLI команды для исправления
    
    # Типы: simple_match, regex_match, block_match, structure_check, meta_check
    logic_type = db.Column(db.String(30), nullable=False)
    logic_payload = db.Column(JSONB, nullable=False)  # Параметры проверки
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    # Relationships
    policy = db.relationship("Policy", back_populates="rules")
    vendor = db.relationship("Vendor", back_populates="rules")
    results = db.relationship("Result", back_populates="rule", lazy="dynamic")
    exceptions = db.relationship("RuleException", back_populates="rule", lazy="dynamic")
    
    def __repr__(self):
        return f"<Rule {self.title}>"
    
    def to_dict(self, include_payload=True):
        data = {
            "id": str(self.id),
            "policy_id": str(self.policy_id),
            "vendor_code": self.vendor_code,
            "title": self.title,
            "description": self.description,
            "remediation": self.remediation,
            "logic_type": self.logic_type,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_payload:
            data["logic_payload"] = self.logic_payload
        return data
