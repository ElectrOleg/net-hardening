"""DeviceGroup model - groups of devices with shared policies."""
import uuid
from sqlalchemy.dialects.postgresql import UUID
from app.extensions import db


class DeviceGroup(db.Model):
    """Device Group - for organizing devices and applying shared policies."""
    
    __tablename__ = "hcs_device_groups"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    
    # Hierarchical groups (optional)
    parent_id = db.Column(UUID(as_uuid=True), db.ForeignKey("hcs_device_groups.id"), nullable=True)
    parent = db.relationship("DeviceGroup", remote_side=[id], backref="children")
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    # Devices in this group
    devices = db.relationship("Device", back_populates="group")
    
    # M2M with Policies
    policies = db.relationship(
        "Policy",
        secondary="hcs_group_policies",
        backref=db.backref("device_groups", lazy="dynamic")
    )
    
    def __repr__(self):
        return f"<DeviceGroup {self.name}>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "is_active": self.is_active,
            "device_count": len(self.devices),
            "policies": [str(p.id) for p in self.policies],
        }


# M2M table for DeviceGroup <-> Policy
group_policies = db.Table(
    "hcs_group_policies",
    db.Column("group_id", UUID(as_uuid=True), db.ForeignKey("hcs_device_groups.id"), primary_key=True),
    db.Column("policy_id", UUID(as_uuid=True), db.ForeignKey("hcs_policies.id"), primary_key=True),
    db.Column("assigned_at", db.DateTime, server_default=db.func.now()),
)
