"""Vendor model - справочник вендоров оборудования."""
from app.extensions import db


class Vendor(db.Model):
    """Справочник вендоров с привязкой к парсер-драйверу."""
    
    __tablename__ = "hcs_vendors"
    
    code = db.Column(db.String(50), primary_key=True)  # cisco_ios, eltex_esr
    name = db.Column(db.String(100), nullable=False)
    parser_driver = db.Column(db.String(50))  # textfsm_ios, json_generic
    description = db.Column(db.Text)
    
    # Relationships
    rules = db.relationship("Rule", back_populates="vendor", lazy="dynamic")
    
    def __repr__(self):
        return f"<Vendor {self.code}>"
    
    def to_dict(self):
        return {
            "code": self.code,
            "name": self.name,
            "parser_driver": self.parser_driver,
            "description": self.description,
        }
